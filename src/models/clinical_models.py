"""
Clinical data models — FHIR R5 aligned, Pydantic v2.

Design principles:
  - Every field maps to a named FHIR element; nothing is a free-form dict
    unless it IS a FHIR resource blob being passed to the server.
  - Enums are used for all controlled vocabularies so typos fail at
    validation time, not silently at runtime.
  - Optional fields carry explicit defaults so callers never get
    AttributeError on missing data.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

class TriagePriority(str, Enum):
    """
    ESI-5 / CTAS levels mapped to FHIR Encounter.priority v3 ActPriority codes.
    STAT   = ESI 1 — immediate, life threat
    ASAP   = ESI 2 — emergent, high risk
    URGENT = ESI 3 — urgent, stable but needs intervention
    ROUTINE= ESI 4-5 — non-urgent
    """
    ROUTINE = "routine"
    URGENT  = "urgent"
    ASAP    = "asap"
    STAT    = "stat"


class InteractionSeverity(str, Enum):
    CRITICAL = "critical"   # contraindicated / avoid
    MAJOR    = "major"      # may be life-threatening
    MODERATE = "moderate"   # may worsen condition
    MINOR    = "minor"      # minimally clinically significant


class EvidenceLevel(str, Enum):
    """AHA / ACC / ADA harmonised evidence grading"""
    A    = "A"     # multiple RCTs / meta-analyses
    B_R  = "B-R"   # single RCT
    B_NR = "B-NR"  # non-randomised
    C_LD = "C-LD"  # limited data
    C_EO = "C-EO"  # expert opinion
    # Shorthand used by older guidelines
    B    = "B"
    C    = "C"


class RecommendationStrength(str, Enum):
    STRONG      = "strong"       # benefits >> risks; "should"
    CONDITIONAL = "conditional"  # benefits > risks, but uncertain; "may"
    AGAINST     = "against"      # risks >> benefits


class BiologicalSex(str, Enum):
    MALE    = "male"
    FEMALE  = "female"
    OTHER   = "other"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Core clinical primitives
# ---------------------------------------------------------------------------

class VitalSigns(BaseModel):
    """Typed vital signs — avoids silent key-spelling errors from raw dicts."""
    systolic_bp:        Optional[float] = Field(None, ge=40,  le=300,  description="mmHg")
    diastolic_bp:       Optional[float] = Field(None, ge=20,  le=200,  description="mmHg")
    heart_rate:         Optional[float] = Field(None, ge=20,  le=300,  description="bpm")
    respiratory_rate:   Optional[float] = Field(None, ge=4,   le=60,   description="breaths/min")
    oxygen_saturation:  Optional[float] = Field(None, ge=50,  le=100,  description="SpO2 %")
    temperature:        Optional[float] = Field(None, ge=30,  le=44,   description="°C")
    gcs:                Optional[int]   = Field(None, ge=3,   le=15,   description="Glasgow Coma Scale")
    pain_score:         Optional[int]   = Field(None, ge=0,   le=10,   description="NRS pain 0–10")

    @model_validator(mode="after")
    def bp_ordering(self) -> "VitalSigns":
        if self.systolic_bp and self.diastolic_bp:
            if self.systolic_bp <= self.diastolic_bp:
                raise ValueError("systolic_bp must be greater than diastolic_bp")
        return self


class Symptom(BaseModel):
    """FHIR Condition / Observation aligned symptom."""
    code:      str = Field(..., description="SNOMED CT preferred code")
    display:   str = Field(..., description="Human-readable name")
    severity:  int = Field(..., ge=1, le=10, description="Patient-reported severity 1–10")
    onset:     Optional[datetime] = None
    body_site: Optional[str]      = None
    duration_hours: Optional[float] = Field(None, ge=0, description="How long symptom present")

    @field_validator("display", mode="before")
    @classmethod
    def normalise_display(cls, v: str) -> str:
        return v.strip().lower()


class PatientDemographics(BaseModel):
    """
    Clinically relevant demographics for risk stratification.
    Kept separate from identity to allow tools to work without PII.
    """
    age_years:  Optional[int]          = Field(None, ge=0, le=130)
    sex:        BiologicalSex          = BiologicalSex.UNKNOWN
    weight_kg:  Optional[float]        = Field(None, ge=1, le=500)
    height_cm:  Optional[float]        = Field(None, ge=30, le=250)
    pregnant:   bool                   = False
    smoker:     bool                   = False
    # Comorbidity flags for risk scoring
    has_diabetes:       bool = False
    has_hypertension:   bool = False
    has_heart_failure:  bool = False
    has_ckd:            bool = False
    has_copd:           bool = False
    has_liver_disease:  bool = False
    has_afib:           bool = False

    @property
    def bmi(self) -> Optional[float]:
        if self.weight_kg and self.height_cm and self.height_cm > 0:
            return round(self.weight_kg / (self.height_cm / 100) ** 2, 1)
        return None


class PatientContext(BaseModel):
    """SHARP context — bridges EHR session into the MCP tool chain."""
    patient_id:       str                         = Field(..., description="FHIR Patient.id")
    fhir_server_url:  Optional[str]               = None
    access_token:     Optional[str]               = Field(None, description="OAuth2 bearer")
    encounter_id:     Optional[str]               = None
    demographics:     PatientDemographics         = Field(default_factory=PatientDemographics)


# ---------------------------------------------------------------------------
# Triage models
# ---------------------------------------------------------------------------

class TriageRequest(BaseModel):
    symptoms:        List[Symptom]
    patient_context: PatientContext
    chief_complaint: str
    vital_signs:     Optional[VitalSigns] = None


class TriageResult(BaseModel):
    priority:             TriagePriority
    score:                int   = Field(..., ge=0, le=100)
    news2_score:          int   = Field(..., ge=0, le=20, description="NEWS2 aggregate score")
    reasoning:            str
    clinical_flags:       List[str]   = Field(default_factory=list)
    recommended_actions:  List[str]   = Field(default_factory=list)
    fhir_observation:     Dict[str, Any] = Field(default_factory=dict)
    estimated_wait_minutes: int


# ---------------------------------------------------------------------------
# Medication / Pharmacy models
# ---------------------------------------------------------------------------

class MedicationInput(BaseModel):
    code:       str  = Field(..., description="RxNorm CUI")
    display:    str
    dosage:     str
    route:      Optional[str] = None
    frequency:  Optional[str] = None

    @field_validator("display", mode="before")
    @classmethod
    def normalise(cls, v: str) -> str:
        return v.strip().lower()


class DrugInteraction(BaseModel):
    drug_a:         str
    drug_b:         str
    severity:       InteractionSeverity
    description:    str
    mechanism:      Optional[str] = None
    management:     str
    evidence_level: EvidenceLevel
    qtc_risk:       bool = False   # True when interaction prolongs QTc


class AllergyAlert(BaseModel):
    drug:       str
    allergen:   str
    reaction:   str
    severity:   str  # anaphylaxis / severe / moderate / mild


class PharmacyRequest(BaseModel):
    medications:       List[MedicationInput]
    patient_context:   PatientContext
    allergies:         List[str]             = Field(default_factory=list)
    renal_function:    Optional[str]         = None  # eGFR mL/min/1.73m²
    hepatic_function:  Optional[str]         = None  # Child-Pugh A/B/C


class PharmacyResult(BaseModel):
    interactions:              List[DrugInteraction]
    allergy_alerts:            List[AllergyAlert]
    duplicate_therapies:       List[str]
    renal_adjustments:         List[str]
    hepatic_adjustments:       List[str]
    qtc_prolongation_risk:     bool
    overall_risk_score:        int   = Field(..., ge=0, le=100)
    risk_level:                str   # LOW / MODERATE / HIGH / CRITICAL
    fhir_medication_request:   Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Guideline models
# ---------------------------------------------------------------------------

class GuidelineRequest(BaseModel):
    condition_code:        str  = Field(..., description="ICD-10 or SNOMED")
    condition_display:     str
    patient_context:       PatientContext
    current_medications:   List[str] = Field(default_factory=list)
    comorbidities:         List[str] = Field(default_factory=list)


class GuidelineActivity(BaseModel):
    """Single activity within a care plan."""
    action:       str
    snomed_code:  str
    snomed_display: str
    frequency:    Optional[str] = None
    target_value: Optional[str] = None


class CareRecommendation(BaseModel):
    guideline_source:       str
    recommendation_text:    str
    strength:               RecommendationStrength
    evidence_grade:         EvidenceLevel
    applicable_medications: List[str]
    contraindications:      List[str]
    monitoring_requirements: List[str]
    lifestyle_modifications: List[str]       = Field(default_factory=list)
    specialist_referral:     Optional[str]   = None
    follow_up_weeks:         Optional[int]   = None
    fhir_care_plan:          Optional[Dict[str, Any]] = None
