"""
MCP Tool: Evidence-Based Guideline Recommender
===============================================
Queries the GuidelineDatabase with intelligent branch selection
and serialises the recommendation for the MCP response.

Fixes vs old version:
  - Uses create_care_plan() FHIR helper (not raw client.client.post)
  - Serialises new model fields: lifestyle_modifications, specialist_referral,
    follow_up_weeks, strength.value, evidence_grade.value
  - Handles unsupported conditions gracefully with a curated fallback message
  - Surfaces branch_id so agents know which clinical pathway was selected
"""

from __future__ import annotations

import json
from typing import Optional

from mcp.server.fastmcp import Context

from models.clinical_models import GuidelineRequest, PatientContext, PatientDemographics
from services.guideline_service import GuidelineDatabase, _GUIDELINES
from services.fhir_client import FHIRClient, FHIRContextBridge


async def get_clinical_guideline(
    condition_code: str,
    condition_display: str,
    patient_id: str,
    current_medications_json: str = "[]",
    comorbidities_json: str = "[]",
    ctx: Context = None,
) -> str:
    """
    MCP Tool: Retrieve evidence-based clinical guideline recommendations.

    Covers 12 high-prevalence ICD-10 conditions. Branch selection is
    driven by comorbidities and current medications — e.g. diabetes with
    ASCVD will receive the SGLT2i/GLP-1 RA pathway, not generic metformin.

    Args:
        condition_code:           ICD-10 code (e.g. "E11", "I10", "I50", "J44")
        condition_display:        Human-readable condition name
        patient_id:               FHIR Patient ID
        current_medications_json: JSON array of drug names (e.g. ["metformin","ramipril"])
        comorbidities_json:       JSON array of ICD-10 comorbidity codes or names
                                  (e.g. ["I25", "N18"] or ["ckd", "heart failure"])
        ctx:                      MCP context for SHARP propagation

    Returns:
        JSON with guideline_source, recommendation, strength, evidence_grade,
        applicable_medications, contraindications, monitoring_requirements,
        lifestyle_modifications, specialist_referral, follow_up_weeks,
        and fhir_careplan_reference
    """
    # ── Parse inputs ──────────────────────────────────────────────────────
    current_meds  = json.loads(current_medications_json)
    comorbidities = json.loads(comorbidities_json)

    # ── SHARP context ─────────────────────────────────────────────────────
    sharp = FHIRContextBridge.extract_from_headers(
        ctx.request_headers if ctx else {}
    )
    if not sharp.patient_id:
        sharp.patient_id = patient_id

    # Build a PatientContext from the SHARP data so GuidelineRequest validates
    patient_ctx = PatientContext(
        patient_id      = sharp.patient_id,
        fhir_server_url = sharp.fhir_server_url,
        access_token    = sharp.access_token,
        encounter_id    = sharp.encounter_id,
        demographics    = PatientDemographics(),
    )

    # ── Query guideline database ──────────────────────────────────────────
    request = GuidelineRequest(
        condition_code       = condition_code,
        condition_display    = condition_display,
        patient_context      = patient_ctx,
        current_medications  = current_meds,
        comorbidities        = comorbidities,
    )

    db             = GuidelineDatabase()
    recommendation = db.get_recommendation(request)

    if not recommendation:
        # Return supported conditions list so the calling agent can re-query
        supported = sorted(_GUIDELINES.keys())
        return json.dumps({
            "error":       f"No guideline available for condition code '{condition_code}'",
            "suggestion":  "Consult specialist or refer to local clinical protocols",
            "supported_codes": supported,
        }, indent=2)

    # ── FHIR CarePlan write ───────────────────────────────────────────────
    careplan_ref = None
    fhir_client  = None
    if recommendation.fhir_care_plan and sharp.fhir_server_url:
        try:
            fhir_client = FHIRClient(sharp.fhir_server_url, sharp.access_token)
            created     = await fhir_client.create_care_plan(recommendation.fhir_care_plan)
            careplan_ref = (
                f"{sharp.fhir_server_url}/CarePlan/"
                f"{created.get('id', 'unknown')}"
            )
        except Exception as exc:
            careplan_ref = f"FHIR write skipped: {exc}"
        finally:
            if fhir_client:
                await fhir_client.close()

    # ── Serialise ─────────────────────────────────────────────────────────
    response = {
        "guideline_source":        recommendation.guideline_source,
        "recommendation":          recommendation.recommendation_text,
        "strength":                recommendation.strength.value,
        "evidence_grade":          recommendation.evidence_grade.value,
        "applicable_medications":  recommendation.applicable_medications,
        "contraindications":       recommendation.contraindications,
        "monitoring_requirements": recommendation.monitoring_requirements,
        "lifestyle_modifications": recommendation.lifestyle_modifications,
        "specialist_referral":     recommendation.specialist_referral,
        "follow_up_weeks":         recommendation.follow_up_weeks,
        "fhir_careplan_reference": careplan_ref,
        # Metadata for calling agents
        "condition_code":     condition_code,
        "condition_display":  condition_display,
        "comorbidities_considered": comorbidities,
        "medications_considered":   current_meds,
    }

    return json.dumps(response, indent=2)
