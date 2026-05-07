"""
Evidence-Based Clinical Guideline Knowledge Base
=================================================
Covers 12 high-prevalence conditions with multi-branch recommendations:

  E11    Type 2 Diabetes Mellitus          (ADA 2026)
  I10    Essential Hypertension            (ESC/ESH 2024, ACC/AHA 2023)
  I50    Heart Failure (HFrEF)             (ESC 2023)
  I48    Atrial Fibrillation               (ESC 2024)
  J44    COPD                              (GOLD 2025)
  J45    Asthma                            (GINA 2024)
  N18    Chronic Kidney Disease            (KDIGO 2024)
  F32    Depressive Episode / Depression   (NICE 2022 / APA 2024)
  E03    Hypothyroidism                    (ATA 2024)
  M10    Gout                              (ACR 2020)
  K21    GORD / GERD                       (ACG 2022)
  E78    Hyperlipidaemia                   (ESC/EAS 2024)

Branch selection logic:
  - Comorbidities steer to the appropriate pathway (e.g. DM2 + ASCVD → SGLT2i/GLP-1)
  - Current medications avoid duplicate class recommendations
  - CKD comorbidity flags renal-safe alternatives

FHIR CarePlan includes:
  - Condition-specific LOINC monitoring targets
  - Activity codes in SNOMED CT
  - SHARP extension provenance
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from models.clinical_models import (
    CareRecommendation, EvidenceLevel, GuidelineRequest, RecommendationStrength,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return s.strip().lower()


def _has_comorbidity(comorbidities: List[str], *codes: str) -> bool:
    normed = [_norm(c) for c in comorbidities]
    return any(_norm(code) in normed for code in codes)


def _on_drug_class(current_meds: List[str], *class_keywords: str) -> bool:
    normed = [_norm(m) for m in current_meds]
    return any(
        any(kw in med for med in normed)
        for kw in class_keywords
    )


# ---------------------------------------------------------------------------
# Guideline data structure
# ---------------------------------------------------------------------------

GuidelineEntry = Dict[str, Any]
# Each entry:
#   source: str
#   branches: list of {
#       id: str
#       trigger_comorbidities: list (any match → use this branch)
#       trigger_exclude_meds: list (if patient already on these, skip)
#       text: str
#       strength: RecommendationStrength
#       evidence: EvidenceLevel
#       medications: list[str]
#       contraindications: list[str]
#       monitoring: list[str]
#       lifestyle: list[str]
#       referral: str | None
#       follow_up_weeks: int
#       loinc_target: {code, display, target}
#       snomed_activity: {code, display}
#   }


_GUIDELINES: Dict[str, GuidelineEntry] = {

    # ── Type 2 Diabetes (E11) ────────────────────────────────────────────
    "E11": {
        "source": "ADA Standards of Care 2026 / EASD 2024",
        "branches": [
            {
                "id":                     "dm2_ascvd",
                "trigger_comorbidities":  ["I25", "I21", "I63", "Z82.49", "ascvd", "cardiovascular disease", "ischaemic heart disease", "atherosclerosis"],
                "trigger_exclude_meds":   ["sglt2", "empagliflozin", "dapagliflozin", "canagliflozin", "glp-1", "liraglutide", "semaglutide", "dulaglutide"],
                "text":                   "For T2DM with established ASCVD: add SGLT2 inhibitor (empagliflozin or dapagliflozin) or GLP-1 receptor agonist (liraglutide, semaglutide) to reduce CV mortality and HF hospitalisation — independent of HbA1c.",
                "strength":               RecommendationStrength.STRONG,
                "evidence":               EvidenceLevel.A,
                "medications":            ["empagliflozin", "dapagliflozin", "liraglutide", "semaglutide"],
                "contraindications":      ["history of diabetic ketoacidosis (SGLT2i)", "eGFR <45 (SGLT2i)", "medullary thyroid carcinoma (GLP-1 RA)", "multiple endocrine neoplasia type 2 (GLP-1 RA)"],
                "monitoring":             ["HbA1c every 3 months until target, then 6-monthly", "eGFR and electrolytes 3-monthly", "Blood pressure at every visit", "Weight and BMI 3-monthly", "Foot exam annually", "Urine ACR annually"],
                "lifestyle":              ["Mediterranean diet or low-carbohydrate diet", "≥150 min/week moderate aerobic activity", "Smoking cessation", "Weight loss target 5–15% body weight"],
                "referral":               "Endocrinology if HbA1c >86 mmol/mol (10%) despite dual therapy or complex insulin regimen",
                "follow_up_weeks":        12,
                "loinc_target":           {"code": "4548-4", "display": "HbA1c", "target": "<53 mmol/mol (7%)"},
                "snomed_activity":        {"code": "182922004", "display": "Dietary regime management"},
            },
            {
                "id":                     "dm2_heart_failure",
                "trigger_comorbidities":  ["I50", "heart failure", "hfref", "hfpef"],
                "trigger_exclude_meds":   ["sglt2", "empagliflozin", "dapagliflozin"],
                "text":                   "T2DM with heart failure: prioritise SGLT2 inhibitor (dapagliflozin or empagliflozin) — proven to reduce HF hospitalisation and CV death. Avoid thiazolidinediones and saxagliptin (worsen HF).",
                "strength":               RecommendationStrength.STRONG,
                "evidence":               EvidenceLevel.A,
                "medications":            ["dapagliflozin", "empagliflozin"],
                "contraindications":      ["eGFR <25", "type 1 diabetes", "recurrent UTI"],
                "monitoring":             ["HbA1c every 3 months", "eGFR monthly for first 3 months", "BP and volume status at each visit", "BNP/NT-proBNP 6-monthly"],
                "lifestyle":              ["Sodium restriction <2 g/day", "Fluid restriction if oedematous", "Daily weight monitoring", "Cardiac rehabilitation"],
                "referral":               "Cardiology / heart failure clinic",
                "follow_up_weeks":        4,
                "loinc_target":           {"code": "4548-4", "display": "HbA1c", "target": "<58 mmol/mol (7.5%) in HF"},
                "snomed_activity":        {"code": "229070002", "display": "Diabetic monitoring"},
            },
            {
                "id":                     "dm2_ckd",
                "trigger_comorbidities":  ["N18", "ckd", "chronic kidney disease"],
                "trigger_exclude_meds":   ["sglt2", "empagliflozin", "dapagliflozin"],
                "text":                   "T2DM with CKD: use SGLT2i (dapagliflozin) if eGFR ≥25 for renoprotection. Add finerenone if ACR >300 and already on maximum ACEi/ARB. Avoid metformin if eGFR <30.",
                "strength":               RecommendationStrength.STRONG,
                "evidence":               EvidenceLevel.A,
                "medications":            ["dapagliflozin", "finerenone"],
                "contraindications":      ["eGFR <25 for SGLT2i", "hyperkalaemia >5.5 for finerenone"],
                "monitoring":             ["eGFR and ACR quarterly", "Potassium monthly (if finerenone)", "HbA1c every 3 months", "Blood pressure <130/80 target"],
                "lifestyle":              ["Low-protein diet (0.8 g/kg) if CKD stage ≥3b", "Sodium restriction", "Smoking cessation"],
                "referral":               "Nephrology if eGFR <30 or ACR >300",
                "follow_up_weeks":        4,
                "loinc_target":           {"code": "33914-3", "display": "eGFR", "target": ">45 mL/min (or slow progression)"},
                "snomed_activity":        {"code": "229070002", "display": "Renal and diabetes monitoring"},
            },
            {
                "id":                     "dm2_standard",
                "trigger_comorbidities":  [],  # default
                "trigger_exclude_meds":   ["metformin"],
                "text":                   "T2DM first-line: metformin is the cornerstone unless contraindicated (eGFR <30). Individualise glycaemic target. Add second agent (SGLT2i, GLP-1 RA, DPP-4i, or sulfonylurea) if HbA1c above target at 3 months.",
                "strength":               RecommendationStrength.STRONG,
                "evidence":               EvidenceLevel.A,
                "medications":            ["metformin", "empagliflozin", "semaglutide", "sitagliptin", "gliclazide"],
                "contraindications":      ["eGFR <30 (metformin)", "severe hepatic impairment (metformin)"],
                "monitoring":             ["HbA1c every 3 months until at target", "eGFR annually", "B12 every 2-3 years (long-term metformin)", "Lipid panel annually", "ACR annually"],
                "lifestyle":              ["Mediterranean or DASH diet", "150 min/week moderate exercise", "Weight management programme if BMI >27", "Self-monitoring blood glucose"],
                "referral":               "Diabetes specialist nurse, dietitian referral at diagnosis",
                "follow_up_weeks":        12,
                "loinc_target":           {"code": "4548-4", "display": "HbA1c", "target": "<53 mmol/mol (7%) most patients"},
                "snomed_activity":        {"code": "182922004", "display": "Dietary management"},
            },
        ],
    },

    # ── Essential Hypertension (I10) ──────────────────────────────────────
    "I10": {
        "source": "ESC/ESH 2024 Hypertension Guidelines / ACC/AHA 2023",
        "branches": [
            {
                "id":                    "htn_dm_ckd",
                "trigger_comorbidities": ["E11", "E10", "N18", "diabetes", "ckd"],
                "trigger_exclude_meds":  ["ace inhibitor", "acei", "lisinopril", "ramipril", "arb", "losartan"],
                "text":                  "Hypertension with diabetes or CKD: ACE inhibitor or ARB is first-line (renoprotective). Target BP <130/80 mmHg. Add calcium channel blocker or thiazide-like diuretic as second agent.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["ramipril", "lisinopril", "candesartan", "amlodipine", "indapamide"],
                "contraindications":     ["ACEi in pregnancy", "bilateral renal artery stenosis", "eGFR <30 + hyperkalaemia"],
                "monitoring":            ["U&E and creatinine at 2 weeks after starting ACEi/ARB", "eGFR 3-monthly", "BP at every visit (target <130/80)", "Urine ACR annually"],
                "lifestyle":             ["DASH diet (high potassium, low sodium)", "Sodium <5 g/day", "30 min aerobic activity 5×/week", "BMI target 20–25"],
                "referral":              "Nephrology if eGFR <30 or resistant hypertension",
                "follow_up_weeks":       4,
                "loinc_target":          {"code": "55284-4", "display": "Blood pressure", "target": "<130/80 mmHg"},
                "snomed_activity":       {"code": "413473000", "display": "Cardiovascular disease risk assessment"},
            },
            {
                "id":                    "htn_heart_failure",
                "trigger_comorbidities": ["I50", "heart failure"],
                "trigger_exclude_meds":  ["beta blocker", "bisoprolol", "carvedilol", "ace", "arb"],
                "text":                  "Hypertension with HFrEF: use ACEi/ARB + beta-blocker + MRA (spironolactone/eplerenone). Avoid CCBs (except amlodipine). Target BP <130/80 mmHg.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["ramipril", "bisoprolol", "spironolactone", "sacubitril/valsartan"],
                "contraindications":     ["Non-dihydropyridine CCBs (diltiazem/verapamil) in HFrEF", "eGFR <30 for MRA", "K+ >5.5 for MRA"],
                "monitoring":            ["U&E and K+ weekly for first month after MRA", "BNP every 3 months", "ECHO annually", "BP and HR at every visit"],
                "lifestyle":             ["Sodium <2 g/day", "Fluid restriction if oedematous", "Daily weight monitoring", "Cardiac rehab programme"],
                "referral":              "Heart failure specialist within 2 weeks if newly diagnosed HFrEF",
                "follow_up_weeks":       4,
                "loinc_target":          {"code": "55284-4", "display": "Blood pressure", "target": "<130/80 mmHg"},
                "snomed_activity":       {"code": "413473000", "display": "Hypertension and HF co-management"},
            },
            {
                "id":                    "htn_standard",
                "trigger_comorbidities": [],
                "trigger_exclude_meds":  [],
                "text":                  "Stage 1–2 hypertension: initiate antihypertensive therapy. Preferred first-line agents: ACEi/ARB + CCB (amlodipine). Add thiazide-like diuretic as third agent. Target BP <140/90 mmHg (general); <130/80 if high CV risk.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["ramipril", "amlodipine", "indapamide", "bisoprolol (if angina/AF)"],
                "contraindications":     ["ACEi in pregnancy", "thiazides in gout", "beta-blockers in asthma/COPD"],
                "monitoring":            ["BP at 2 and 4 weeks after each medication change", "U&E at 1 month", "Fasting lipid profile and HbA1c at baseline", "ASCVD risk calculation"],
                "lifestyle":             ["DASH diet", "Sodium <5 g/day", "Limit alcohol ≤14 units/week", "150 min/week aerobic exercise", "Weight reduction"],
                "referral":              "Cardiology if BP >180/110 resistant to 3 agents",
                "follow_up_weeks":       4,
                "loinc_target":          {"code": "55284-4", "display": "Blood pressure", "target": "<140/90 mmHg"},
                "snomed_activity":       {"code": "413473000", "display": "Cardiovascular risk factor management"},
            },
        ],
    },

    # ── Heart Failure HFrEF (I50) ─────────────────────────────────────────
    "I50": {
        "source": "ESC Heart Failure Guidelines 2023",
        "branches": [
            {
                "id":                    "hf_standard",
                "trigger_comorbidities": [],
                "trigger_exclude_meds":  [],
                "text":                  "HFrEF (EF <40%): initiate the four pillars of disease-modifying therapy — ACEi/ARB/ARNI, evidence-based beta-blocker, MRA, and SGLT2 inhibitor. Achieve maximum tolerated doses. Loop diuretic for congestion symptom control (not prognostic).",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["sacubitril/valsartan", "ramipril", "bisoprolol", "carvedilol", "spironolactone", "eplerenone", "dapagliflozin", "empagliflozin", "furosemide"],
                "contraindications":     ["Non-DHP CCBs (verapamil, diltiazem)", "glitazones", "NSAIDs", "saxagliptin"],
                "monitoring":            ["BNP/NT-proBNP 3-monthly", "Echocardiogram 3-6 months post initiation", "U&E and K+ weekly for 4 weeks after each dose change", "HR target 60-70 bpm", "BP target 100-130 mmHg systolic"],
                "lifestyle":             ["Fluid restriction 1.5–2 L/day if hyponatraemic", "Sodium restriction", "Daily weight — report gain >2 kg/48h", "Cardiac rehabilitation", "Influenza and pneumococcal vaccination"],
                "referral":              "Heart failure specialist and ICD/CRT assessment if EF <35% on optimal therapy for ≥3 months",
                "follow_up_weeks":       2,
                "loinc_target":          {"code": "42198-3", "display": "BNP", "target": "<125 pg/mL"},
                "snomed_activity":       {"code": "229070002", "display": "Heart failure monitoring"},
            },
        ],
    },

    # ── Atrial Fibrillation (I48) ─────────────────────────────────────────
    "I48": {
        "source": "ESC Atrial Fibrillation Guidelines 2024",
        "branches": [
            {
                "id":                    "af_anticoagulation",
                "trigger_comorbidities": [],
                "trigger_exclude_meds":  ["warfarin", "apixaban", "rivaroxaban", "dabigatran", "edoxaban"],
                "text":                  "AF with CHA₂DS₂-VASc ≥2 (men) or ≥3 (women): initiate oral anticoagulation. Prefer DOAC over warfarin (apixaban, rivaroxaban, dabigatran, edoxaban). Assess stroke risk with CHA₂DS₂-VASc and bleeding risk with HAS-BLED at each visit.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["apixaban", "rivaroxaban", "dabigatran", "edoxaban"],
                "contraindications":     ["mechanical heart valve (DOAC contraindicated — use warfarin)", "moderate-severe mitral stenosis (warfarin)", "eGFR <15 (most DOACs)"],
                "monitoring":            ["CHA₂DS₂-VASc annually", "HAS-BLED bleeding risk annually", "eGFR annually (DOAC dose adjustment)", "ECG — HR target 60-100 bpm", "ECHO to assess mitral valve"],
                "lifestyle":             ["Alcohol reduction (major AF trigger)", "Weight loss if obese (BMI >30)", "Hypertension management", "Sleep apnoea screening and treatment"],
                "referral":              "Electrophysiology if paroxysmal AF for rhythm-control or ablation consideration",
                "follow_up_weeks":       4,
                "loinc_target":          {"code": "8867-4", "display": "Heart rate", "target": "60-100 bpm at rest"},
                "snomed_activity":       {"code": "229799001", "display": "Anticoagulation management"},
            },
        ],
    },

    # ── COPD (J44) ────────────────────────────────────────────────────────
    "J44": {
        "source": "GOLD COPD Report 2025",
        "branches": [
            {
                "id":                    "copd_exacerbation_risk",
                "trigger_comorbidities": ["frequent exacerbations", "previous hospitalisation"],
                "trigger_exclude_meds":  ["lama", "tiotropium", "umeclidinium", "ics", "budesonide", "fluticasone"],
                "text":                  "COPD with high exacerbation risk (≥2/year or ≥1 hospitalisation): triple inhaler therapy (LAMA + LABA + ICS) if blood eosinophils ≥300. LAMA + LABA if eosinophils <100. Add roflumilast if FEV1 <50% + chronic bronchitis + frequent exacerbations.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["umeclidinium/vilanterol/fluticasone furoate", "glycopyrronium/indacaterol/mometasone", "roflumilast (if FEV1<50%+chronic bronchitis)"],
                "contraindications":     ["ICS monotherapy", "ICS if eosinophils <100 (increased pneumonia risk)", "roflumilast in severe depression"],
                "monitoring":            ["Spirometry (FEV1/FVC) annually", "Blood eosinophils before ICS initiation", "Exacerbation frequency 3-monthly", "O2 saturation; assess for LTOT if SaO2 ≤92%", "Inhaler technique at every visit"],
                "lifestyle":             ["Smoking cessation (single most effective intervention)", "Pulmonary rehabilitation (≥8 sessions)", "Annual influenza and pneumococcal vaccination", "LTOT if PaO2 ≤7.3 kPa at rest"],
                "referral":              "Respiratory specialist if diagnostic uncertainty, FEV1 <50%, or frequent hospitalisations",
                "follow_up_weeks":       8,
                "loinc_target":          {"code": "19926-5", "display": "FEV1/FVC ratio", "target": ">0.70 post-BD (diagnostic; therapeutic target: symptom control)"},
                "snomed_activity":       {"code": "229799001", "display": "Inhaler therapy management"},
            },
            {
                "id":                    "copd_standard",
                "trigger_comorbidities": [],
                "trigger_exclude_meds":  [],
                "text":                  "COPD (GOLD A/B): long-acting bronchodilator — LAMA preferred over LABA as monotherapy. Add LABA if persistent dyspnoea on LAMA. Avoid ICS unless eosinophils ≥300.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["tiotropium", "umeclidinium", "glycopyrronium", "salmeterol (if LAMA inadequate)"],
                "contraindications":     ["Short-acting bronchodilators as sole therapy (only PRN)", "ICS monotherapy"],
                "monitoring":            ["mMRC dyspnoea and CAT score 3-monthly", "Spirometry annually", "Exacerbation history at every visit"],
                "lifestyle":             ["Smoking cessation", "Pulmonary rehabilitation if CAT ≥10 or mMRC ≥2", "Annual influenza vaccination"],
                "referral":              None,
                "follow_up_weeks":       12,
                "loinc_target":          {"code": "19926-5", "display": "FEV1/FVC post-bronchodilator", "target": "Symptom control; FEV1 decline <40 mL/year"},
                "snomed_activity":       {"code": "229799001", "display": "Bronchodilator therapy management"},
            },
        ],
    },

    # ── Asthma (J45) ─────────────────────────────────────────────────────
    "J45": {
        "source": "GINA 2024 Asthma Management Report",
        "branches": [
            {
                "id":                    "asthma_standard",
                "trigger_comorbidities": [],
                "trigger_exclude_meds":  [],
                "text":                  "Asthma (all severities): preferred reliever is low-dose ICS-formoterol (not SABA-only). Step-up ICS dose if uncontrolled. Add LAMA (tiotropium) at Step 4. Biologic (dupilumab, mepolizumab, benralizumab) for severe eosinophilic asthma at Step 5.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["budesonide/formoterol", "fluticasone/salmeterol", "montelukast (adjunct)", "tiotropium (Step 4)", "dupilumab (Step 5)"],
                "contraindications":     ["SABA-only therapy (increases risk of severe attacks)", "Oral corticosteroids long-term without biologic consideration"],
                "monitoring":            ["ACQ-6 / ACT symptom score at each visit", "Peak flow or spirometry 3-monthly", "Exacerbation frequency 6-monthly", "Inhaler technique at every visit", "Sputum eosinophils/FeNO if step-up considered"],
                "lifestyle":             ["Allergen avoidance (identified triggers)", "Smoking cessation", "Weight loss if obese", "Annual influenza vaccination"],
                "referral":              "Respiratory / allergy specialist if Step 3 therapy inadequate",
                "follow_up_weeks":       8,
                "loinc_target":          {"code": "19926-5", "display": "FEV1/FVC", "target": "ACT ≥20; ACQ ≤0.75"},
                "snomed_activity":       {"code": "229799001", "display": "Inhaler therapy management"},
            },
        ],
    },

    # ── Chronic Kidney Disease (N18) ──────────────────────────────────────
    "N18": {
        "source": "KDIGO CKD Guidelines 2024",
        "branches": [
            {
                "id":                    "ckd_standard",
                "trigger_comorbidities": [],
                "trigger_exclude_meds":  [],
                "text":                  "CKD: maximise ACEi/ARB for proteinuria reduction. Add SGLT2 inhibitor (dapagliflozin) if eGFR ≥25 and ACR ≥200. Target BP <130/80. Treat anaemia (Hb <100 g/L) with erythropoiesis-stimulating agents once iron-replete. Bicarbonate replacement if serum bicarbonate <22 mmol/L.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["ramipril", "candesartan", "dapagliflozin", "amlodipine", "sodium bicarbonate"],
                "contraindications":     ["ACEi + ARB combination", "NSAIDs", "direct nephrotoxins", "SGLT2i if eGFR <25"],
                "monitoring":            ["eGFR quarterly", "Urine ACR quarterly", "Potassium quarterly", "Phosphate 6-monthly", "Haemoglobin 3-monthly", "Parathyroid hormone 6-monthly"],
                "lifestyle":             ["Low-protein diet 0.8 g/kg (not <0.6 g/kg)", "Low-phosphate diet", "Sodium restriction <5 g/day", "Smoking cessation", "Avoid nephrotoxins (NSAIDs, iodinated contrast without precaution)"],
                "referral":              "Nephrology if eGFR <30, ACR >300, or rapid progression (>5 mL/min/year)",
                "follow_up_weeks":       12,
                "loinc_target":          {"code": "33914-3", "display": "eGFR", "target": ">45 mL/min or slow annual decline"},
                "snomed_activity":       {"code": "229070002", "display": "Renal function monitoring"},
            },
        ],
    },

    # ── Depression (F32) ─────────────────────────────────────────────────
    "F32": {
        "source": "NICE Depression Guidelines 2022 (updated) / APA Practice Guidelines 2024",
        "branches": [
            {
                "id":                    "depression_standard",
                "trigger_comorbidities": [],
                "trigger_exclude_meds":  [],
                "text":                  "Moderate-severe depression: offer antidepressant + structured psychological therapy (CBT or behavioural activation) concurrently. SSRIs are first-line (sertraline preferred: best efficacy/tolerability balance in network meta-analysis). Switch class after 4 weeks if no response. Augmentation (lithium, quetiapine, aripiprazole) if 2 adequate trials fail.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["sertraline", "escitalopram", "mirtazapine", "venlafaxine", "duloxetine"],
                "contraindications":     ["MAOIs within 2 weeks of SSRI initiation", "citalopram if QTc >450 ms", "SSRIs in bipolar disorder without mood stabiliser"],
                "monitoring":            ["PHQ-9 at 2, 4, 8 weeks after initiation", "Side-effect review at 2 weeks", "Suicidality assessment weekly for first 4 weeks (especially age <25)", "HbA1c and lipids baseline (antidepressant metabolic effects)", "Maintain antidepressant for ≥6 months after remission"],
                "lifestyle":             ["Regular aerobic exercise (30 min 3×/week — NNT ~7 for response)", "Sleep hygiene programme", "Limit alcohol", "Social engagement / support network", "Mindfulness-based CBT for recurrent depression"],
                "referral":              "Psychiatry if psychotic features, bipolar disorder, 2+ treatment failures, or active suicidality",
                "follow_up_weeks":       4,
                "loinc_target":          {"code": "44261-6", "display": "PHQ-9 score", "target": "<5 (remission)"},
                "snomed_activity":       {"code": "229799001", "display": "Antidepressant medication management"},
            },
        ],
    },

    # ── Hypothyroidism (E03) ──────────────────────────────────────────────
    "E03": {
        "source": "ATA Guidelines for Hypothyroidism 2024",
        "branches": [
            {
                "id":                    "hypothyroid_standard",
                "trigger_comorbidities": [],
                "trigger_exclude_meds":  [],
                "text":                  "Hypothyroidism: levothyroxine monotherapy is first-line. Starting dose 1.6 mcg/kg/day (lean body weight); start at 25-50 mcg in elderly or cardiac disease. Target TSH 0.5–2.5 mIU/L (younger adults); 1–4 mIU/L (elderly). Take on empty stomach 30-60 min before breakfast.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["levothyroxine"],
                "contraindications":     ["Starting full replacement dose in ischaemic heart disease (titrate slowly)", "Interaction: calcium, iron, antacids reduce absorption (separate by 4 h)"],
                "monitoring":            ["TSH at 6-8 weeks after initiation or dose change", "TSH annually once stable", "FT4 if TSH interpretation uncertain", "Bone density if overreplaced (suppressed TSH)"],
                "lifestyle":             ["Consistent timing of levothyroxine", "Avoid dietary soy within 4 h of dose", "Iodine-adequate diet", "Report chest pain or palpitations promptly"],
                "referral":              "Endocrinology if symptomatic on adequate levothyroxine, pregnancy, or suspected secondary hypothyroidism",
                "follow_up_weeks":       8,
                "loinc_target":          {"code": "11579-0", "display": "TSH", "target": "0.5–2.5 mIU/L (adult); 1–4 mIU/L (elderly)"},
                "snomed_activity":       {"code": "229799001", "display": "Thyroid hormone replacement management"},
            },
        ],
    },

    # ── Gout (M10) ───────────────────────────────────────────────────────
    "M10": {
        "source": "ACR Gout Treatment Guidelines 2020 (updated 2023)",
        "branches": [
            {
                "id":                    "gout_urate_lowering",
                "trigger_comorbidities": [],
                "trigger_exclude_meds":  [],
                "text":                  "Gout: initiate urate-lowering therapy (ULT) with allopurinol (preferred) or febuxostat. Co-prescribe low-dose colchicine or NSAID prophylaxis for first 3-6 months. Target serum urate <360 μmol/L (<6 mg/dL); <300 μmol/L if tophaceous disease. Dietary modification adjunctive.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["allopurinol", "febuxostat", "colchicine (prophylaxis)", "naproxen (acute flare)"],
                "contraindications":     ["Allopurinol: dose reduce in CKD (eGFR <30 → max 100 mg); HLA-B*5801 testing in Han Chinese/Thai before starting", "Febuxostat: cardiovascular events in existing CVD — use with caution", "NSAIDs in CKD/heart failure/anticoagulation"],
                "monitoring":            ["Serum urate every 2-4 weeks during dose titration", "Target urate <360 μmol/L", "LFT at baseline and 3 months (febuxostat)", "eGFR annually", "Flare frequency 6-monthly"],
                "lifestyle":             ["Reduce red meat and seafood", "Avoid fructose-rich beverages", "Cherry consumption (modest urate reduction)", "Hydration >2 L/day", "Alcohol cessation or reduction", "Weight loss"],
                "referral":              "Rheumatology if tophaceous gout, renal failure, or drug intolerance",
                "follow_up_weeks":       6,
                "loinc_target":          {"code": "3084-1", "display": "Serum uric acid", "target": "<360 μmol/L (6 mg/dL)"},
                "snomed_activity":       {"code": "229799001", "display": "Urate-lowering therapy management"},
            },
        ],
    },

    # ── GORD / GERD (K21) ─────────────────────────────────────────────────
    "K21": {
        "source": "ACG GERD Clinical Guidelines 2022",
        "branches": [
            {
                "id":                    "gerd_standard",
                "trigger_comorbidities": [],
                "trigger_exclude_meds":  [],
                "text":                  "GORD: PPI once daily 30 min before breakfast for 4-8 weeks (initial). Step down to H2RA or PPI on-demand after healing. Avoid long-term PPI without indication review. Test-and-treat for H. pylori in uninvestigated dyspepsia. Upper GI endoscopy if alarm features (dysphagia, weight loss, anaemia).",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["omeprazole", "lansoprazole", "pantoprazole", "esomeprazole"],
                "contraindications":     ["Long-term PPI without annual indication review", "PPI + clopidogrel (use pantoprazole — least CYP2C19 interaction)", "High-dose PPI with no symptom benefit"],
                "monitoring":            ["Annual PPI indication review", "Magnesium if on PPI >1 year", "Bone density if on PPI >5 years + additional osteoporosis risk", "H. pylori test-of-cure 4-6 weeks after eradication"],
                "lifestyle":             ["Head-of-bed elevation 10-15 cm", "No meals within 3 h of bedtime", "Avoid trigger foods (coffee, alcohol, chocolate, fatty foods)", "Weight loss if overweight", "Smoking cessation"],
                "referral":              "Gastroenterology for endoscopy if alarm features, Barrett's surveillance, or refractory symptoms",
                "follow_up_weeks":       8,
                "loinc_target":          {"code": "44261-6", "display": "Symptom score", "target": "GERD-HRQL ≤6 (remission)"},
                "snomed_activity":       {"code": "229799001", "display": "PPI therapy management"},
            },
        ],
    },

    # ── Hyperlipidaemia (E78) ──────────────────────────────────────────────
    "E78": {
        "source": "ESC/EAS Dyslipidaemia Guidelines 2024",
        "branches": [
            {
                "id":                    "lipid_very_high_risk",
                "trigger_comorbidities": ["I25", "I21", "I63", "ascvd", "diabetes with organ damage", "ckd g3b–g5"],
                "trigger_exclude_meds":  ["statin", "atorvastatin", "rosuvastatin"],
                "text":                  "Very high CV risk: initiate high-intensity statin (atorvastatin 40-80 mg or rosuvastatin 20-40 mg). Add ezetimibe if LDL-C not at target after 4-6 weeks. Add PCSK9 inhibitor if LDL-C ≥1.4 mmol/L on max-tolerated statin + ezetimibe.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["atorvastatin", "rosuvastatin", "ezetimibe", "evolocumab (PCSK9i)"],
                "contraindications":     ["Statins in pregnancy/breastfeeding", "Active liver disease", "CYP3A4 interactions with simvastatin"],
                "monitoring":            ["Fasting lipid panel at 4-6 weeks after initiation", "LFT at baseline and 3 months", "CK if myalgia reported", "LDL-C target <1.4 mmol/L (very high risk), <1.8 mmol/L (high risk)"],
                "lifestyle":             ["Reduce saturated fat to <7% total energy", "Dietary fibre ≥30 g/day", "Plant sterols/stanols 2 g/day (LDL reduction ~10%)", "150 min/week moderate aerobic exercise", "Weight management"],
                "referral":              "Lipid clinic if statin intolerance or familial hypercholesterolaemia suspected",
                "follow_up_weeks":       6,
                "loinc_target":          {"code": "13457-7", "display": "LDL-C", "target": "<1.4 mmol/L (very high risk)"},
                "snomed_activity":       {"code": "229799001", "display": "Lipid-lowering therapy management"},
            },
            {
                "id":                    "lipid_standard",
                "trigger_comorbidities": [],
                "trigger_exclude_meds":  [],
                "text":                  "High CV risk (10-year risk ≥10%): moderate-intensity statin (atorvastatin 10-20 mg, rosuvastatin 5-10 mg). Target LDL-C <1.8 mmol/L or ≥50% reduction. Add ezetimibe if needed.",
                "strength":              RecommendationStrength.STRONG,
                "evidence":              EvidenceLevel.A,
                "medications":           ["atorvastatin", "rosuvastatin", "ezetimibe"],
                "contraindications":     ["Statins in pregnancy", "Simvastatin >20 mg with amiodarone"],
                "monitoring":            ["Lipid panel at 6 weeks, then annually when stable", "LFT baseline", "CK if myalgia"],
                "lifestyle":             ["Dietary modification as above", "Exercise programme", "Smoking cessation"],
                "referral":              None,
                "follow_up_weeks":       6,
                "loinc_target":          {"code": "13457-7", "display": "LDL-C", "target": "<1.8 mmol/L (high risk)"},
                "snomed_activity":       {"code": "229799001", "display": "Lipid-lowering therapy management"},
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Database query engine
# ---------------------------------------------------------------------------

class GuidelineDatabase:
    """
    Retrieve evidence-based recommendations with intelligent branch selection.

    Branch selection priority:
      1. Condition-specific comorbidity triggers (most specific match)
      2. Current medication exclusions (skip if patient already on that drug)
      3. Default branch (first non-triggered branch that doesn't require specific comorbidity)
    """

    def get_recommendation(self, request: GuidelineRequest) -> Optional[CareRecommendation]:
        # Normalise condition code — strip sub-codes (E11.9 → E11)
        base_code = request.condition_code.split(".")[0].upper()

        entry = _GUIDELINES.get(base_code)
        if not entry:
            return None

        branch = self._select_branch(request, entry["branches"])
        care_plan = self._build_care_plan(request, entry["source"], branch)

        return CareRecommendation(
            guideline_source        = entry["source"],
            recommendation_text     = branch["text"],
            strength                = branch["strength"],
            evidence_grade          = branch["evidence"],
            applicable_medications  = branch["medications"],
            contraindications       = branch["contraindications"],
            monitoring_requirements = branch["monitoring"],
            lifestyle_modifications = branch.get("lifestyle", []),
            specialist_referral     = branch.get("referral"),
            follow_up_weeks         = branch.get("follow_up_weeks"),
            fhir_care_plan          = care_plan,
        )

    def _select_branch(
        self,
        request: GuidelineRequest,
        branches: List[Dict],
    ) -> Dict:
        """Select the most clinically appropriate branch."""
        comorbidities   = request.comorbidities or []
        current_meds    = request.current_medications or []

        # Pass 1: comorbidity-triggered branches (most specific)
        for branch in branches:
            triggers = branch.get("trigger_comorbidities", [])
            if not triggers:
                continue  # default branch — consider later
            if _has_comorbidity(comorbidities, *triggers):
                # Check the patient is not already on the recommended drugs
                exclude = branch.get("trigger_exclude_meds", [])
                if exclude and _on_drug_class(current_meds, *exclude):
                    continue  # already on this line — skip to next branch
                return branch

        # Pass 2: default branch (empty trigger_comorbidities)
        for branch in branches:
            if not branch.get("trigger_comorbidities"):
                exclude = branch.get("trigger_exclude_meds", [])
                if exclude and _on_drug_class(current_meds, *exclude):
                    continue
                return branch

        # Fallback: return first branch regardless
        return branches[0]

    def _build_care_plan(
        self,
        request: GuidelineRequest,
        source: str,
        branch: Dict,
    ) -> Dict[str, Any]:
        """Construct a FHIR R5 CarePlan resource."""
        patient_ref    = f"Patient/{request.patient_context.patient_id}"
        loinc          = branch.get("loinc_target", {})
        snomed         = branch.get("snomed_activity", {})
        follow_up_wks  = branch.get("follow_up_weeks", 12)

        activities = [
            {
                "plannedActivityDetail": {
                    "code": {
                        "coding": [{
                            "system":  "http://snomed.info/sct",
                            "code":    snomed.get("code", "229070002"),
                            "display": snomed.get("display", "Clinical management"),
                        }],
                    },
                    "status":      "not-started",
                    "description": (
                        f"Initiate: {', '.join(branch['medications'][:3])}"
                        if branch.get("medications")
                        else "Lifestyle modification programme"
                    ),
                    "scheduledTiming": {
                        "repeat": {
                            "boundsPeriod": {
                                "start": _now_iso(),
                            },
                            "frequency": 1,
                            "period":    follow_up_wks,
                            "periodUnit": "wk",
                        }
                    },
                }
            }
        ]

        # Add monitoring activities
        for monitoring_item in branch.get("monitoring", [])[:3]:
            activities.append({
                "plannedActivityDetail": {
                    "code": {
                        "coding": [{
                            "system":  "http://loinc.org",
                            "code":    loinc.get("code", "55284-4"),
                            "display": loinc.get("display", "Clinical measurement"),
                        }]
                    },
                    "status":      "not-started",
                    "description": monitoring_item,
                }
            })

        return {
            "resourceType": "CarePlan",
            "status":        "draft",
            "intent":        "proposal",
            "title":         f"AI-Guided Care Plan: {request.condition_display}",
            "description":   branch["text"],
            "subject":       {"reference": patient_ref},
            "author": {
                "reference": "Device/ai-clinical-decision-support",
                "display":   "AI Clinical Decision Support (Prompt Opinion MCP)",
            },
            "goal": [{
                "description": {
                    "text": (
                        f"Target {loinc.get('display', 'clinical parameter')}: "
                        f"{loinc.get('target', 'as per guideline')}"
                    )
                },
                "target": [{
                    "measure": {
                        "coding": [{
                            "system":  "http://loinc.org",
                            "code":    loinc.get("code", ""),
                            "display": loinc.get("display", ""),
                        }]
                    },
                    "detailString": loinc.get("target", ""),
                }],
                "addresses": [{"reference": f"Condition/problem-{request.condition_code}"}],
            }],
            "activity": activities,
            "note": [{"text": f"Evidence source: {source}. Strength: {branch['strength'].value}. Grade: {branch['evidence'].value}."}],
            "extension": [{
                "url":      "http://promptopinion.com/fhir/StructureDefinition/sharp-guideline-source",
                "valueUri": f"urn:guideline:{source.replace(' ', '_')}",
            }],
        }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
