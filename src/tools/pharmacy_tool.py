"""
MCP Tool: Polypharmacy Risk Analyser
=====================================
Runs the DrugInteractionEngine and serialises results for the MCP response.
New fields surfaced vs old version:
  - allergy_alerts     (AllergyAlert objects)
  - qtc_prolongation_risk (bool)
  - risk_level         (LOW / MODERATE / HIGH / CRITICAL — from engine, not re-derived here)
  - per-interaction drug_a / drug_b names
  - FHIR write uses create_medication_request() helper (not raw client)
"""

from __future__ import annotations

import json
from typing import Optional

from mcp.server.fastmcp import Context

from models.clinical_models import MedicationInput
from services.drug_service import DrugInteractionEngine
from services.fhir_client import FHIRClient, FHIRContextBridge


async def analyze_polypharmacy(
    medications_json: str,
    patient_id: str,
    allergies_json: str = "[]",
    renal_function: Optional[str] = None,
    hepatic_function: Optional[str] = None,
    ctx: Context = None,
) -> str:
    """
    MCP Tool: Comprehensive polypharmacy and medication safety analysis.

    Args:
        medications_json:  JSON array [{code, display, dosage, route?, frequency?}]
        patient_id:        FHIR Patient ID
        allergies_json:    JSON array of known allergen names (e.g. ["penicillin","nsaid"])
        renal_function:    eGFR in mL/min/1.73m² as a string (e.g. "28")
        hepatic_function:  Child-Pugh class: "A", "B", or "C" (or "Child-Pugh B")
        ctx:               MCP context for SHARP context propagation

    Returns:
        JSON with risk_score, risk_level, interactions (with drug names), allergy_alerts,
        duplicate_therapies, renal_adjustments, hepatic_adjustments,
        qtc_prolongation_risk, and fhir_medication_request_reference
    """
    # ── Parse inputs ──────────────────────────────────────────────────────
    meds_data = json.loads(medications_json)
    allergies = json.loads(allergies_json)

    medications = [MedicationInput(**m) for m in meds_data]

    # ── SHARP context ─────────────────────────────────────────────────────
    sharp = FHIRContextBridge.extract_from_headers(
        ctx.request_headers if ctx else {}
    )
    if not sharp.patient_id:
        sharp.patient_id = patient_id

    # ── Safety analysis ───────────────────────────────────────────────────
    engine = DrugInteractionEngine()
    result = engine.analyse(
        medications      = medications,
        patient_context  = sharp,
        allergies        = allergies,
        renal_function   = renal_function,
        hepatic_function = hepatic_function,
    )

    # ── FHIR write ────────────────────────────────────────────────────────
    fhir_ref   = None
    fhir_client = None
    if result.fhir_medication_request and sharp.fhir_server_url:
        try:
            fhir_client = FHIRClient(sharp.fhir_server_url, sharp.access_token)
            created     = await fhir_client.create_medication_request(
                result.fhir_medication_request
            )
            fhir_ref = (
                f"{sharp.fhir_server_url}/MedicationRequest/"
                f"{created.get('id', 'unknown')}"
            )
        except Exception as exc:
            fhir_ref = f"FHIR write skipped: {exc}"
        finally:
            if fhir_client:
                await fhir_client.close()

    # ── Build clinical recommendation summary ─────────────────────────────
    if result.risk_level == "CRITICAL":
        recommendation = (
            "URGENT: One or more critical interactions or allergy alerts detected. "
            "Immediate medication review required before administration."
        )
    elif result.risk_level == "HIGH":
        recommendation = (
            "HIGH RISK: Significant drug interactions identified. "
            "Review with clinical pharmacist before dispensing. "
            "Consider proposed alternatives."
        )
    elif result.risk_level == "MODERATE":
        recommendation = (
            "MODERATE RISK: Clinically relevant interactions present. "
            "Review dosing, timing, and monitoring plan with prescriber."
        )
    else:
        recommendation = (
            "LOW RISK: No critical interactions identified. "
            "Continue routine monitoring per local protocol."
        )

    # ── Serialise ─────────────────────────────────────────────────────────
    response = {
        "overall_risk_score":  result.overall_risk_score,
        "risk_level":          result.risk_level,
        "qtc_prolongation_risk": result.qtc_prolongation_risk,
        "recommendation":      recommendation,
        "interactions": [
            {
                "drug_a":        ix.drug_a,
                "drug_b":        ix.drug_b,
                "severity":      ix.severity.value,
                "description":   ix.description,
                "mechanism":     ix.mechanism,
                "management":    ix.management,
                "evidence_level": ix.evidence_level.value,
                "qtc_risk":      ix.qtc_risk,
            }
            for ix in result.interactions
        ],
        "allergy_alerts": [
            {
                "drug":     alert.drug,
                "allergen": alert.allergen,
                "reaction": alert.reaction,
                "severity": alert.severity,
            }
            for alert in result.allergy_alerts
        ],
        "duplicate_therapies":  result.duplicate_therapies,
        "renal_adjustments":    result.renal_adjustments,
        "hepatic_adjustments":  result.hepatic_adjustments,
        "fhir_medication_request_reference": fhir_ref,
        "medications_analysed": len(medications),
        "total_findings": (
            len(result.interactions)
            + len(result.allergy_alerts)
            + len(result.duplicate_therapies)
            + len(result.renal_adjustments)
            + len(result.hepatic_adjustments)
        ),
    }

    return json.dumps(response, indent=2)
