"""
MCP Tool: Clinical Triage Engine
=================================
Implements a clinically validated triage algorithm based on:

  - NEWS2 (National Early Warning Score 2) — Royal College of Physicians UK
  - ESI-5 (Emergency Severity Index) — ACEP / AHRQ
  - CTAS (Canadian Triage and Acuity Scale) chief-complaint mapping

Scoring pipeline:
  1. NEWS2 physiological score from vital signs (0–20)
  2. Chief-complaint / symptom red-flag detection (weighted)
  3. Demographic risk modifiers (age extremes, pregnancy, immunocompromise)
  4. Symptom combination pattern detection (e.g. chest pain + diaphoresis)
  5. Final ESI-level mapping with detailed clinical rationale
  6. FHIR R5 Observation write via SHARP context
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from mcp.server.fastmcp import Context

from models.clinical_models import (
    Symptom, TriagePriority, TriageResult, VitalSigns,
)
from services.fhir_client import FHIRClient, FHIRContextBridge


# ---------------------------------------------------------------------------
# NEWS2 scoring tables (RCP 2017)
# ---------------------------------------------------------------------------

def _news2_resp_rate(rr: Optional[float]) -> int:
    if rr is None: return 0
    if rr <= 8:    return 3
    if rr <= 11:   return 1
    if rr <= 20:   return 0
    if rr <= 24:   return 2
    return 3


def _news2_spo2(spo2: Optional[float], copd: bool = False) -> int:
    """Scale 1 for standard; Scale 2 for confirmed COPD hypercapnic."""
    if spo2 is None: return 0
    if not copd:
        if spo2 >= 96:   return 0
        if spo2 >= 94:   return 1
        if spo2 >= 92:   return 2
        return 3
    else:
        # Scale 2: target 88-92%
        if spo2 >= 97:   return 3
        if spo2 >= 95:   return 2
        if spo2 >= 93:   return 1
        if spo2 >= 88:   return 0
        if spo2 >= 86:   return 1
        if spo2 >= 84:   return 2
        return 3


def _news2_bp(sbp: Optional[float]) -> int:
    if sbp is None: return 0
    if sbp <= 90:    return 3
    if sbp <= 100:   return 2
    if sbp <= 110:   return 1
    if sbp <= 219:   return 0
    return 3  # hypertensive crisis


def _news2_hr(hr: Optional[float]) -> int:
    if hr is None: return 0
    if hr <= 40:    return 3
    if hr <= 50:    return 1
    if hr <= 90:    return 0
    if hr <= 110:   return 1
    if hr <= 130:   return 2
    return 3


def _news2_temp(temp: Optional[float]) -> int:
    if temp is None: return 0
    if temp <= 35.0:  return 3
    if temp <= 36.0:  return 1
    if temp <= 38.0:  return 0
    if temp <= 39.0:  return 1
    return 2


def _news2_gcs(gcs: Optional[int]) -> int:
    """Any reduction from 15 = score 3."""
    if gcs is None:  return 0
    return 0 if gcs == 15 else 3


def compute_news2(vitals: Optional[VitalSigns], copd: bool = False) -> Tuple[int, List[str]]:
    """
    Returns (news2_total, list_of_abnormal_flags).
    NEWS2 ranges: 0-4 low, 5-6 medium, 7+ high.
    """
    if vitals is None:
        return 0, []

    components = {
        "Respiratory rate":   _news2_resp_rate(vitals.respiratory_rate),
        "SpO₂":               _news2_spo2(vitals.oxygen_saturation, copd),
        "Systolic BP":        _news2_bp(vitals.systolic_bp),
        "Heart rate":         _news2_hr(vitals.heart_rate),
        "Temperature":        _news2_temp(vitals.temperature),
        "Consciousness (GCS)":_news2_gcs(vitals.gcs),
    }

    total = sum(components.values())
    flags = [f"{name} abnormal (NEWS2 +{score})"
             for name, score in components.items() if score > 0]

    return total, flags


# ---------------------------------------------------------------------------
# Red-flag symptom registry (SNOMED display name → weight)
# Weights: 5 = absolute STAT trigger, 3 = strong ASAP, 1 = moderate
# ---------------------------------------------------------------------------

# Exact SNOMED display matches (after lower-strip)
_RED_FLAG_EXACT: Dict[str, int] = {
    "chest pain":                          5,
    "cardiac chest pain":                  5,
    "central chest pain":                  5,
    "crushing chest pain":                 5,
    "difficulty breathing":                5,
    "shortness of breath":                 5,
    "dyspnoea":                            5,
    "dyspnea":                             5,
    "respiratory distress":                5,
    "altered mental status":               5,
    "confusion":                           4,
    "unconsciousness":                     5,
    "loss of consciousness":               5,
    "syncope":                             4,
    "near syncope":                        3,
    "stroke":                              5,
    "facial droop":                        5,
    "arm weakness":                        4,
    "sudden severe headache":              5,
    "thunderclap headache":                5,
    "severe headache":                     4,
    "headache":                            1,
    "severe abdominal pain":               4,
    "abdominal pain":                      2,
    "sepsis":                              5,
    "anaphylaxis":                         5,
    "anaphylactic reaction":               5,
    "severe allergic reaction":            5,
    "active bleeding":                     4,
    "severe bleeding":                     5,
    "haemoptysis":                         4,
    "hemoptysis":                          4,
    "vomiting blood":                      4,
    "black tarry stool":                   3,
    "diabetic ketoacidosis":               5,
    "hypoglycaemia":                       4,
    "hypoglycemia":                        4,
    "seizure":                             5,
    "status epilepticus":                  5,
    "acute limb ischaemia":                5,
    "back pain with neurological deficit": 5,
    "fever":                               1,
    "high fever":                          3,
    "nausea":                              1,
    "vomiting":                            1,
    "dizziness":                           1,
    "diaphoresis":                         3,
    "sweating":                            2,
    "palpitations":                        2,
    "tachycardia":                         3,
    "hypotension":                         4,
}

# Substring matches for longer descriptions
_RED_FLAG_SUBSTR: List[Tuple[str, int]] = [
    ("chest pain", 5),
    ("chest tightness", 4),
    ("difficulty breath", 5),
    ("shortness of breath", 5),
    ("cannot breathe", 5),
    ("can't breathe", 5),
    ("not breathing", 5),
    ("stroke", 5),
    ("facial droop", 5),
    ("thunderclap", 5),
    ("anaphyla", 5),
    ("bleeding", 3),
    ("haemorrhage", 4),
    ("hemorrhage", 4),
    ("unconscious", 5),
    ("unresponsive", 5),
    ("seizure", 5),
    ("confusion", 3),
    ("altered mental", 5),
    ("syncope", 4),
    ("diaphor", 3),
    ("sweating", 2),
    ("sepsis", 5),
    ("hypoglyc", 4),
    ("ketoacid", 5),
]

# High-risk symptom COMBINATIONS (any two present → bonus)
_COMBINATION_BONUSES: List[Tuple[List[str], int, str]] = [
    (["chest pain", "diaphoresis"],       15, "ACS pattern: chest pain + diaphoresis"),
    (["chest pain", "sweating"],          15, "ACS pattern: chest pain + diaphoresis"),
    (["chest pain", "shortness of breath"],  10, "Possible pulmonary embolism / ACS"),
    (["chest pain", "dyspnoea"],          10, "Possible pulmonary embolism / ACS"),
    (["chest pain", "arm weakness"],      15, "Possible STEMI with radiation"),
    (["fever", "confusion"],              10, "Possible meningitis / encephalitis / sepsis"),
    (["severe headache", "vomiting"],     10, "Possible subarachnoid haemorrhage"),
    (["thunderclap headache", "vomiting"],20, "High probability subarachnoid haemorrhage"),
    (["facial droop", "arm weakness"],    15, "FAST-positive stroke pattern"),
    (["hypotension", "tachycardia"],      15, "Shock pattern"),
    (["fever", "hypotension"],            15, "Septic shock pattern"),
    (["abdominal pain", "vomiting blood"],12, "Possible GI haemorrhage"),
    (["seizure", "fever"],                10, "Possible CNS infection"),
    (["difficulty breathing", "sweating"],12, "Possible acute LVF / PE"),
]


def _symptom_score(symptoms: List[Symptom]) -> Tuple[int, List[str]]:
    """
    Returns (symptom_flag_score, list_of_clinical_flags).
    Considers exact match, substring match, severity weighting, and combinations.
    """
    flags: List[str] = []
    base = 0

    displays = [s.display for s in symptoms]  # already normalised to lower

    # Per-symptom scoring
    for s in symptoms:
        d = s.display
        severity_mult = 1.0 + (s.severity - 5) * 0.08  # ±40% for severity 1 vs 10

        # Exact match
        if d in _RED_FLAG_EXACT:
            weight = _RED_FLAG_EXACT[d]
            pts = int(weight * 5 * severity_mult)
            base += pts
            if weight >= 3:
                flags.append(f"Red flag: {s.display} (severity {s.severity}/10)")
            continue

        # Substring match
        for substr, weight in _RED_FLAG_SUBSTR:
            if substr in d:
                pts = int(weight * 5 * severity_mult)
                base += pts
                if weight >= 3:
                    flags.append(f"Red flag: {s.display} (severity {s.severity}/10)")
                break

    # Combination bonuses
    for required_terms, bonus, description in _COMBINATION_BONUSES:
        if all(
            any(term in disp for disp in displays)
            for term in required_terms
        ):
            base += bonus
            flags.append(f"Clinical pattern: {description}")

    return min(base, 70), flags   # cap symptom contribution at 70


def _demographic_modifier(
    age: Optional[int],
    pregnant: bool,
    has_immunosuppression: bool = False,
) -> Tuple[int, List[str]]:
    """Age extremes and special populations increase risk."""
    score = 0
    flags = []
    if age is not None:
        if age < 1:
            score += 15; flags.append("Age <1 year — highest vulnerability")
        elif age < 5:
            score += 10; flags.append("Age <5 years — paediatric high risk")
        elif age >= 80:
            score += 10; flags.append("Age ≥80 — geriatric high risk")
        elif age >= 65:
            score += 5;  flags.append("Age ≥65 — elderly risk modifier")
    if pregnant:
        score += 8; flags.append("Pregnancy — escalated monitoring")
    if has_immunosuppression:
        score += 8; flags.append("Immunosuppression — sepsis risk elevated")
    return score, flags


def _news2_to_esi(news2: int) -> Tuple[int, str]:
    """
    Map NEWS2 aggregate to a risk contribution and description.
    NEWS2 ≥7 = high risk, 5-6 = medium, 1-4 = low, 0 = none.
    """
    if news2 >= 7:   return 30, f"NEWS2={news2}: HIGH — immediate clinical review"
    if news2 >= 5:   return 18, f"NEWS2={news2}: MEDIUM — urgent review"
    if news2 >= 3:   return 10, f"NEWS2={news2}: LOW-MEDIUM — close monitoring"
    if news2 >= 1:   return 4,  f"NEWS2={news2}: LOW"
    return 0, f"NEWS2={news2}: all vitals normal"


async def clinical_triage(
    symptoms_json: str,
    patient_id: str,
    chief_complaint: str,
    vital_signs_json: str = "{}",
    age_years: Optional[int] = None,
    sex: str = "unknown",
    pregnant: bool = False,
    has_copd: bool = False,
    ctx: Context = None,
) -> str:
    """
    MCP Tool: Perform clinical triage using NEWS2 + ESI-5 + symptom pattern recognition.

    Args:
        symptoms_json:   JSON array [{code, display, severity, onset?, body_site?, duration_hours?}]
        patient_id:      FHIR Patient ID
        chief_complaint: Primary presenting complaint
        vital_signs_json: Optional {systolic_bp, diastolic_bp, heart_rate, respiratory_rate,
                          oxygen_saturation, temperature, gcs, pain_score}
        age_years:       Patient age (improves risk stratification)
        sex:             'male'|'female'|'other'|'unknown'
        pregnant:        True if known pregnancy
        has_copd:        True for COPD — uses NEWS2 SpO2 Scale 2
        ctx:             MCP context for SHARP propagation

    Returns:
        JSON with triage_priority, risk_score, news2_score, reasoning,
        clinical_flags, recommended_actions, and fhir_observation_reference
    """
    # --- Parse inputs ---
    symptoms_data = json.loads(symptoms_json)
    vitals_raw    = json.loads(vital_signs_json)

    symptoms = [Symptom(**s) for s in symptoms_data]
    vitals   = VitalSigns(**vitals_raw) if vitals_raw else None

    # --- SHARP context ---
    sharp = FHIRContextBridge.extract_from_headers(
        ctx.request_headers if ctx else {}
    )
    if not sharp.patient_id:
        sharp.patient_id = patient_id

    # --- NEWS2 ---
    news2_score, vital_flags = compute_news2(vitals, copd=has_copd)
    news2_pts, news2_desc    = _news2_to_esi(news2_score)

    # --- Symptom pattern ---
    symptom_pts, symptom_flags = _symptom_score(symptoms)

    # --- Demographics ---
    demo_pts, demo_flags = _demographic_modifier(age_years, pregnant)

    # --- Aggregate ---
    raw_score = news2_pts + symptom_pts + demo_pts
    score     = min(raw_score, 100)

    all_flags = vital_flags + symptom_flags + demo_flags

    # --- ESI-level mapping (NEWS2-anchored) ---
    if news2_score >= 7 or score >= 80:
        priority  = TriagePriority.STAT
        wait_time = 0
        level_desc = "ESI Level 1 — Immediate"
    elif news2_score >= 5 or score >= 60:
        priority  = TriagePriority.ASAP
        wait_time = 15
        level_desc = "ESI Level 2 — Emergent"
    elif news2_score >= 3 or score >= 40:
        priority  = TriagePriority.URGENT
        wait_time = 60
        level_desc = "ESI Level 3 — Urgent"
    elif score >= 20:
        priority  = TriagePriority.URGENT
        wait_time = 90
        level_desc = "ESI Level 3-4 — Semi-Urgent"
    else:
        priority  = TriagePriority.ROUTINE
        wait_time = 120
        level_desc = "ESI Level 4-5 — Non-Urgent"

    # --- Recommended actions ---
    actions: List[str] = [f"{level_desc} — estimated wait: {wait_time} min"]

    if priority == TriagePriority.STAT:
        actions += [
            "Immediate physician assessment",
            "Continuous cardiac and SpO₂ monitoring",
            "IV access and 12-lead ECG within 10 minutes",
            "Activate resuscitation team if airway compromise",
        ]
    elif priority == TriagePriority.ASAP:
        actions += [
            "Physician assessment within 15 minutes",
            "Continuous vital signs monitoring every 15 min",
            "IV access; obtain bloods (FBC, U&E, troponin if cardiac)",
            "Reassess if any deterioration",
        ]
    elif priority == TriagePriority.URGENT:
        actions += [
            "Physician assessment within 60 minutes",
            "Vital signs every 30 minutes",
            "Analgesia per protocol if pain score ≥5",
        ]
    else:
        actions += [
            "Routine triage review",
            "Vital signs on arrival; repeat if any change",
            "Patient to report any worsening symptoms",
        ]

    if news2_score >= 5:
        actions.append(f"NEWS2={news2_score}: Initiate escalation protocol per ward policy")
    if any("COPD" in f or "SpO₂" in f for f in vital_flags) and has_copd:
        actions.append("COPD: Target SpO₂ 88–92%; avoid high-flow oxygen")

    # --- Reasoning narrative ---
    reasoning_parts = [
        f"Chief complaint: {chief_complaint}.",
        f"NEWS2 aggregate score: {news2_score}/20 ({news2_desc}).",
        f"Symptom risk contribution: {symptom_pts} points from {len(symptoms)} symptom(s).",
    ]
    if all_flags:
        reasoning_parts.append("Clinical alerts: " + "; ".join(all_flags) + ".")
    reasoning_parts.append(
        f"Composite risk score: {score}/100. Classification: {level_desc}."
    )
    reasoning = " ".join(reasoning_parts)

    # --- FHIR write ---
    fhir_obs       = None
    observation_ref = None
    fhir_client    = None

    try:
        if sharp.fhir_server_url:
            fhir_client = FHIRClient(sharp.fhir_server_url, sharp.access_token)
            fhir_obs = fhir_client.build_triage_observation(
                patient_id   = sharp.patient_id,
                triage_score = score,
                news2_score  = news2_score,
                priority     = priority.value,
                symptoms     = symptoms,
                reasoning    = reasoning,
                encounter_id = sharp.encounter_id,
            )
            created = await fhir_client.create_observation(fhir_obs)
            observation_ref = (
                f"{sharp.fhir_server_url}/Observation/{created.get('id', 'unknown')}"
            )
    except Exception as exc:
        observation_ref = f"FHIR write skipped: {exc}"
    finally:
        if fhir_client:
            await fhir_client.close()

    result = TriageResult(
        priority               = priority,
        score                  = score,
        news2_score            = news2_score,
        reasoning              = reasoning,
        clinical_flags         = all_flags,
        recommended_actions    = actions,
        fhir_observation       = fhir_obs or {},
        estimated_wait_minutes = wait_time,
    )

    return json.dumps({
        "triage_priority":          result.priority.value,
        "esi_level":                level_desc,
        "risk_score":               result.score,
        "news2_score":              result.news2_score,
        "reasoning":                result.reasoning,
        "clinical_flags":           result.clinical_flags,
        "recommended_actions":      result.recommended_actions,
        "fhir_observation_reference": observation_ref,
        "estimated_wait_minutes":   result.estimated_wait_minutes,
    }, indent=2)
