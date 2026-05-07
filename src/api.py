#!/usr/bin/env python3
"""
Healthcare MCP Superpower — REST API
=====================================
FastAPI wrapper around the three MCP tools so any frontend,
curl, or Postman client can call them without needing MCP transport.

Run:
    cd src/
    uvicorn api:app --reload --port 8000
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os as _os

# ── Import our clinical tools ──────────────────────────────────────────────
from tools.triage_tool import clinical_triage
from tools.pharmacy_tool import analyze_polypharmacy
from tools.guideline_tool import get_clinical_guideline
from services.guideline_service import _GUIDELINES

app = FastAPI(
    title="Healthcare Clinical Intelligence API",
    description="AI-powered clinical decision support: triage, polypharmacy safety, and evidence-based guidelines.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response schemas ────────────────────────────────────────────

class SymptomIn(BaseModel):
    code: str
    display: str
    severity: int  # 1-10

class VitalSignsIn(BaseModel):
    systolic_bp: Optional[float] = None
    diastolic_bp: Optional[float] = None
    heart_rate: Optional[float] = None
    respiratory_rate: Optional[float] = None
    oxygen_saturation: Optional[float] = None
    temperature: Optional[float] = None
    gcs: Optional[int] = None
    pain_score: Optional[int] = None

class TriageRequest(BaseModel):
    symptoms: List[SymptomIn]
    patient_id: str = "demo-patient"
    chief_complaint: str
    vital_signs: Optional[VitalSignsIn] = None
    age_years: Optional[int] = None
    sex: str = "unknown"
    pregnant: bool = False
    has_copd: bool = False

class MedicationIn(BaseModel):
    code: str
    display: str
    dosage: str
    route: Optional[str] = None

class PharmacyRequest(BaseModel):
    medications: List[MedicationIn]
    patient_id: str = "demo-patient"
    allergies: List[str] = []
    renal_function: Optional[str] = None
    hepatic_function: Optional[str] = None

class GuidelineRequest(BaseModel):
    condition_code: str
    condition_display: str
    patient_id: str = "demo-patient"
    current_medications: List[str] = []
    comorbidities: List[str] = []


# ── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False, response_class=HTMLResponse)
async def root():
    # Serve the frontend HTML — walk up from src/ to find frontend/index.html
    _src_dir = _os.path.dirname(_os.path.abspath(__file__))
    _html    = _os.path.join(_src_dir, "..", "frontend", "index.html")
    if _os.path.isfile(_html):
        return HTMLResponse(content=open(_html, encoding="utf-8").read())
    return HTMLResponse("<h2>Frontend not found — make sure frontend/index.html exists next to the src/ folder.</h2>", status_code=404)

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/guidelines/supported")
async def supported_guidelines():
    """Return all supported ICD-10 condition codes."""
    return {
        "supported_conditions": [
            {"code": code, "source": entry["source"]}
            for code, entry in _GUIDELINES.items()
        ]
    }

@app.post("/triage")
async def triage(req: TriageRequest) -> Dict[str, Any]:
    """
    AI-powered clinical triage using NEWS2 + ESI-5.
    Returns priority (routine/urgent/asap/stat), NEWS2 score, risk score, and recommended actions.
    """
    try:
        vitals_json = json.dumps(req.vital_signs.model_dump(exclude_none=True) if req.vital_signs else {})
        result_str = await clinical_triage(
            symptoms_json    = json.dumps([s.model_dump() for s in req.symptoms]),
            patient_id       = req.patient_id,
            chief_complaint  = req.chief_complaint,
            vital_signs_json = vitals_json,
            age_years        = req.age_years,
            sex              = req.sex,
            pregnant         = req.pregnant,
            has_copd         = req.has_copd,
        )
        return json.loads(result_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/pharmacy")
async def pharmacy(req: PharmacyRequest) -> Dict[str, Any]:
    """
    Polypharmacy safety analysis: drug interactions, allergy alerts,
    QTc risk, renal/hepatic dosing, and therapeutic duplicates.
    """
    try:
        result_str = await analyze_polypharmacy(
            medications_json = json.dumps([m.model_dump() for m in req.medications]),
            patient_id       = req.patient_id,
            allergies_json   = json.dumps(req.allergies),
            renal_function   = req.renal_function,
            hepatic_function = req.hepatic_function,
        )
        return json.loads(result_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/guideline")
async def guideline(req: GuidelineRequest) -> Dict[str, Any]:
    """
    Evidence-based clinical guideline recommendations.
    Intelligent branch selection based on comorbidities and current medications.
    """
    try:
        result_str = await get_clinical_guideline(
            condition_code           = req.condition_code,
            condition_display        = req.condition_display,
            patient_id               = req.patient_id,
            current_medications_json = json.dumps(req.current_medications),
            comorbidities_json       = json.dumps(req.comorbidities),
        )
        return json.loads(result_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
