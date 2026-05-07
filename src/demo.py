#!/usr/bin/env python3
"""
Healthcare MCP Superpower — Standalone Demo
============================================
Exercises all three MCP tools without requiring a running MCP transport or
a live FHIR server.  The tools work in "offline" mode and produce the same
JSON output an agent would receive.

Usage:
    cd src/
    python demo.py
"""

import asyncio
import json
import sys
import os

# Make sure src/ is on the path whether run from repo root or from src/
sys.path.insert(0, os.path.dirname(__file__))

from tools.triage_tool import clinical_triage
from tools.pharmacy_tool import analyze_polypharmacy
from tools.guideline_tool import get_clinical_guideline


SEPARATOR = "\n" + "=" * 70 + "\n"


# ---------------------------------------------------------------------------
# Demo 1 — Clinical Triage
# ---------------------------------------------------------------------------

async def demo_triage() -> None:
    print(SEPARATOR)
    print("DEMO 1: Clinical Triage (STAT scenario)")
    print(SEPARATOR)

    symptoms = json.dumps([
        {"code": "29857009",  "display": "Chest pain",          "severity": 9},
        {"code": "230145002", "display": "Difficulty breathing", "severity": 8},
        {"code": "422587007", "display": "Nausea",               "severity": 4},
    ])
    vital_signs = json.dumps({
        "systolic_bp": 185,
        "heart_rate": 128,
        "oxygen_saturation": 89,
    })

    result = await clinical_triage(
        symptoms_json=symptoms,
        patient_id="patient-demo-001",
        chief_complaint="Crushing chest pain radiating to left arm, onset 30 minutes ago",
        vital_signs_json=vital_signs,
    )
    data = json.loads(result)
    print(json.dumps(data, indent=2))
    assert data["triage_priority"] == "stat", "Expected STAT priority for high-severity chest pain"
    print("\n✅  Triage priority correctly assessed as STAT")


# ---------------------------------------------------------------------------
# Demo 2 — Polypharmacy Analysis
# ---------------------------------------------------------------------------

async def demo_polypharmacy() -> None:
    print(SEPARATOR)
    print("DEMO 2: Polypharmacy Analysis (Warfarin + Aspirin critical interaction)")
    print(SEPARATOR)

    medications = json.dumps([
        {"code": "11289",  "display": "Warfarin", "dosage": "5mg daily"},
        {"code": "1191",   "display": "Aspirin",  "dosage": "81mg daily"},
        {"code": "860975", "display": "Metformin", "dosage": "1000mg twice daily"},
    ])
    allergies = json.dumps(["penicillin"])

    result = await analyze_polypharmacy(
        medications_json=medications,
        patient_id="patient-demo-001",
        allergies_json=allergies,
        renal_function="28",  # eGFR — will trigger metformin renal alert
    )
    data = json.loads(result)
    print(json.dumps(data, indent=2))
    assert data["overall_risk_score"] >= 50, "Expected HIGH risk for warfarin + aspirin + low eGFR"
    assert len(data["interactions"]) > 0, "Expected at least one drug interaction"
    print(f"\n✅  Identified {len(data['interactions'])} interaction(s), risk level: {data['risk_level']}")


# ---------------------------------------------------------------------------
# Demo 3 — Clinical Guideline (Type 2 Diabetes)
# ---------------------------------------------------------------------------

async def demo_guideline() -> None:
    print(SEPARATOR)
    print("DEMO 3: Evidence-Based Guideline — Type 2 Diabetes (ICD-10 E11)")
    print(SEPARATOR)

    current_meds = json.dumps(["lisinopril", "atorvastatin"])
    comorbidities = json.dumps(["I10"])  # Hypertension

    result = await get_clinical_guideline(
        condition_code="E11",
        condition_display="Type 2 Diabetes Mellitus",
        patient_id="patient-demo-001",
        current_medications_json=current_meds,
        comorbidities_json=comorbidities,
    )
    data = json.loads(result)
    print(json.dumps(data, indent=2))
    assert "metformin" in [m.lower() for m in data.get("applicable_medications", [])], \
        "Expected metformin as first-line recommendation"
    print(f"\n✅  Guideline: {data['guideline_source']} | Strength: {data['strength']} | Grade: {data['evidence_grade']}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def main() -> None:
    print("\n🏥  Healthcare MCP Superpower — Demo Runner")
    print("Built for the Agents Assemble Hackathon (Prompt Opinion)\n")

    try:
        await demo_triage()
        await demo_polypharmacy()
        await demo_guideline()

        print(SEPARATOR)
        print("🎉  All demos completed successfully!")
        print("    The MCP server is ready to publish to the Prompt Opinion Marketplace.")
        print(SEPARATOR)

    except AssertionError as exc:
        print(f"\n❌  Assertion failed: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n❌  Unexpected error: {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
