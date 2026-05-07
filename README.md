# 🏥 Healthcare Clinical Intelligence MCP

> **Agents Assemble Hackathon** — Superpower Submission  
> Built for the [Prompt Opinion](https://promptopinion.com) Platform

---

## What It Does

**Healthcare Clinical Intelligence** is an MCP server that gives any healthcare AI agent three powerful clinical decision-support capabilities — all integrated with FHIR R5 and the Prompt Opinion SHARP context extension.

| Tool | Category | FHIR Output |
|------|----------|-------------|
| `clinical_triage_tool` | Clinical Decision Support | `Observation` |
| `analyze_polypharmacy_tool` | Medication Safety | `MedicationRequest` (draft) |
| `get_clinical_guideline_tool` | Evidence-Based Medicine | `CarePlan` (draft) |

---

## Architecture

```
Prompt Opinion Platform
        │
        │  SHARP Headers (Patient ID, FHIR Token, Encounter ID)
        ▼
┌──────────────────────────────────┐
│      MCP Server (FastMCP)        │
│  ┌──────────┐  ┌──────────────┐  │
│  │  Triage  │  │ Polypharmacy │  │
│  │   Tool   │  │    Tool      │  │
│  └────┬─────┘  └──────┬───────┘  │
│       │               │          │
│  ┌────▼───────────────▼────────┐ │
│  │     Services Layer          │ │
│  │  FHIRClient · DrugEngine    │ │
│  │  GuidelineDB · SHARPBridge  │ │
│  └────────────────┬────────────┘ │
└───────────────────┼──────────────┘
                    │  FHIR R5 REST
                    ▼
            FHIR Server (EHR)
```

---

## Tools

### 1. `clinical_triage_tool`

AI-powered triage that assigns ESI-aligned priority and writes a structured **FHIR Observation** (LOINC 56839-4).

**Inputs:**
- `symptoms_json` — SNOMED-coded symptoms with severity 1–10
- `patient_id` — FHIR Patient ID
- `chief_complaint` — Primary presenting complaint
- `vital_signs_json` *(optional)* — BP, HR, SpO₂

**Output:**
```json
{
  "triage_priority": "stat",
  "risk_score": 95,
  "reasoning": "RED FLAG symptoms detected. Elevated BP and tachycardia.",
  "recommended_actions": ["Priority: STAT", "Estimated wait: 0 minutes"],
  "fhir_observation_reference": "https://fhir.example.com/Observation/123",
  "estimated_wait_minutes": 0
}
```

---

### 2. `analyze_polypharmacy_tool`

Detects drug-drug interactions, duplicate therapies, and organ-adjusted dosing risks. Generates a **FHIR MedicationRequest** draft for safer alternatives.

**Inputs:**
- `medications_json` — RxNorm-coded medications with dosage
- `patient_id` — FHIR Patient ID
- `allergies_json` *(optional)* — Known allergies
- `renal_function` *(optional)* — eGFR (mL/min/1.73m²)
- `hepatic_function` *(optional)* — Child-Pugh class

**Output:**
```json
{
  "overall_risk_score": 75,
  "risk_level": "HIGH",
  "interactions": [
    {
      "severity": "critical",
      "description": "Increased bleeding risk due to additive anticoagulant effects",
      "management": "Avoid combination unless strictly indicated with INR monitoring"
    }
  ],
  "renal_adjustments": ["Metformin: Contraindicated if eGFR <30 (eGFR: 28)"],
  "fhir_medication_request_reference": "https://fhir.example.com/MedicationRequest/456"
}
```

---

### 3. `get_clinical_guideline_tool`

Retrieves society-endorsed recommendations (ADA, ACC/AHA) for ICD-10 conditions and generates a **FHIR CarePlan** draft.

**Inputs:**
- `condition_code` — ICD-10 or SNOMED code (e.g., `E11`, `I10`)
- `condition_display` — Condition name
- `patient_id` — FHIR Patient ID
- `current_medications_json` *(optional)*
- `comorbidities_json` *(optional)*

**Output:**
```json
{
  "guideline_source": "ADA Standards of Care 2026",
  "recommendation": "Metformin remains first-line therapy for type 2 diabetes",
  "strength": "strong",
  "evidence_grade": "A",
  "applicable_medications": ["metformin"],
  "monitoring_requirements": ["eGFR annually", "HbA1c every 3 months"],
  "fhir_careplan_reference": "https://fhir.example.com/CarePlan/789"
}
```

---

## SHARP Context Propagation

This server is fully SHARP-aware. The Prompt Opinion platform injects patient context via headers:

| Header | Purpose |
|--------|---------|
| `X-SHARP-Patient-ID` | FHIR Patient.id |
| `X-SHARP-FHIR-Server` | FHIR base URL |
| `X-SHARP-Access-Token` | OAuth2 bearer token |
| `X-SHARP-Encounter-ID` | Active encounter reference |

When SHARP context is present, each tool automatically writes its output resource (Observation / MedicationRequest / CarePlan) to the patient's FHIR record. When no SHARP context is provided (e.g. local testing), the tools still return full clinical intelligence — FHIR writes are simply skipped.

---

## Quick Start

### Prerequisites
- Python 3.12+
- `pip install -r requirements.txt`

### Run the Demo
```bash
cd src/
python demo.py
```

### Run the MCP Server (stdio)
```bash
cd src/
python server.py
```

### Docker
```bash
docker build -f src/Dockerfile -t healthcare-mcp .
docker run -i healthcare-mcp
```

---

## Project Structure

```
healthcare-mcp-superpower/
├── requirements.txt
└── src/
    ├── server.py              # FastMCP server & tool registration
    ├── smithery.yaml          # Prompt Opinion Marketplace configuration
    ├── Dockerfile
    ├── demo.py                # Standalone demo / smoke tests
    ├── models/
    │   └── clinical_models.py # Pydantic v2 FHIR-aligned data models
    ├── services/
    │   ├── fhir_client.py     # FHIR R5 client + SHARP context bridge
    │   ├── drug_service.py    # Drug interaction engine
    │   └── guideline_service.py # Clinical guideline knowledge base
    └── tools/
        ├── triage_tool.py
        ├── pharmacy_tool.py
        └── guideline_tool.py
```

---

## Standards Compliance

- **FHIR R5** — Observation, MedicationRequest, CarePlan resources
- **SNOMED CT** — Symptom and procedure coding
- **LOINC** — Observation codes (56839-4 triage acuity)
- **RxNorm** — Medication coding
- **ICD-10** — Condition coding
- **MCP 1.6+** — FastMCP stdio transport
- **SHARP** — Prompt Opinion context propagation extension

---

## Hackathon Submission

**Category:** Superpower (MCP Server)  
**Platform:** Prompt Opinion Marketplace  
**Hackathon:** Agents Assemble — The Healthcare AI Endgame  
**Deadline:** May 12, 2026
