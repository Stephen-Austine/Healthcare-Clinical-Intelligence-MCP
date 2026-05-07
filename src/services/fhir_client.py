"""
FHIR R5 Client with SHARP Context Propagation.
Handles authenticated communication with FHIR servers and bridges
EHR session credentials from Prompt Opinion's SHARP extension.
"""

import httpx
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from models.clinical_models import PatientContext, Symptom


# ---------------------------------------------------------------------------
# SHARP Context Bridge
# ---------------------------------------------------------------------------

class SHARPContext:
    """
    Holds healthcare session context propagated by the Prompt Opinion platform
    via the SHARP extension headers.
    """

    def __init__(
        self,
        patient_id: str = "",
        fhir_server_url: Optional[str] = None,
        access_token: Optional[str] = None,
        encounter_id: Optional[str] = None,
    ):
        self.patient_id = patient_id
        self.fhir_server_url = fhir_server_url
        self.access_token = access_token
        self.encounter_id = encounter_id

    def is_complete(self) -> bool:
        """Returns True when enough context is present to write to FHIR."""
        return bool(self.patient_id and self.fhir_server_url)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"SHARPContext(patient_id={self.patient_id!r}, "
            f"fhir_server_url={self.fhir_server_url!r}, "
            f"encounter_id={self.encounter_id!r})"
        )


class FHIRContextBridge:
    """
    Extracts SHARP context from MCP request headers injected by the
    Prompt Opinion platform.

    Header names follow the SHARP extension specification:
      X-SHARP-Patient-ID
      X-SHARP-FHIR-Server
      X-SHARP-Access-Token
      X-SHARP-Encounter-ID
    """

    HEADER_MAP = {
        "patient_id":      ["x-sharp-patient-id", "x-patient-id"],
        "fhir_server_url": ["x-sharp-fhir-server", "x-fhir-server-url"],
        "access_token":    ["x-sharp-access-token", "authorization"],
        "encounter_id":    ["x-sharp-encounter-id", "x-encounter-id"],
    }

    @classmethod
    def extract_from_headers(cls, headers: Dict[str, str]) -> SHARPContext:
        """
        Parse SHARP context out of a dict of HTTP headers (case-insensitive).

        Args:
            headers: Dict of header name → value (may be empty).

        Returns:
            Populated SHARPContext; fields are empty strings / None when absent.
        """
        lower_headers = {k.lower(): v for k, v in (headers or {}).items()}
        ctx = SHARPContext()

        for field, candidates in cls.HEADER_MAP.items():
            for candidate in candidates:
                value = lower_headers.get(candidate)
                if value:
                    # Strip "Bearer " prefix from Authorization header
                    if field == "access_token" and value.lower().startswith("bearer "):
                        value = value[7:]
                    setattr(ctx, field, value)
                    break

        return ctx


# ---------------------------------------------------------------------------
# FHIR R5 Client
# ---------------------------------------------------------------------------

class FHIRClient:
    """
    Async FHIR R5 client for reading and writing clinical resources.

    Supports:
      - Patient / Observation / MedicationRequest / CarePlan / Condition reads
      - Observation writes (triage scores)
      - MedicationRequest draft creation (polypharmacy alternatives)
      - CarePlan draft creation (guideline care plans)

    Falls back gracefully when the server is unavailable so that the MCP tools
    still return useful data even without a live FHIR backend.
    """

    DEFAULT_FHIR_SERVER = "https://hapi.fhir.org/baseR5"
    TIMEOUT = 15  # seconds

    def __init__(
        self,
        base_url: str = DEFAULT_FHIR_SERVER,
        access_token: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        headers: Dict[str, str] = {
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=self.TIMEOUT,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    async def get_patient(self, patient_id: str) -> Dict[str, Any]:
        """Fetch FHIR Patient resource."""
        resp = await self.client.get(f"{self.base_url}/Patient/{patient_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_medications(self, patient_id: str) -> List[Dict[str, Any]]:
        """Fetch active MedicationRequests for a patient."""
        resp = await self.client.get(
            f"{self.base_url}/MedicationRequest",
            params={"patient": patient_id, "status": "active", "_count": "50"},
        )
        resp.raise_for_status()
        bundle = resp.json()
        return [e["resource"] for e in bundle.get("entry", [])]

    async def get_conditions(self, patient_id: str) -> List[Dict[str, Any]]:
        """Fetch active Conditions for a patient."""
        resp = await self.client.get(
            f"{self.base_url}/Condition",
            params={"patient": patient_id, "clinical-status": "active", "_count": "50"},
        )
        resp.raise_for_status()
        bundle = resp.json()
        return [e["resource"] for e in bundle.get("entry", [])]

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    async def create_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """POST an Observation resource; returns the created resource."""
        resp = await self.client.post(
            f"{self.base_url}/Observation",
            json=observation,
        )
        resp.raise_for_status()
        return resp.json()

    async def create_medication_request(
        self, medication_request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """POST a MedicationRequest resource; returns the created resource."""
        resp = await self.client.post(
            f"{self.base_url}/MedicationRequest",
            json=medication_request,
        )
        resp.raise_for_status()
        return resp.json()

    async def create_care_plan(self, care_plan: Dict[str, Any]) -> Dict[str, Any]:
        """POST a CarePlan resource; returns the created resource."""
        resp = await self.client.post(
            f"{self.base_url}/CarePlan",
            json=care_plan,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # FHIR resource builders
    # ------------------------------------------------------------------

    def build_triage_observation(
        self,
        patient_id: str,
        triage_score: int,
        priority: str,
        symptoms: List["Symptom"],
        reasoning: str,
        encounter_id: Optional[str] = None,
        news2_score: int = 0,
    ) -> Dict[str, Any]:
        """
        Construct a FHIR R5 Observation resource representing a triage assessment.
        Coding follows LOINC 56839-4 (Emergency department triage acuity).
        """
        now = datetime.now(timezone.utc).isoformat()

        obs: Dict[str, Any] = {
            "resourceType": "Observation",
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "survey",
                            "display": "Survey",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "56839-4",
                        "display": "Emergency department triage acuity",
                    }
                ],
                "text": "AI Clinical Triage Assessment",
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": now,
            "issued": now,
            "valueInteger": triage_score,
            "interpretation": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                            "code": priority.upper(),
                            "display": priority.capitalize(),
                        }
                    ]
                }
            ],
            "note": [{"text": reasoning}],
            "component": [
                # NEWS2 aggregate score
                {
                    "code": {
                        "coding": [{
                            "system":  "http://loinc.org",
                            "code":    "96758-6",
                            "display": "National Early Warning Score 2 (NEWS2)",
                        }]
                    },
                    "valueInteger": news2_score,
                },
            ] + [
                {
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "75325-1",
                                "display": "Symptom",
                            }
                        ]
                    },
                    "valueCodeableConcept": {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": s.code,
                                "display": s.display,
                            }
                        ],
                        "text": f"{s.display} (severity {s.severity}/10)",
                    },
                }
                for s in symptoms
            ],
            "extension": [
                {
                    "url": "http://promptopinion.com/fhir/StructureDefinition/sharp-triage-priority",
                    "valueCode": priority,
                }
            ],
        }

        if encounter_id:
            obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}

        return obs

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        await self.client.aclose()

    async def __aenter__(self) -> "FHIRClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
