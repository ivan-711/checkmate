"""S1 loader for Synthea FHIR R4 bundles: Patient, AllergyIntolerance, MedicationRequest, Encounter
only (ADR-004). Every other resource type in the bundle is dropped unread.

Field paths were checked against the Nov 2021 sample on 2026-10-17 (transaction bundles,
``fullUrl = urn:uuid:<id>``, phone ``555-NNN-NNNN``, language under ``communication[0]``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from backend.core.normalize import strip_synthea_digits
from backend.ingest.normalize import Identity

PARSED_RESOURCE_TYPES = ("Patient", "AllergyIntolerance", "MedicationRequest", "Encounter")
MOTHERS_MAIDEN_URL = "http://hl7.org/fhir/StructureDefinition/patient-mothersMaidenName"
# The two non-patient files shipped in the sample's fhir/ folder.
NON_PATIENT_PREFIXES = ("hospitalInformation", "practitionerInformation")


@dataclass
class FhirPatientBundle:
    patient_id: str
    identity: Identity
    patient: dict
    allergies: list[dict] = field(default_factory=list)
    medication_requests: list[dict] = field(default_factory=list)
    encounters: list[dict] = field(default_factory=list)
    medications: list[dict] = field(default_factory=list)  # Medication resources an order points at


def iter_bundle_paths(fhir_dir: Path) -> list[Path]:
    return sorted(p for p in fhir_dir.glob("*.json") if not p.name.startswith(NON_PATIENT_PREFIXES))


def load_bundle(path: Path) -> FhirPatientBundle:
    with path.open("rb") as fh:
        return parse_bundle(json.load(fh))


def _official_name(patient: dict) -> dict:
    names = patient.get("name") or []
    for name in names:
        if name.get("use") == "official":
            return name
    return names[0] if names else {}


def _maiden_name(patient: dict) -> str | None:
    for name in patient.get("name") or []:
        if name.get("use") == "maiden":
            return name.get("family")
    return None


def _first(values: list | None) -> str | None:
    return values[0] if values else None


def _phone(patient: dict) -> str | None:
    for telecom in patient.get("telecom") or []:
        if telecom.get("system") == "phone" and telecom.get("value"):
            return telecom["value"]
    return None


def _language(patient: dict) -> str | None:
    communication = patient.get("communication") or []
    if not communication:
        return None
    coding = (communication[0].get("language") or {}).get("coding") or []
    return coding[0].get("code") if coding else None


def _mothers_maiden(patient: dict) -> str | None:
    for ext in patient.get("extension") or []:
        if ext.get("url") == MOTHERS_MAIDEN_URL:
            return ext.get("valueString")
    return None


def identity_from_patient(patient: dict) -> Identity:
    """Digits are stripped here, before anything else sees the name (architecture §3 S1)."""
    name = _official_name(patient)
    given = name.get("given") or []
    address = _first(patient.get("address")) or {}
    return Identity(
        given=strip_synthea_digits(_first(given)),
        middle=strip_synthea_digits(given[1]) if len(given) > 1 else None,
        family=strip_synthea_digits(name.get("family")),
        prefix=_first(name.get("prefix")),
        suffix=_first(name.get("suffix")),
        maiden=strip_synthea_digits(_maiden_name(patient)),
        birth_date=patient.get("birthDate"),
        sex=patient.get("gender"),
        phone=_phone(patient),
        address_line=_first(address.get("line")),
        city=address.get("city"),
        state=address.get("state"),
        postal_code=address.get("postalCode"),
        language=_language(patient),
        mother_maiden=strip_synthea_digits(_mothers_maiden(patient)),
    )


def parse_bundle(bundle: dict) -> FhirPatientBundle:
    by_type: dict[str, list[dict]] = {t: [] for t in PARSED_RESOURCE_TYPES}
    medications_by_url: dict[str, dict] = {}
    for entry in bundle.get("entry") or []:
        resource = entry.get("resource") or {}
        rtype = resource.get("resourceType")
        if rtype in by_type:
            by_type[rtype].append(resource)
        elif rtype == "Medication" and entry.get("fullUrl"):
            medications_by_url[entry["fullUrl"]] = resource
    if len(by_type["Patient"]) != 1:
        raise ValueError(f"expected exactly one Patient in the bundle, found {len(by_type['Patient'])}")
    patient = by_type["Patient"][0]
    if not patient.get("id"):
        raise ValueError("Patient has no id")
    # Some orders use medicationReference instead of an inline code; keep the referenced resource.
    referenced = [
        medications_by_url[ref]
        for ref in ((mr.get("medicationReference") or {}).get("reference") for mr in by_type["MedicationRequest"])
        if ref in medications_by_url
    ]
    return FhirPatientBundle(
        patient_id=patient["id"],
        identity=identity_from_patient(patient),
        patient=patient,
        allergies=by_type["AllergyIntolerance"],
        medication_requests=by_type["MedicationRequest"],
        encounters=by_type["Encounter"],
        medications=referenced,
    )
