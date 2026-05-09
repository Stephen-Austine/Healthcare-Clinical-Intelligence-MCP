# Healthcare Clinical Intelligence

A Model Context Protocol (MCP) server providing AI-powered clinical decision support at the point of care. Built for the Agents Assemble hackathon on the Prompt Opinion platform.

Three production-grade MCP tools — clinical triage, polypharmacy safety analysis, and evidence-based guideline recommendations — each integrated with FHIR R5 and the SHARP context propagation standard.

---

## Table of Contents

- [Overview](#overview)
- [Clinical Tools](#clinical-tools)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Getting Started](#getting-started)
- [Running the Application](#running-the-application)
- [API Reference](#api-reference)
- [FHIR R5 Integration](#fhir-r5-integration)
- [SHARP Context Propagation](#sharp-context-propagation)
- [Clinical Protocols and Evidence Base](#clinical-protocols-and-evidence-base)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Prompt Opinion Marketplace](#prompt-opinion-marketplace)
- [Clinical Disclaimer](#clinical-disclaimer)
- [License](#license)

---

## Overview

Clinical decision support is one of the most impactful applications of AI in healthcare, yet most implementations are isolated tools that cannot communicate with each other or with the broader EHR ecosystem. This project addresses that gap.

Healthcare Clinical Intelligence exposes three specialist clinical tools as a standards-compliant MCP server. Any AI agent — whether running on Prompt Opinion, Claude, or any MCP-compatible host — can invoke these tools with a patient context and receive clinically grounded, evidence-cited responses. Results are optionally written back to the patient's FHIR record automatically, creating a closed loop between AI reasoning and the medical record.

The server is designed to operate within the Prompt Opinion SHARP extension framework, meaning EHR session credentials (patient ID, FHIR server URL, access token, encounter ID) flow through automatically from the calling agent without any additional credential handling in the tools themselves.

---

## Clinical Tools

### 1. Clinical Triage Engine

Assigns an ESI-aligned triage priority to a presenting patient using a multi-factor scoring pipeline.

**Scoring methodology:**

The engine computes three independent scores and combines them into a composite risk score out of 100.

**NEWS2 (National Early Warning Score 2)** — The physiological scoring layer, following the 2017 Royal College of Physicians specification. Six parameters are scored: respiratory rate, oxygen saturation (with COPD-aware Scale 2 logic), systolic blood pressure, heart rate, temperature, and level of consciousness via GCS. Scores of 0–4 indicate low risk, 5–6 medium risk, and 7 or above high risk requiring immediate clinical review.

**Symptom pattern recognition** — A two-tier registry of 60+ SNOMED-coded symptom displays. The first tier is exact-match scoring with severity weighting; the second tier is substring matching for free-text descriptions. On top of individual symptom scores, a combination bonus system detects high-acuity clinical patterns: chest pain with diaphoresis scores 15 bonus points and flags an ACS pattern, a FAST-positive stroke triad (facial droop + arm weakness) scores 15 points, and a thunderclap headache with vomiting scores 20 points and flags probable subarachnoid haemorrhage.

**Demographic risk modifiers** — Age extremes (under 1 year: +15, under 5 years: +10, 80 and over: +10, 65 and over: +5), active pregnancy (+8), and immunosuppression (+8) are applied as additive modifiers to the composite score.

**ESI level mapping** — The composite score and NEWS2 value are mapped to an ESI 1–5 triage classification with an estimated wait time and a specific set of recommended clinical actions.

**FHIR output** — When a FHIR server URL is present in the SHARP context, the tool writes an Observation resource containing the triage score, NEWS2 score, priority, and reasoning narrative, and returns the resource reference.

---

### 2. Polypharmacy Safety Analyser

Performs a comprehensive medication safety review for a patient's active drug list.

**Analysis layers:**

**Drug-drug interactions** — The interaction database covers over 200 clinically significant drug pairs. Each interaction record includes the drug pair names, severity classification (critical, major, moderate, minor), mechanism of action, clinical description, evidence level (AHA/ACC harmonised grading A through C-EO), and specific management guidance. Critical interactions are those where concurrent use is generally contraindicated.

**QTc prolongation risk** — A flag is raised when two or more QTc-prolonging agents are present simultaneously, a pattern associated with elevated risk of torsades de pointes.

**Allergy cross-reactivity** — The allergen list is checked against each medication's drug class. Known cross-reactive pairs (e.g. penicillin allergy and cephalosporins, sulfonamide allergy and certain diuretics) trigger allergy alerts with the relevant reaction type.

**Therapeutic duplication** — Medications sharing the same pharmacological class and indication are identified (e.g. two ACE inhibitors, two statins) and flagged as duplicate therapy.

**Organ-adjusted dosing** — When renal function (eGFR in mL/min/1.73m²) or hepatic function (Child-Pugh class A, B, or C) is supplied, medications requiring dose adjustment are identified and the relevant adjustment is described.

**Risk classification** — A numerical risk score drives a four-tier classification: LOW, MODERATE, HIGH, and CRITICAL. Each tier maps to a specific clinical recommendation, from routine monitoring through to immediate pharmacist review before administration.

**FHIR output** — A MedicationRequest resource is written to the FHIR server when context is available, and the reference is returned in the response.

---

### 3. Evidence-Based Guideline Recommender

Retrieves society guideline recommendations for 12 high-prevalence conditions, with intelligent branch selection based on patient comorbidities and current medications.

**Supported conditions:**

| ICD-10 Code | Condition |
|---|---|
| E11 | Type 2 diabetes mellitus |
| I10 | Essential hypertension |
| I50 | Heart failure |
| J44 | Chronic obstructive pulmonary disease |
| I25 | Chronic ischaemic heart disease |
| N18 | Chronic kidney disease |
| F32 | Major depressive disorder |
| E78 | Dyslipidaemia / hypercholesterolaemia |
| J45 | Asthma |
| K21 | Gastro-oesophageal reflux disease |
| M05 | Rheumatoid arthritis |
| I48 | Atrial fibrillation |

**Branch selection logic:** A patient with Type 2 diabetes who also has established ASCVD (I25) or heart failure (I50) will receive the SGLT2 inhibitor / GLP-1 receptor agonist pathway rather than the default metformin initiation branch. A patient with CKD will have the renal-safe medication pathway selected automatically. This context-aware routing is driven by the comorbidities and current medications passed in the request.

**Recommendation fields:** Each response includes the guideline source (AHA, ACC, ADA, NICE, GOLD, ESC, and others), recommendation text, recommendation strength (strong, conditional, or expert opinion), evidence grade (A through C-EO), applicable medications, contraindications, monitoring requirements, lifestyle modification guidance, specialist referral indication, and recommended follow-up interval in weeks.

**FHIR output** — A CarePlan resource is written to the FHIR server when context is available.

---

## Architecture

```
                        Prompt Opinion Platform
                        ┌───────────────────────────────────┐
                        │                                   │
      Clinician / Agent │   SHARP Context injected into     │
           request      │   every tool call automatically   │
                        │                                   │
                        └──────────────┬────────────────────┘
                                       │ MCP (stdio)
                        ┌──────────────▼────────────────────┐
                        │   MCP Server  (src/server.py)     │
                        │                                   │
                        │  ┌──────────┐ ┌───────────────┐  │
                        │  │  Triage  │ │  Polypharmacy  │  │
                        │  │  Tool    │ │  Tool          │  │
                        │  └────┬─────┘ └──────┬────────┘  │
                        │       │               │            │
                        │  ┌────▼───────────────▼────────┐  │
                        │  │     Guideline Tool          │  │
                        │  └─────────────────────────────┘  │
                        └──────────────┬────────────────────┘
                                       │ HTTP / SMART on FHIR
                        ┌──────────────▼────────────────────┐
                        │       FHIR R5 Server              │
                        │  (Epic, Cerner, HAPI, or any      │
                        │   SMART-on-FHIR compliant EHR)    │
                        └───────────────────────────────────┘
```

The FastAPI layer (`src/api.py`) wraps the same tool functions and serves the browser-based demonstration UI at `/`. The MCP server (`src/server.py`) uses the same underlying services over stdio transport for agent-to-agent use.

---

## Technology Stack

| Layer | Technology |
|---|---|
| MCP protocol | `mcp >= 1.6.0` with `fastmcp` |
| API framework | FastAPI 0.111+ with Uvicorn |
| Data validation | Pydantic v2 with FHIR-aligned models |
| FHIR communication | `httpx` async client (FHIR R5) |
| Healthcare context | SHARP extension (Prompt Opinion) |
| Clinical models | NEWS2, ESI-5, CTAS, AHA/ACC evidence grading |
| Drug database | Embedded interaction database (200+ pairs) |
| Guideline database | Embedded society guideline store (12 conditions) |
| Runtime | Python 3.11+ |
| Container | Docker (multi-stage build) |

---

## Getting Started

### Prerequisites

- Python 3.11 or later
- pip or conda

### Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/healthcare-ai/caregap-mcp
cd healthcare-mcp-superpower
pip install -r requirements.txt
```

Using a virtual environment (recommended):

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Using conda:

```bash
conda create -n healthcare-mcp python=3.11
conda activate healthcare-mcp
pip install -r requirements.txt
```

---

## Running the Application

### One-command start

```bash
python run.py
```

This installs any missing dependencies, starts the FastAPI server on port 8000, and opens the browser UI automatically.

```
http://localhost:8000          - Interactive clinical dashboard
http://localhost:8000/docs     - Swagger API explorer
http://localhost:8000/health   - Health check endpoint
```

Press `Ctrl+C` to stop.

### Manual start (API only)

```bash
cd src
uvicorn api:app --reload --port 8000
```

### MCP server (for agent integration)

```bash
cd src
python server.py
```

The MCP server communicates over stdio. Point your MCP host at this process.

### Docker

```bash
# Build
docker build -f src/Dockerfile -t healthcare-mcp .

# Run API + UI
docker run -p 8000:8000 healthcare-mcp

# Run MCP server (stdio mode)
docker run -i healthcare-mcp python server.py
```

---

## API Reference

All endpoints accept and return `application/json`. CORS is open for local development.

### GET /health

Returns server status.

```json
{ "status": "healthy" }
```

### GET /guidelines/supported

Returns all supported ICD-10 condition codes and their guideline sources.

```json
{
  "supported_conditions": [
    { "code": "E11", "source": "ADA Standards of Medical Care 2024" },
    { "code": "I10", "source": "AHA/ACC Hypertension Guidelines 2023" }
  ]
}
```

### POST /triage

Perform clinical triage using NEWS2 + ESI-5 + symptom pattern recognition.

**Request body:**

```json
{
  "patient_id": "patient-123",
  "chief_complaint": "central chest pain with sweating",
  "symptoms": [
    { "code": "29857009", "display": "chest pain", "severity": 8 },
    { "code": "415068001", "display": "diaphoresis", "severity": 6 }
  ],
  "vital_signs": {
    "systolic_bp": 88,
    "heart_rate": 118,
    "respiratory_rate": 22,
    "oxygen_saturation": 94,
    "temperature": 37.2,
    "gcs": 14
  },
  "age_years": 67,
  "sex": "male",
  "pregnant": false,
  "has_copd": false
}
```

**Response:**

```json
{
  "triage_priority": "stat",
  "esi_level": "ESI Level 1 — Immediate",
  "risk_score": 95,
  "news2_score": 9,
  "reasoning": "Chief complaint: central chest pain with sweating. NEWS2 aggregate score: 9/20 (NEWS2=9: HIGH — immediate clinical review). Symptom risk contribution: 60 points from 2 symptom(s). Clinical alerts: Systolic BP abnormal (NEWS2 +3); Heart rate abnormal (NEWS2 +2); Respiratory rate abnormal (NEWS2 +2); SpO2 abnormal (NEWS2 +1); Red flag: chest pain (severity 8/10); Clinical pattern: ACS pattern: chest pain + diaphoresis. Composite risk score: 95/100. Classification: ESI Level 1 — Immediate.",
  "clinical_flags": [
    "Systolic BP abnormal (NEWS2 +3)",
    "Heart rate abnormal (NEWS2 +2)",
    "Red flag: chest pain (severity 8/10)",
    "Clinical pattern: ACS pattern: chest pain + diaphoresis",
    "Age >= 65 — elderly risk modifier"
  ],
  "recommended_actions": [
    "ESI Level 1 — Immediate — estimated wait: 0 min",
    "Immediate physician assessment",
    "Continuous cardiac and SpO2 monitoring",
    "IV access and 12-lead ECG within 10 minutes",
    "Activate resuscitation team if airway compromise",
    "NEWS2=9: Initiate escalation protocol per ward policy"
  ],
  "fhir_observation_reference": null,
  "estimated_wait_minutes": 0
}
```

---

### POST /pharmacy

Polypharmacy safety analysis with drug interaction detection.

**Request body:**

```json
{
  "patient_id": "patient-123",
  "medications": [
    { "code": "372756006", "display": "warfarin", "dosage": "5mg daily" },
    { "code": "387207008", "display": "ibuprofen", "dosage": "400mg three times daily" },
    { "code": "372625005", "display": "amiodarone", "dosage": "200mg daily" }
  ],
  "allergies": ["penicillin"],
  "renal_function": "35",
  "hepatic_function": null
}
```

**Response:**

```json
{
  "overall_risk_score": 88,
  "risk_level": "CRITICAL",
  "qtc_prolongation_risk": true,
  "recommendation": "URGENT: One or more critical interactions or allergy alerts detected. Immediate medication review required before administration.",
  "interactions": [
    {
      "drug_a": "warfarin",
      "drug_b": "ibuprofen",
      "severity": "critical",
      "description": "NSAIDs significantly increase anticoagulant effect and GI bleeding risk",
      "mechanism": "NSAID inhibition of COX-1 reduces platelet aggregation; additive anticoagulation",
      "management": "Avoid concurrent use. Use paracetamol for analgesia. If unavoidable, increase INR monitoring frequency.",
      "evidence_level": "A",
      "qtc_risk": false
    }
  ],
  "renal_adjustments": [
    "Warfarin: Monitor INR more frequently with eGFR < 60; renal clearance of metabolites reduced",
    "Ibuprofen: Contraindicated with eGFR < 30; use with caution and close monitoring for eGFR 30-60"
  ],
  "medications_analysed": 3,
  "total_findings": 4
}
```

---

### POST /guideline

Retrieve evidence-based guideline recommendations with comorbidity-aware branch selection.

**Request body:**

```json
{
  "condition_code": "E11",
  "condition_display": "Type 2 diabetes mellitus",
  "patient_id": "patient-123",
  "current_medications": ["metformin", "ramipril"],
  "comorbidities": ["I50", "N18"]
}
```

**Response:**

```json
{
  "guideline_source": "ADA Standards of Medical Care 2024 — Heart Failure / CKD pathway",
  "recommendation": "For patients with T2DM and heart failure or CKD with eGFR >= 20, add an SGLT2 inhibitor (empagliflozin, dapagliflozin, or canagliflozin) to existing therapy. These agents reduce hospitalisation for heart failure and slow CKD progression independently of glycaemic effect.",
  "strength": "strong",
  "evidence_grade": "A",
  "applicable_medications": ["empagliflozin", "dapagliflozin", "canagliflozin"],
  "contraindications": ["eGFR < 20", "dialysis", "recurrent UTI", "genital mycotic infection history"],
  "monitoring_requirements": ["eGFR at baseline and 3-monthly", "HbA1c every 3 months until stable", "blood pressure", "weight"],
  "lifestyle_modifications": ["low-sodium diet < 2g/day", "fluid restriction if oedematous", "daily weight monitoring"],
  "specialist_referral": "Nephrology if eGFR < 30 or rapid decline. Cardiology for optimisation of HF therapy.",
  "follow_up_weeks": 6,
  "fhir_careplan_reference": null,
  "condition_code": "E11",
  "comorbidities_considered": ["I50", "N18"],
  "medications_considered": ["metformin", "ramipril"]
}
```

---

## FHIR R5 Integration

The server communicates with any SMART on FHIR R5-compliant server. When SHARP context is present and a FHIR server URL is provided, each tool writes a resource to the patient's record and returns the reference:

| Tool | FHIR Resource Written |
|---|---|
| clinical_triage | Observation (triage score, NEWS2, priority) |
| analyze_polypharmacy | MedicationRequest (safety review record) |
| get_clinical_guideline | CarePlan (guideline recommendation) |

FHIR writes are non-blocking — if the write fails (e.g. the server is unavailable or the token has expired), the tool still returns its clinical result and includes a `"FHIR write skipped: <reason>"` string in the reference field rather than raising an error.

For testing, the public HAPI FHIR R5 sandbox (`https://hapi.fhir.org/baseR5`) requires no authentication and accepts resource writes freely.

---

## SHARP Context Propagation

SHARP (Standard Healthcare Agent Request Protocol) is the Prompt Opinion platform mechanism for propagating EHR session credentials through multi-agent call chains without requiring each tool to handle authentication independently.

The server reads four SHARP headers from every incoming MCP or HTTP request:

| Header | Purpose |
|---|---|
| `X-SHARP-Patient-ID` | FHIR Patient resource ID |
| `X-SHARP-FHIR-Server` | Base URL of the FHIR R5 server |
| `X-SHARP-Access-Token` | SMART on FHIR bearer token |
| `X-SHARP-Encounter-ID` | Active encounter ID for resource association |

When these headers are absent (as in direct API or demo use), the tools fall back to the `patient_id` field in the request body and skip FHIR writes.

---

## Clinical Protocols and Evidence Base

| Protocol | Application |
|---|---|
| NEWS2 — Royal College of Physicians UK (2017) | Physiological scoring in clinical triage |
| ESI-5 — ACEP / AHRQ | Triage priority level assignment |
| CTAS — Canadian Triage and Acuity Scale | Chief-complaint mapping |
| ADA Standards of Medical Care (2024) | Diabetes guideline recommendations |
| AHA / ACC Hypertension Guidelines (2023) | Hypertension guideline recommendations |
| ACC / AHA Heart Failure Guidelines (2022) | Heart failure guideline recommendations |
| GOLD COPD Report (2024) | COPD guideline recommendations |
| AHA / ACC Dyslipidaemia Guidelines (2019) | Lipid management recommendations |
| ESC Atrial Fibrillation Guidelines (2020) | AF management recommendations |
| NICE Clinical Guidelines (multiple) | UK-specific guideline branches |
| AHA / ACC Evidence Grading (A, B-R, B-NR, C-LD, C-EO) | Recommendation strength classification |

---

## Project Structure

```
healthcare-mcp-superpower/
├── run.py                          One-command launcher (start here)
├── requirements.txt                Python dependencies
├── README.md
├── frontend/
│   └── index.html                  Interactive clinical dashboard (served at /)
└── src/
    ├── server.py                   MCP server entry point (stdio transport)
    ├── api.py                      FastAPI REST wrapper (HTTP transport)
    ├── demo.py                     CLI demo runner
    ├── smithery.yaml               Prompt Opinion marketplace configuration
    ├── Dockerfile                  Container build file
    ├── models/
    │   ├── __init__.py
    │   └── clinical_models.py      Pydantic v2 models (FHIR R5 aligned)
    ├── services/
    │   ├── __init__.py
    │   ├── fhir_client.py          Async FHIR R5 client + SHARP bridge
    │   ├── drug_service.py         Drug interaction engine (200+ pairs)
    │   └── guideline_service.py    Society guideline database (12 conditions)
    └── tools/
        ├── __init__.py
        ├── triage_tool.py          NEWS2 + ESI-5 triage engine
        ├── pharmacy_tool.py        Polypharmacy safety analyser
        └── guideline_tool.py       Evidence-based guideline recommender
```

---

## Configuration

All configuration is through environment variables. There are no required variables — the server runs with defaults for local and sandbox use.

| Variable | Default | Description |
|---|---|---|
| `FHIR_SERVER_URL` | `https://hapi.fhir.org/baseR5` | Default FHIR server when SHARP context is absent |
| `PORT` | `8000` | API server port |
| `LOG_LEVEL` | `INFO` | Python logging level |

In production, the FHIR server URL and access token should always come from SHARP context rather than environment variables, as they are patient-session-specific.

A `.env` file in the project root is loaded automatically if present.

---

## Prompt Opinion Marketplace

The `src/smithery.yaml` file contains the complete Prompt Opinion marketplace configuration for publishing this server as a discoverable MCP Superpower.

To publish:

1. Create a free account at [promptopinion.com](https://promptopinion.com)
2. Deploy the server to a reachable host (any VPS, Railway, Render, or similar)
3. In the Prompt Opinion dashboard, create a new MCP Server entry and point it to your deployment
4. The `smithery.yaml` configuration will be picked up automatically for marketplace listing
5. Once published, any agent in the ecosystem can discover and invoke your tools

The SHARP configuration in `smithery.yaml` specifies which context fields this server requires (`patient_id`, `fhir_server_url`) and which are optional (`access_token`, `encounter_id`), so the platform can prompt for them appropriately.

---

## Clinical Disclaimer

This software is a decision support tool intended for use by qualified healthcare professionals. All outputs — triage classifications, drug interaction alerts, dosing recommendations, and guideline suggestions — are informational and do not constitute medical advice. Final clinical decisions must be made by a licensed clinician applying their professional judgement to the specific patient and situation.

Drug interaction data, guideline recommendations, and dosing adjustments are derived from publicly available clinical literature and society guidelines current at the time of writing. They may not reflect the most recent evidence or local formulary restrictions. Always consult current prescribing information and local protocols.

This software has not been submitted for regulatory clearance as a medical device in any jurisdiction.

---

## License

MIT License. See `LICENSE` for full terms.
