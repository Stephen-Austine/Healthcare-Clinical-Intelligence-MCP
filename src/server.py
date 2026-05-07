#!/usr/bin/env python3
"""
Healthcare AI Superpower - MCP Server
Clinical Decision Support with FHIR R5 Integration

This MCP server exposes three specialized tools:
1. clinical_triage - AI-powered patient triage with FHIR Observation writes
2. analyze_polypharmacy - Multi-drug safety analysis with FHIR MedicationRequest generation
3. get_clinical_guideline - Evidence-based recommendations with FHIR CarePlan creation

Built for the Agents Assemble Hackathon - Prompt Opinion Platform
"""

import asyncio
from mcp.server.fastmcp import FastMCP

# Import tool functions
from tools.triage_tool import clinical_triage
from tools.pharmacy_tool import analyze_polypharmacy
from tools.guideline_tool import get_clinical_guideline

# Initialize MCP server
mcp = FastMCP("healthcare-clinical-intelligence")

# Register tools with descriptive schemas
@mcp.tool()
async def clinical_triage_tool(
    symptoms_json: str,
    patient_id: str,
    chief_complaint: str,
    vital_signs_json: str = "{}",
    age_years: int = None,
    sex: str = "unknown",
    pregnant: bool = False,
    has_copd: bool = False,
) -> str:
    """
    Perform AI-powered clinical triage using NEWS2 + ESI-5 + symptom pattern recognition.

    Args:
        symptoms_json:    JSON array [{"code":"snomed_code","display":"name","severity":1-10}]
        patient_id:       FHIR Patient ID (propagated via SHARP context)
        chief_complaint:  Primary reason for presentation
        vital_signs_json: Optional {"systolic_bp":120,"heart_rate":80,"oxygen_saturation":98,
                          "respiratory_rate":16,"temperature":37.0,"gcs":15,"pain_score":5}
        age_years:        Patient age — improves paediatric/geriatric risk stratification
        sex:              "male"|"female"|"other"|"unknown"
        pregnant:         True if known pregnancy — escalates triage priority
        has_copd:         True for confirmed COPD — enables NEWS2 SpO2 Scale 2

    Returns:
        JSON with triage_priority, esi_level, risk_score, news2_score, reasoning,
        clinical_flags, recommended_actions, fhir_observation_reference,
        estimated_wait_minutes
    """
    return await clinical_triage(
        symptoms_json, patient_id, chief_complaint,
        vital_signs_json, age_years, sex, pregnant, has_copd,
    )


@mcp.tool()
async def analyze_polypharmacy_tool(
    medications_json: str,
    patient_id: str,
    allergies_json: str = "[]",
    renal_function: str = None,
    hepatic_function: str = None
) -> str:
    """
    Analyze medication regimen for drug interactions, duplicates, and organ-adjusted dosing.
    
    Args:
        medications_json: JSON array [{"code": "rxnorm", "display": "Drug Name", "dosage": "10mg daily"}]
        patient_id: FHIR Patient ID
        allergies_json: JSON array of known allergies
        renal_function: eGFR in mL/min/1.73m²
        hepatic_function: Child-Pugh classification or description
    
    Returns:
        JSON with risk score, interaction details, and FHIR MedicationRequest for alternatives
    """
    return await analyze_polypharmacy(
        medications_json, patient_id, allergies_json, 
        renal_function, hepatic_function
    )


@mcp.tool()
async def get_clinical_guideline_tool(
    condition_code: str,
    condition_display: str,
    patient_id: str,
    current_medications_json: str = "[]",
    comorbidities_json: str = "[]"
) -> str:
    """
    Retrieve evidence-based clinical guideline recommendations.
    
    Args:
        condition_code: ICD-10 or SNOMED CT code (e.g., "E11" for Type 2 Diabetes)
        condition_display: Human-readable condition name
        patient_id: FHIR Patient ID
        current_medications_json: JSON array of current medication names
        comorbidities_json: JSON array of comorbidity codes
    
    Returns:
        JSON with guideline source, recommendation strength, applicable medications, and FHIR CarePlan
    """
    return await get_clinical_guideline(
        condition_code, condition_display, patient_id,
        current_medications_json, comorbidities_json
    )


@mcp.resource("fhir://patient/{patient_id}/summary")
async def get_patient_summary(patient_id: str) -> str:
    """
    MCP Resource: Retrieve patient clinical summary from FHIR server.
    Accessible as a resource for agent context building.
    """
    from services.fhir_client import FHIRClient, FHIRContextBridge
    
    # In production, extract from request context
    client = FHIRClient("https://hapi.fhir.org/baseR5")
    try:
        patient = await client.get_patient(patient_id)
        meds = await client.get_medications(patient_id)
        conditions = await client.get_conditions(patient_id)
        
        return f"""
        Patient Summary ({patient_id}):
        Name: {patient.get('name', [{}])[0].get('text', 'Unknown')}
        DOB: {patient.get('birthDate', 'Unknown')}
        Active Conditions: {len(conditions)}
        Active Medications: {len(meds)}
        """
    except Exception as e:
        return f"Error retrieving patient summary: {str(e)}"
    finally:
        await client.close()


def main():
    """Entry point for MCP server"""
    mcp.run(transport='stdio')


if __name__ == "__main__":
    main()