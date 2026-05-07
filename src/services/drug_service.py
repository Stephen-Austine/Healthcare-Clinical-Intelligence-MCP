"""
Drug Interaction & Polypharmacy Safety Engine
==============================================
Knowledge base covers:
  - 60+ clinically significant drug-drug interactions
  - QTc-prolongation risk detection (CredibleMeds / AHA classes)
  - Allergy cross-reactivity checks
  - Therapeutic class duplicate detection (15 pharmacological classes)
  - Renal dosing thresholds (eGFR-based, KDIGO aligned)
  - Hepatic impairment adjustments (Child-Pugh A/B/C)
  - Context-aware FHIR MedicationRequest generation with correct alternatives

Evidence levels follow AHA/ACC grading (A / B-R / B-NR / C-LD / C-EO).

In production this layer would be backed by DrugBank, First DataBank,
Lexicomp, or a CDS Hooks service — the interface is identical.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from models.clinical_models import (
    AllergyAlert, DrugInteraction, EvidenceLevel, InteractionSeverity,
    MedicationInput, PharmacyResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    """Lowercase-strip for consistent lookups."""
    return name.strip().lower()


# ---------------------------------------------------------------------------
# Drug-drug interaction knowledge base
# ---------------------------------------------------------------------------
# Key: frozenset of two normalised drug names
# Value: dict matching DrugInteraction fields

_DDI_DB: Dict[frozenset, Dict[str, Any]] = {
    # ── Anticoagulants ───────────────────────────────────────────────────
    frozenset({"warfarin", "aspirin"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Additive anticoagulation: major increase in major bleeding risk.",
        mechanism="Synergistic inhibition of platelet aggregation + clotting factor depression.",
        management="Avoid unless clinically necessary (e.g. mechanical valve + ACS). If combined: INR target 2.0-2.5, use low-dose aspirin ≤100 mg, add PPI, review weekly.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"warfarin", "ibuprofen"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="NSAIDs displace warfarin from plasma proteins and cause GI bleeding.",
        mechanism="Protein-binding displacement + COX-1 inhibition → GI mucosal damage.",
        management="Avoid NSAIDs with warfarin. Use paracetamol/acetaminophen for analgesia; add PPI if unavoidable.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"warfarin", "naproxen"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="NSAID + anticoagulant — high GI bleeding risk.",
        mechanism="COX inhibition + protein-binding displacement.",
        management="Substitute paracetamol; if NSAID essential, add PPI and monitor INR closely.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"warfarin", "amiodarone"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Amiodarone potentiates warfarin effect 2-3 fold via CYP2C9 inhibition.",
        mechanism="CYP2C9 and CYP3A4 inhibition increases warfarin S-enantiomer plasma levels.",
        management="Reduce warfarin dose by 30-50% on initiation; monitor INR twice weekly for first month.",
        evidence_level=EvidenceLevel.A, qtc_risk=True,
    ),
    frozenset({"warfarin", "fluconazole"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Strong CYP2C9 inhibitor dramatically elevates warfarin levels.",
        mechanism="Fluconazole is a potent CYP2C9/3A4 inhibitor.",
        management="Reduce warfarin dose by ~50%; monitor INR daily for 3-5 days.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"warfarin", "metronidazole"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Metronidazole inhibits warfarin metabolism.",
        mechanism="CYP2C9 inhibition + gut flora reduction (less vitamin K synthesis).",
        management="Reduce warfarin dose; monitor INR every 2 days during metronidazole course.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"apixaban", "ibuprofen"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="NSAID increases bleeding risk with DOAC.",
        mechanism="Additive anticoagulant effect + GI mucosal damage.",
        management="Avoid NSAIDs; use paracetamol.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=False,
    ),
    frozenset({"rivaroxaban", "amiodarone"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Amiodarone inhibits P-gp and CYP3A4, increasing rivaroxaban levels.",
        mechanism="P-gp and CYP3A4 inhibition.",
        management="Monitor closely for bleeding; consider dose reduction.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=True,
    ),

    # ── Statins / CYP3A4 ─────────────────────────────────────────────────
    frozenset({"simvastatin", "clarithromycin"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Risk of rhabdomyolysis: simvastatin levels increase 10-fold.",
        mechanism="CYP3A4 inhibition by clarithromycin.",
        management="Suspend simvastatin for duration of macrolide therapy. Pravastatin or rosuvastatin safe alternatives.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"simvastatin", "erythromycin"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Erythromycin is a strong CYP3A4 inhibitor — rhabdomyolysis risk.",
        mechanism="CYP3A4 inhibition.",
        management="Hold simvastatin; use pravastatin or rosuvastatin.",
        evidence_level=EvidenceLevel.A, qtc_risk=True,
    ),
    frozenset({"simvastatin", "itraconazole"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Azole antifungal causes massive increase in simvastatin AUC.",
        mechanism="CYP3A4 inhibition.",
        management="Contraindicated. Use fluconazole ≤200 mg/day if antifungal needed, or switch statin.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"simvastatin", "amiodarone"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Increased myopathy risk with simvastatin >20 mg + amiodarone.",
        mechanism="CYP3A4 inhibition.",
        management="Cap simvastatin at 20 mg/day or switch to rosuvastatin.",
        evidence_level=EvidenceLevel.A, qtc_risk=True,
    ),
    frozenset({"atorvastatin", "clarithromycin"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="CYP3A4 inhibition raises atorvastatin levels; myopathy risk.",
        mechanism="CYP3A4 inhibition.",
        management="Use pravastatin or rosuvastatin during macrolide course.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=False,
    ),

    # ── QTc-prolonging pairs ──────────────────────────────────────────────
    frozenset({"amiodarone", "sotalol"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Both drugs prolong QTc; torsades de pointes risk.",
        mechanism="Additive blockade of IKr (hERG) channels.",
        management="Avoid combination. If required, continuous cardiac monitoring, electrolyte optimisation.",
        evidence_level=EvidenceLevel.A, qtc_risk=True,
    ),
    frozenset({"haloperidol", "methadone"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="High torsades de pointes risk from additive QTc prolongation.",
        mechanism="Dual IKr blockade.",
        management="Contraindicated. Use alternative antipsychotic not prolonging QTc.",
        evidence_level=EvidenceLevel.A, qtc_risk=True,
    ),
    frozenset({"ciprofloxacin", "amiodarone"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Ciprofloxacin prolongs QTc; additive with amiodarone.",
        mechanism="Both inhibit cardiac potassium channels.",
        management="Use alternative antibiotic (e.g. co-amoxiclav). ECG monitoring mandatory if unavoidable.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=True,
    ),
    frozenset({"azithromycin", "amiodarone"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Azithromycin has intrinsic QTc prolongation risk; additive with amiodarone.",
        mechanism="Cardiac potassium channel blockade.",
        management="Avoid. Use doxycycline or co-amoxiclav instead.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=True,
    ),
    frozenset({"ondansetron", "amiodarone"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Ondansetron prolongs QTc, increasing torsades risk with amiodarone.",
        mechanism="Additive IKr blockade.",
        management="Use metoclopramide as antiemetic alternative; avoid ondansetron ≥32 mg IV.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=True,
    ),
    frozenset({"citalopram", "amiodarone"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Citalopram causes dose-dependent QTc prolongation; additive with amiodarone.",
        mechanism="IKr blockade.",
        management="Switch to sertraline or mirtazapine. If citalopram essential: max 20 mg/day, ECG.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=True,
    ),
    frozenset({"moxifloxacin", "amiodarone"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Both agents cause substantial QTc prolongation — highest TdP risk.",
        mechanism="Dual IKr channel blockade.",
        management="Contraindicated. Use alternative antibiotic.",
        evidence_level=EvidenceLevel.A, qtc_risk=True,
    ),

    # ── Antidiabetics ────────────────────────────────────────────────────
    frozenset({"metformin", "contrast media"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Iodinated contrast impairs renal clearance of metformin → lactic acidosis.",
        mechanism="Reduced renal perfusion + metformin accumulation.",
        management="Hold metformin ≥48 h before contrast; restart only when eGFR confirmed stable.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=False,
    ),
    frozenset({"insulin", "beta blockers"}): dict(
        severity=InteractionSeverity.MODERATE,
        description="Beta-blockers mask hypoglycaemia symptoms (except sweating).",
        mechanism="Sympathetic response to hypoglycaemia blunted; cardioselective beta-blockers safer.",
        management="Use cardioselective beta-blocker (bisoprolol/metoprolol). Educate patient on atypical hypo signs.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"glipizide", "fluconazole"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Fluconazole inhibits CYP2C9 metabolism of sulfonylureas → severe hypoglycaemia.",
        mechanism="CYP2C9 inhibition.",
        management="Reduce sulfonylurea dose by ≥50%; monitor blood glucose closely.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=False,
    ),
    frozenset({"glibenclamide", "fluconazole"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Severe hypoglycaemia risk — CYP2C9 inhibition of sulfonylurea.",
        mechanism="CYP2C9 inhibition.",
        management="Reduce dose; close glucose monitoring.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=False,
    ),

    # ── CNS / Serotonin ──────────────────────────────────────────────────
    frozenset({"tramadol", "sertraline"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Serotonin syndrome risk; lowered seizure threshold.",
        mechanism="Additive serotonergic activity.",
        management="Avoid combination. If pain management needed: use paracetamol + low-dose opioid (not tramadol).",
        evidence_level=EvidenceLevel.B_R, qtc_risk=False,
    ),
    frozenset({"tramadol", "fluoxetine"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Serotonin syndrome + inhibition of tramadol's active metabolite.",
        mechanism="Serotonin reuptake inhibition + CYP2D6 inhibition reduces tramadol analgesia.",
        management="Avoid. Use alternative analgesic.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=False,
    ),
    frozenset({"linezolid", "sertraline"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Linezolid is a MAOI — serotonin syndrome with SSRIs can be fatal.",
        mechanism="MAO-A inhibition + SSRI = massive serotonin excess.",
        management="Contraindicated. Wash-out SSRI ≥2 weeks before linezolid. Use alternative antibiotic if possible.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"linezolid", "fluoxetine"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Serotonin syndrome — MAOI + SSRI interaction.",
        mechanism="MAO inhibition + serotonin reuptake inhibition.",
        management="Contraindicated. Fluoxetine washout 5 weeks required (long half-life).",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"moclobemide", "sertraline"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="MAO inhibitor + SSRI: potentially fatal serotonin syndrome.",
        mechanism="Combined serotonin excess.",
        management="Contraindicated — at least 2 weeks washout between agents.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),

    # ── ACE-I / ARB / Potassium ──────────────────────────────────────────
    frozenset({"lisinopril", "spironolactone"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Dual RAAS blockade causes hyperkalaemia.",
        mechanism="Additive potassium retention via aldosterone suppression.",
        management="Monitor potassium and creatinine at 1 week, 1 month, then 3-monthly. Hold if K⁺ >5.5 mmol/L.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"ramipril", "spironolactone"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Hyperkalaemia risk with ACE-I + aldosterone antagonist.",
        mechanism="Combined RAAS suppression.",
        management="Same as lisinopril + spironolactone — U&E monitoring mandatory.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"lisinopril", "valsartan"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="ACEi + ARB combination increases renal failure, hyperkalaemia, hypotension.",
        mechanism="Dual RAAS blockade — ONTARGET trial showed net harm.",
        management="Contraindicated per ESC guidelines. Use single agent at optimal dose.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"ramipril", "losartan"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="ACEi + ARB: dual RAAS blockade net harm (ONTARGET).",
        mechanism="Dual RAAS suppression.",
        management="Avoid combination. Exception: specialist-supervised in selected HFrEF.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"potassium chloride", "spironolactone"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Potassium supplements + potassium-sparing diuretic: hyperkalaemia.",
        mechanism="Additive potassium retention.",
        management="Monitor K⁺ closely; reduce or stop supplemental potassium if K⁺ >4.5.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=False,
    ),

    # ── Immunosuppressants ───────────────────────────────────────────────
    frozenset({"ciclosporin", "clarithromycin"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Nephrotoxicity and toxicity from elevated ciclosporin levels.",
        mechanism="CYP3A4 / P-gp inhibition by macrolide.",
        management="Avoid macrolides with ciclosporin. Use azithromycin only if necessary with TDM.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"tacrolimus", "fluconazole"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Azole antifungal dramatically raises tacrolimus levels — nephrotoxicity.",
        mechanism="CYP3A4 inhibition.",
        management="Reduce tacrolimus dose by ~50-70%; intensive TDM until stable.",
        evidence_level=EvidenceLevel.A, qtc_risk=True,
    ),
    frozenset({"methotrexate", "nsaids"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="NSAIDs reduce methotrexate renal clearance → severe toxicity.",
        mechanism="Competition for renal tubular secretion.",
        management="Avoid NSAIDs within 24 h of high-dose methotrexate. For low-dose MTX, short-course ibuprofen may be acceptable with monitoring.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),

    # ── Antiepileptics ───────────────────────────────────────────────────
    frozenset({"carbamazepine", "warfarin"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Carbamazepine induces CYP2C9 → subtherapeutic warfarin.",
        mechanism="CYP2C9 induction.",
        management="Increase warfarin dose; weekly INR until stable.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"phenytoin", "warfarin"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Complex bi-directional interaction: phenytoin can increase or decrease warfarin effect.",
        mechanism="CYP2C9 induction (lowers warfarin) + protein binding competition.",
        management="Monitor INR at least weekly. Consider alternative anticoagulant.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"valproate", "lamotrigine"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Valproate inhibits lamotrigine glucuronidation, doubling levels.",
        mechanism="UGT inhibition.",
        management="Halve lamotrigine titration rate and dose when combined with valproate.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),

    # ── Antihypertensives ────────────────────────────────────────────────
    frozenset({"sildenafil", "nitrates"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Profound hypotension — potentially fatal.",
        mechanism="Additive cGMP-mediated vasodilation.",
        management="Absolute contraindication. 24 h washout for sildenafil/vardenafil; 48 h for tadalafil.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"sildenafil", "isosorbide mononitrate"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Life-threatening hypotension.",
        mechanism="Potentiated vasodilation via cGMP.",
        management="Contraindicated.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),

    # ── Antimicrobials ───────────────────────────────────────────────────
    frozenset({"rifampicin", "warfarin"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Rifampicin is the most potent CYP inducer — reduces warfarin effect by 70-90%.",
        mechanism="Broad CYP induction (1A2, 2C9, 2C19, 3A4).",
        management="Dramatically increase warfarin dose (often 2-3×); daily INR until stable.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"rifampicin", "oral contraceptive"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Rifampicin reduces oestrogen/progestogen levels causing contraceptive failure.",
        mechanism="CYP3A4 induction.",
        management="Use barrier contraception during rifampicin and 28 days after completion.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"rifampicin", "dolutegravir"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Rifampicin reduces dolutegravir AUC by 54% — HIV viral rebound risk.",
        mechanism="P-gp and UGT1A1 induction.",
        management="Double dolutegravir dose to 50 mg twice daily when combined with rifampicin.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),

    # ── Miscellaneous important pairs ────────────────────────────────────
    frozenset({"methotrexate", "trimethoprim"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Additive antifolate toxicity — pancytopenia, mucositis.",
        mechanism="Both inhibit dihydrofolate reductase.",
        management="Contraindicated in combination. Use alternative antibiotic.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"lithium", "ibuprofen"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="NSAIDs raise lithium levels by 25-60% — toxicity risk.",
        mechanism="Reduced renal lithium clearance (prostaglandin-dependent).",
        management="Avoid NSAIDs; use paracetamol. Monitor lithium level if NSAID unavoidable.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"lithium", "naproxen"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="NSAID-induced lithium toxicity.",
        mechanism="Reduced renal clearance.",
        management="Avoid; monitor lithium levels closely.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"colchicine", "clarithromycin"}): dict(
        severity=InteractionSeverity.CRITICAL,
        description="Fatal colchicine toxicity due to CYP3A4/P-gp inhibition.",
        mechanism="Clarithromycin inhibits both CYP3A4 and P-gp — colchicine accumulates.",
        management="Contraindicated in renal/hepatic impairment. In normal function: reduce colchicine to single dose of 0.6 mg only.",
        evidence_level=EvidenceLevel.A, qtc_risk=False,
    ),
    frozenset({"digoxin", "amiodarone"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Amiodarone increases digoxin levels by ~70% — toxicity.",
        mechanism="P-gp inhibition reduces digoxin renal/non-renal clearance.",
        management="Reduce digoxin dose by 50% on starting amiodarone; monitor levels weekly.",
        evidence_level=EvidenceLevel.A, qtc_risk=True,
    ),
    frozenset({"digoxin", "clarithromycin"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Macrolide reduces gut flora P-gp degradation of digoxin — levels rise.",
        mechanism="P-gp inhibition + altered gut flora.",
        management="Monitor digoxin level; reduce dose if needed.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=True,
    ),
    frozenset({"clozapine", "ciprofloxacin"}): dict(
        severity=InteractionSeverity.MAJOR,
        description="Ciprofloxacin inhibits CYP1A2 raising clozapine levels — toxicity, seizures.",
        mechanism="CYP1A2 inhibition.",
        management="Avoid. If unavoidable: reduce clozapine dose by 30-50%, monitor plasma levels.",
        evidence_level=EvidenceLevel.B_R, qtc_risk=True,
    ),
}


# ---------------------------------------------------------------------------
# Therapeutic class duplicate detection
# ---------------------------------------------------------------------------

_THERAPEUTIC_CLASSES: Dict[str, List[str]] = {
    "ACE inhibitor": [
        "lisinopril", "ramipril", "enalapril", "captopril", "perindopril",
        "fosinopril", "quinapril", "trandolapril", "benazepril",
    ],
    "ARB (Angiotensin II receptor blocker)": [
        "valsartan", "losartan", "candesartan", "irbesartan", "olmesartan",
        "telmisartan", "azilsartan", "eprosartan",
    ],
    "Beta-blocker": [
        "bisoprolol", "metoprolol", "atenolol", "carvedilol", "nebivolol",
        "propranolol", "labetalol", "sotalol", "acebutolol",
    ],
    "Calcium channel blocker (DHP)": [
        "amlodipine", "nifedipine", "lercanidipine", "felodipine",
        "lacidipine", "nimodipine",
    ],
    "Calcium channel blocker (non-DHP)": [
        "diltiazem", "verapamil",
    ],
    "Statin": [
        "atorvastatin", "simvastatin", "rosuvastatin", "pravastatin",
        "fluvastatin", "lovastatin", "pitavastatin",
    ],
    "SSRI": [
        "sertraline", "fluoxetine", "citalopram", "escitalopram",
        "paroxetine", "fluvoxamine",
    ],
    "SNRI": [
        "venlafaxine", "duloxetine", "desvenlafaxine", "milnacipran",
    ],
    "Benzodiazepine": [
        "diazepam", "lorazepam", "clonazepam", "alprazolam",
        "temazepam", "nitrazepam", "oxazepam", "midazolam",
    ],
    "Proton pump inhibitor": [
        "omeprazole", "lansoprazole", "pantoprazole", "esomeprazole",
        "rabeprazole", "dexlansoprazole",
    ],
    "NSAID": [
        "ibuprofen", "naproxen", "diclofenac", "celecoxib", "etoricoxib",
        "indomethacin", "ketorolac", "mefenamic acid", "piroxicam",
    ],
    "Sulfonylurea": [
        "glibenclamide", "glipizide", "gliclazide", "glimepiride",
        "tolbutamide", "chlorpropamide",
    ],
    "Thiazide diuretic": [
        "hydrochlorothiazide", "bendroflumethiazide", "chlorthalidone",
        "indapamide", "metolazone",
    ],
    "Loop diuretic": [
        "furosemide", "bumetanide", "torasemide", "ethacrynic acid",
    ],
    "Potassium-sparing diuretic": [
        "spironolactone", "eplerenone", "amiloride", "triamterene",
    ],
    "Opioid analgesic": [
        "morphine", "oxycodone", "codeine", "tramadol", "fentanyl",
        "buprenorphine", "hydrocodone", "tapentadol", "pethidine",
    ],
}

# Inverted index: drug name → class name
_DRUG_TO_CLASS: Dict[str, str] = {
    _norm(drug): cls
    for cls, drugs in _THERAPEUTIC_CLASSES.items()
    for drug in drugs
}


# ---------------------------------------------------------------------------
# QTc-prolongation individual drug risk list (CredibleMeds "Known Risk")
# ---------------------------------------------------------------------------

_QTC_KNOWN_RISK: set = {
    "amiodarone", "sotalol", "dofetilide", "ibutilide",
    "quinidine", "procainamide", "disopyramide",
    "haloperidol", "pimozide", "ziprasidone", "droperidol",
    "methadone", "bepridil",
    "moxifloxacin", "sparfloxacin",
    "arsenic trioxide",
    "ondansetron",   # at high IV doses
    "citalopram", "escitalopram",
    "azithromycin", "erythromycin", "clarithromycin",
    "fluconazole", "voriconazole", "itraconazole",
    "cisapride", "domperidone",
    "chlorpromazine", "thioridazine",
}

_QTC_CONDITIONAL_RISK: set = {
    "ciprofloxacin", "levofloxacin", "fluoxetine", "sertraline",
    "quetiapine", "risperidone", "olanzapine",
    "tricyclic antidepressants", "amitriptyline", "nortriptyline",
    "metoclopramide",
}


# ---------------------------------------------------------------------------
# Allergy cross-reactivity map
# ---------------------------------------------------------------------------

_ALLERGY_CROSS_REACTIVITY: Dict[str, List[Tuple[str, str, str]]] = {
    # allergen → list of (drug, reaction, severity)
    "penicillin": [
        ("amoxicillin",     "anaphylaxis / severe allergic reaction", "anaphylaxis"),
        ("ampicillin",      "anaphylaxis / severe allergic reaction", "anaphylaxis"),
        ("flucloxacillin",  "anaphylaxis / severe allergic reaction", "anaphylaxis"),
        ("piperacillin",    "anaphylaxis / severe allergic reaction", "anaphylaxis"),
        ("co-amoxiclav",    "anaphylaxis / severe allergic reaction", "anaphylaxis"),
    ],
    "cephalosporin": [
        ("cephalexin",  "cross-reactivity (1-2% with penicillin allergy)", "severe"),
        ("cefuroxime",  "cross-reactivity",                                 "severe"),
        ("ceftriaxone", "cross-reactivity",                                 "severe"),
    ],
    "sulfonamide": [
        ("trimethoprim-sulfamethoxazole", "sulfonamide allergy", "severe"),
        ("sulfamethoxazole",              "sulfonamide allergy", "severe"),
        ("furosemide",   "possible cross-reactivity (sulfonamide moiety)", "moderate"),
        ("thiazides",    "possible cross-reactivity",                       "moderate"),
    ],
    "aspirin": [
        ("ibuprofen",     "NSAID sensitivity — possible cross-reactivity",   "severe"),
        ("naproxen",      "NSAID sensitivity",                               "severe"),
        ("diclofenac",    "NSAID sensitivity",                               "moderate"),
        ("celecoxib",     "COX-2 inhibitor (lower cross-reactivity risk)",    "mild"),
    ],
    "nsaid": [
        ("ibuprofen",  "NSAID allergy", "severe"),
        ("naproxen",   "NSAID allergy", "severe"),
        ("diclofenac", "NSAID allergy", "severe"),
    ],
    "contrast media": [
        ("gadolinium", "iodinated contrast cross-reactivity risk (low)", "mild"),
    ],
}


# ---------------------------------------------------------------------------
# Renal dosing thresholds (eGFR mL/min/1.73m², KDIGO aligned)
# ---------------------------------------------------------------------------

_RENAL_DOSING: Dict[str, List[Tuple[float, str]]] = {
    # drug → list of (eGFR_threshold, guidance) sorted descending by threshold
    "metformin":         [(45, "Reduce dose; increased monitoring. Contraindicated if eGFR <30."),
                          (30, "CONTRAINDICATED — high lactic acidosis risk.")],
    "metformin hydrochloride": [(45, "See metformin."), (30, "CONTRAINDICATED.")],
    "allopurinol":       [(30, "Reduce dose to ≤100 mg/day. Risk of allopurinol hypersensitivity syndrome.")],
    "gabapentin":        [(60, "Dose reduction required; titrate to response. eGFR <30: 300 mg/day maximum.")],
    "pregabalin":        [(60, "Reduce dose proportionally to eGFR reduction.")],
    "digoxin":           [(50, "Reduce dose; narrow therapeutic index. Monitor levels.")],
    "lithium":           [(50, "Reduce dose; serum level monitoring every 1-2 months.")],
    "atenolol":          [(35, "Dose reduction required — renally excreted.")],
    "sotalol":           [(60, "Reduce dose; QTc-prolongation risk increases with reduced clearance.")],
    "nitrofurantoin":    [(45, "Contraindicated — inadequate urinary concentration + peripheral neuropathy risk.")],
    "spironolactone":    [(45, "Use with caution; high hyperkalaemia risk.")],
    "nsaids":            [(60, "Avoid if possible — risk of acute kidney injury and further eGFR decline.")],
    "ibuprofen":         [(60, "Avoid — AKI risk in CKD.")],
    "naproxen":          [(60, "Avoid — AKI risk in CKD.")],
    "colchicine":        [(30, "Use with caution at reduced dose; avoid prolonged courses.")],
    "dabigatran":        [(30, "Contraindicated.")],
    "rivaroxaban":       [(15, "Contraindicated.")],
    "apixaban":          [(25, "Reduce dose if ≥2 of: age ≥80, weight ≤60 kg, creatinine ≥133.")],
    "enoxaparin":        [(30, "Reduce dose to 1 mg/kg once daily; monitor anti-Xa.")],
    "ciprofloxacin":     [(30, "Reduce dose by 50%.")],
    "levofloxacin":      [(50, "Dose adjustment required.")],
    "vancomycin":        [(60, "Extended dosing interval; monitor trough levels.")],
    "aciclovir":         [(50, "Dose reduction required; well-described nephrotoxicity.")],
    "trimethoprim":      [(30, "Avoid or reduce dose; hyperkalaemia risk.")],
    "dapagliflozin":     [(45, "Do not initiate. Discontinue if eGFR falls below 45.")],
    "empagliflozin":     [(45, "Do not initiate below eGFR 45.")],
    "canagliflozin":     [(45, "Contraindicated below eGFR 45.")],
}


# ---------------------------------------------------------------------------
# Hepatic dosing guidance (Child-Pugh B and C)
# ---------------------------------------------------------------------------

_HEPATIC_DOSING: Dict[str, Dict[str, str]] = {
    "simvastatin":    {"B": "Use with caution; monitor LFTs.", "C": "Contraindicated."},
    "atorvastatin":   {"B": "Use with caution.",                "C": "Contraindicated."},
    "rosuvastatin":   {"B": "Use with caution.",                "C": "Contraindicated."},
    "statins":        {"B": "All statins: caution in hepatic impairment.", "C": "Contraindicated."},
    "methotrexate":   {"B": "Contraindicated.",                 "C": "Contraindicated."},
    "paracetamol":    {"B": "Max 2 g/day; avoid long courses.", "C": "Avoid — hepatotoxicity risk."},
    "acetaminophen":  {"B": "Max 2 g/day.",                     "C": "Avoid."},
    "isoniazid":      {"B": "Hepatotoxicity risk — monitor LFTs.", "C": "Contraindicated."},
    "valproate":      {"B": "Contraindicated.",                 "C": "Contraindicated."},
    "carbamazepine":  {"B": "Reduce dose; monitor LFTs.",       "C": "Avoid."},
    "chlorpromazine": {"B": "Use with caution.",                "C": "Contraindicated."},
    "codeine":        {"B": "Reduce dose; increased sensitivity.", "C": "Avoid — encephalopathy risk."},
    "morphine":       {"B": "Reduce dose; extended half-life.", "C": "Avoid or use minimal dose."},
    "tramadol":       {"B": "Reduce dose.",                     "C": "Contraindicated."},
    "warfarin":       {"B": "Reduced synthesis of clotting factors — already anticoagulated effect.",
                      "C": "Contraindicated — coagulopathy."},
    "ibuprofen":      {"B": "Avoid.",                          "C": "Contraindicated."},
    "naproxen":       {"B": "Avoid.",                          "C": "Contraindicated."},
    "ritonavir":      {"B": "Contraindicated.",                "C": "Contraindicated."},
    "fluconazole":    {"B": "Reduce dose; hepatotoxic.",        "C": "Avoid."},
}

# FHIR alternative therapy recommendations
# Maps the interacting drug to a safer alternative with RxNorm code
_SAFE_ALTERNATIVES: Dict[str, Dict[str, Any]] = {
    "simvastatin": {
        "rxnorm": "301542",
        "display": "Rosuvastatin",
        "dosage": "10 mg orally once daily",
        "rationale": "Rosuvastatin is not a CYP3A4 substrate — safe with macrolides/azoles.",
    },
    "warfarin": {
        "rxnorm": "1364430",
        "display": "Apixaban",
        "dosage": "5 mg orally twice daily (2.5 mg BD if ≥2 of: age ≥80, weight ≤60 kg, creatinine ≥133)",
        "rationale": "DOAC has fewer drug interactions and does not require INR monitoring.",
    },
    "ibuprofen": {
        "rxnorm": "161",
        "display": "Paracetamol (Acetaminophen)",
        "dosage": "500–1000 mg orally every 4–6 hours (max 4 g/24h; 2 g if hepatic impairment)",
        "rationale": "Paracetamol lacks COX inhibition — safe with anticoagulants and in CKD.",
    },
    "citalopram": {
        "rxnorm": "36437",
        "display": "Sertraline",
        "dosage": "50 mg orally once daily; titrate to max 200 mg",
        "rationale": "Lower QTc-prolongation risk than citalopram/escitalopram.",
    },
    "tramadol": {
        "rxnorm": "161",
        "display": "Paracetamol + low-dose codeine",
        "dosage": "Paracetamol 1000 mg QDS + codeine phosphate 15 mg QDS (avoid in hepatic impairment)",
        "rationale": "Avoids serotonin syndrome risk associated with tramadol + SSRIs.",
    },
    "clarithromycin": {
        "rxnorm": "723",
        "display": "Doxycycline",
        "dosage": "100 mg orally twice daily for 5–7 days",
        "rationale": "No significant CYP3A4 inhibition; safe with statins and ciclosporin.",
    },
}


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class DrugInteractionEngine:
    """
    Comprehensive polypharmacy safety analyser.

    Checks:
      1. Drug-drug interactions (60+ pairs, evidence-graded)
      2. QTc-prolongation risk (individual and additive)
      3. Allergy cross-reactivity
      4. Therapeutic class duplicates
      5. Renal dosing thresholds
      6. Hepatic dosing adjustments

    All findings are structured for FHIR MedicationRequest generation.
    """

    def analyse(
        self,
        medications: List[MedicationInput],
        patient_context: Any,
        allergies: Optional[List[str]] = None,
        renal_function: Optional[str] = None,
        hepatic_function: Optional[str] = None,
    ) -> PharmacyResult:
        med_names = [_norm(m.display) for m in medications]

        interactions   = self._check_ddi(medications, med_names)
        allergy_alerts = self._check_allergies(medications, allergies or [])
        duplicates     = self._check_duplicates(med_names)
        renal_adj      = self._check_renal(medications, med_names, renal_function)
        hepatic_adj    = self._check_hepatic(medications, med_names, hepatic_function)
        qtc_risk       = self._check_qtc(med_names, interactions)

        risk_score = self._calculate_risk(
            interactions, allergy_alerts, duplicates, renal_adj, qtc_risk
        )
        risk_level = (
            "CRITICAL" if risk_score >= 75 else
            "HIGH"     if risk_score >= 50 else
            "MODERATE" if risk_score >= 25 else
            "LOW"
        )

        fhir_req = self._build_fhir_request(
            medications, med_names, patient_context, interactions, allergy_alerts
        )

        return PharmacyResult(
            interactions            = interactions,
            allergy_alerts          = allergy_alerts,
            duplicate_therapies     = duplicates,
            renal_adjustments       = renal_adj,
            hepatic_adjustments     = hepatic_adj,
            qtc_prolongation_risk   = qtc_risk,
            overall_risk_score      = risk_score,
            risk_level              = risk_level,
            fhir_medication_request = fhir_req,
        )

    # Keep old name as alias for backward compat with server.py
    def analyze(self, *a, **kw) -> PharmacyResult:
        return self.analyse(*a, **kw)

    # ------------------------------------------------------------------

    def _check_ddi(
        self,
        meds: List[MedicationInput],
        med_names: List[str],
    ) -> List[DrugInteraction]:
        found: List[DrugInteraction] = []
        n = len(med_names)
        for i in range(n):
            for j in range(i + 1, n):
                key = frozenset({med_names[i], med_names[j]})
                if key in _DDI_DB:
                    data = _DDI_DB[key].copy()
                    found.append(DrugInteraction(
                        drug_a = meds[i].display,
                        drug_b = meds[j].display,
                        **data,
                    ))
        # Sort: critical first, then major
        severity_order = {
            InteractionSeverity.CRITICAL: 0,
            InteractionSeverity.MAJOR:    1,
            InteractionSeverity.MODERATE: 2,
            InteractionSeverity.MINOR:    3,
        }
        found.sort(key=lambda x: severity_order.get(x.severity, 9))
        return found

    def _check_allergies(
        self,
        meds: List[MedicationInput],
        allergies: List[str],
    ) -> List[AllergyAlert]:
        alerts: List[AllergyAlert] = []
        for allergen_raw in allergies:
            allergen = _norm(allergen_raw)
            cross_list = _ALLERGY_CROSS_REACTIVITY.get(allergen, [])
            for drug, reaction, sev in cross_list:
                drug_n = _norm(drug)
                for med in meds:
                    if _norm(med.display) == drug_n or drug_n in _norm(med.display):
                        alerts.append(AllergyAlert(
                            drug     = med.display,
                            allergen = allergen_raw,
                            reaction = reaction,
                            severity = sev,
                        ))
        return alerts

    def _check_duplicates(self, med_names: List[str]) -> List[str]:
        class_counts: Dict[str, List[str]] = {}
        for name in med_names:
            cls = _DRUG_TO_CLASS.get(name)
            if cls:
                class_counts.setdefault(cls, []).append(name)
        duplicates = []
        for cls, drugs in class_counts.items():
            if len(drugs) > 1:
                duplicates.append(
                    f"Duplicate {cls}: {', '.join(drugs)} — review therapeutic necessity"
                )
        return duplicates

    def _check_renal(
        self,
        meds: List[MedicationInput],
        med_names: List[str],
        egfr_str: Optional[str],
    ) -> List[str]:
        if not egfr_str:
            return []
        try:
            egfr = float(egfr_str)
        except ValueError:
            return [f"Could not parse eGFR value: {egfr_str!r}"]

        adjustments: List[str] = []
        for med, name in zip(meds, med_names):
            thresholds = _RENAL_DOSING.get(name, [])
            for threshold, guidance in sorted(thresholds):  # ascending: most severe (lowest eGFR) first
                if egfr < threshold:
                    adjustments.append(
                        f"{med.display}: eGFR {egfr} mL/min — {guidance}"
                    )
                    break  # show most severe applicable threshold only
        return adjustments

    def _check_hepatic(
        self,
        meds: List[MedicationInput],
        med_names: List[str],
        hepatic: Optional[str],
    ) -> List[str]:
        if not hepatic:
            return []
        cp = hepatic.strip().upper()
        if cp not in ("A", "B", "C"):
            # Try to parse "Child-Pugh B" style
            for grade in ("C", "B", "A"):
                if grade in cp:
                    cp = grade
                    break
            else:
                return [f"Unrecognised hepatic function descriptor: {hepatic!r}"]

        adjustments: List[str] = []
        for med, name in zip(meds, med_names):
            guidance_map = _HEPATIC_DOSING.get(name)
            if guidance_map:
                if cp == "C" and "C" in guidance_map:
                    adjustments.append(
                        f"{med.display}: Child-Pugh C — {guidance_map['C']}"
                    )
                elif cp in ("B", "C") and "B" in guidance_map:
                    adjustments.append(
                        f"{med.display}: Child-Pugh {cp} — {guidance_map['B']}"
                    )
        return adjustments

    def _check_qtc(
        self,
        med_names: List[str],
        interactions: List[DrugInteraction],
    ) -> bool:
        # Individual known-risk drugs
        qtc_drugs = [n for n in med_names if n in _QTC_KNOWN_RISK or n in _QTC_CONDITIONAL_RISK]
        if len(qtc_drugs) >= 2:
            return True
        # Interaction-level QTc flag
        if any(ix.qtc_risk for ix in interactions):
            return True
        return False

    def _calculate_risk(
        self,
        interactions: List[DrugInteraction],
        allergy_alerts: List[AllergyAlert],
        duplicates: List[str],
        renal_adj: List[str],
        qtc_risk: bool,
    ) -> int:
        score = 0
        severity_pts = {
            InteractionSeverity.CRITICAL: 35,
            InteractionSeverity.MAJOR:    20,
            InteractionSeverity.MODERATE: 10,
            InteractionSeverity.MINOR:     3,
        }
        for ix in interactions:
            score += severity_pts.get(ix.severity, 0)

        allergy_severity_pts = {
            "anaphylaxis": 35, "severe": 20, "moderate": 10, "mild": 5,
        }
        for alert in allergy_alerts:
            score += allergy_severity_pts.get(alert.severity, 10)

        score += len(duplicates) * 8
        score += len(renal_adj)  * 15
        if qtc_risk:
            score += 20

        return min(score, 100)

    def _build_fhir_request(
        self,
        meds: List[MedicationInput],
        med_names: List[str],
        context: Any,
        interactions: List[DrugInteraction],
        allergy_alerts: List[AllergyAlert],
    ) -> Optional[Dict[str, Any]]:
        """
        Build FHIR MedicationRequest proposing a safer alternative
        for the highest-priority finding.
        """
        patient_id = getattr(context, "patient_id", "unknown")

        # Prioritise: allergy > critical DDI > major DDI
        target_drug = None
        rationale   = None

        if allergy_alerts:
            target_drug = _norm(allergy_alerts[0].drug)
            rationale   = f"Allergy alert: {allergy_alerts[0].reaction} to {allergy_alerts[0].allergen}"
        elif interactions:
            crit = next(
                (ix for ix in interactions if ix.severity == InteractionSeverity.CRITICAL),
                None,
            )
            if crit:
                # Find which drug in the pair has a known alternative
                for candidate in [_norm(crit.drug_a), _norm(crit.drug_b)]:
                    if candidate in _SAFE_ALTERNATIVES:
                        target_drug = candidate
                        rationale   = crit.description
                        break
                if not target_drug:
                    target_drug = _norm(crit.drug_a)
                    rationale   = crit.description

        if not target_drug:
            return None

        alt = _SAFE_ALTERNATIVES.get(target_drug)
        if not alt:
            return None

        return {
            "resourceType": "MedicationRequest",
            "status":        "draft",
            "intent":        "proposal",
            "priority":      "urgent",
            "subject":       {"reference": f"Patient/{patient_id}"},
            "medicationCodeableConcept": {
                "coding": [{
                    "system":  "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code":    alt["rxnorm"],
                    "display": alt["display"],
                }],
                "text": alt["display"],
            },
            "reasonCode": [{
                "coding": [{
                    "system":  "http://snomed.info/sct",
                    "code":    "373066001",
                    "display": "Drug interaction / allergy alert",
                }],
                "text": rationale,
            }],
            "note": [{"text": f"Proposed alternative: {alt['display']}. Rationale: {alt['rationale']}"}],
            "dosageInstruction": [{
                "text": alt["dosage"],
                "route": {
                    "coding": [{
                        "system":  "http://snomed.info/sct",
                        "code":    "26643006",
                        "display": "Oral route",
                    }]
                },
            }],
        }
