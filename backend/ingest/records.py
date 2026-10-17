"""Source record drafts: what the store writes. Ids are derived, not minted, so the same input
always yields the same record id and loading twice adds nothing (idempotent ingest).

Two renderers turn an Identity into a payload of the right kind: an ER FHIR Patient (with its
four parsed clinical resource lists) or a Clinic CSV row (with its clinical rows). The draft's
identity is then read back from the rendered payload by the same loaders the sample goes
through, so the normalized record can never carry a value the raw payload does not show.

The Synthea person id, narrative and extensions are the hidden truth (evaluation plan §3): the
Patient is rebuilt from a whitelist and the person id is replaced everywhere by the MRN.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID, uuid5

from backend.ingest.csvio import CsvPatient, identity_from_row
from backend.ingest.fhir import MOTHERS_MAIDEN_URL, FhirPatientBundle, identity_from_patient
from backend.ingest.normalize import Identity, parse_date
from contracts.models.common import SourceKind

SOURCE_ER_FHIR = "ER_FHIR"
SOURCE_CLINIC_CSV = "CLINIC_CSV"
KIND_FOR_SOURCE = {SOURCE_ER_FHIR: SourceKind.FHIR_PATIENT, SOURCE_CLINIC_CSV: SourceKind.CSV_ROW}

# Fixed namespace so record ids are a pure function of (source_system, source_local_id).
RECORD_NAMESPACE = UUID("6f1c2a4e-7b3d-4e5f-9a1b-2c3d4e5f6a7b")
MR_IDENTIFIER_CODE = "MR"
SS_IDENTIFIER_CODE = "SS"
# Patient fields an ER registration carries. Everything else Synthea writes (text narrative with
# the person seed, race/ethnicity/birthsex/birthplace/DALY extensions, meta) is dropped.
PATIENT_KEPT_FIELDS = ("maritalStatus", "multipleBirthBoolean", "multipleBirthInteger", "communication")
# Columns that are never part of a clinic export (identity documents and geocoding).
CLINIC_DROPPED_COLUMNS = ("SSN", "DRIVERS", "PASSPORT", "LAT", "LON", "HEALTHCARE_EXPENSES", "HEALTHCARE_COVERAGE", "INCOME")
CSV_SEX_CODES = {"male": "M", "female": "F"}


def record_id(source_system: str, source_local_id: str) -> UUID:
    return uuid5(RECORD_NAMESPACE, f"{source_system}:{source_local_id}")


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_sha256(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceRecordDraft:
    source_system: str
    source_local_id: str
    raw_payload: dict
    identity: Identity  # always derived from raw_payload (see fhir_draft / csv_draft)
    is_constructed: bool = False

    @property
    def id(self) -> UUID:
        return record_id(self.source_system, self.source_local_id)

    @property
    def kind(self) -> SourceKind:
        return KIND_FOR_SOURCE[self.source_system]

    @property
    def sha256(self) -> str:
        return payload_sha256(self.raw_payload)


def _replace_person_id(payload: dict, old: str, new: str) -> dict:
    """Every reference (subject, patient, PATIENT column) carries the Synthea id; swap it in one pass."""
    return json.loads(json.dumps(payload, ensure_ascii=False).replace(old, new))


def _identifiers(base: dict, local_id: str) -> list[dict]:
    """MR becomes the per-source MRN; SS is kept (it is not a feature); the Synthea id is dropped."""
    kept = []
    for ident in base.get("identifier") or []:
        codings = (ident.get("type") or {}).get("coding") or []
        codes = {c.get("code") for c in codings}
        if MR_IDENTIFIER_CODE in codes:
            kept.append({**ident, "value": local_id})
        elif SS_IDENTIFIER_CODE in codes:
            kept.append(ident)
    return kept


def render_fhir_patient(identity: Identity, base: dict, local_id: str) -> dict:
    patient: dict = {"resourceType": "Patient", "id": str(record_id(SOURCE_ER_FHIR, local_id)), "identifier": _identifiers(base, local_id)}
    for key in PATIENT_KEPT_FIELDS:
        if key in base:
            patient[key] = base[key]
    if identity.mother_maiden:
        patient["extension"] = [{"url": MOTHERS_MAIDEN_URL, "valueString": identity.mother_maiden}]

    name: dict = {"use": "official"}
    if identity.family:
        name["family"] = identity.family
    given = [g for g in (identity.given, identity.middle) if g]
    if given:
        name["given"] = given
    if identity.prefix:
        name["prefix"] = [identity.prefix]
    if identity.suffix:
        name["suffix"] = [identity.suffix]
    patient["name"] = [name] + ([{"use": "maiden", "family": identity.maiden}] if identity.maiden else [])

    if identity.phone:
        patient["telecom"] = [{"system": "phone", "value": identity.phone, "use": "home"}]
    if identity.address_line or identity.city or identity.postal_code:
        address = {k: v for k, v in (("city", identity.city), ("state", identity.state), ("postalCode", identity.postal_code), ("country", "US")) if v}
        if identity.address_line:
            address["line"] = [identity.address_line]
        patient["address"] = [address]
    parsed_dob = parse_date(identity.birth_date)
    if identity.birth_date:
        patient["birthDate"] = parsed_dob.isoformat() if parsed_dob else identity.birth_date
    if identity.sex:
        patient["gender"] = identity.sex
    return patient


def fhir_draft(identity: Identity, bundle: FhirPatientBundle, local_id: str, is_constructed: bool = False) -> SourceRecordDraft:
    payload = {
        "patient": render_fhir_patient(identity, bundle.patient, local_id),
        "allergyIntolerances": bundle.allergies,
        "medicationRequests": bundle.medication_requests,
        "encounters": bundle.encounters,
        "medications": bundle.medications,
    }
    payload = _replace_person_id(payload, bundle.patient_id, str(record_id(SOURCE_ER_FHIR, local_id)))
    return SourceRecordDraft(SOURCE_ER_FHIR, local_id, payload, identity_from_patient(payload["patient"]), is_constructed)


def render_csv_row(identity: Identity, base: dict[str, str], local_id: str, include_phone: bool) -> dict[str, str]:
    """A clinic-shaped row: Synthea columns minus identity documents, DOB as MM/DD/YYYY, phone sometimes."""
    row = {k: v for k, v in base.items() if k.upper() not in CLINIC_DROPPED_COLUMNS}
    row["Id"] = local_id
    parsed_dob = parse_date(identity.birth_date)
    row.update({
        "BIRTHDATE": parsed_dob.strftime("%m/%d/%Y") if parsed_dob else (identity.birth_date or ""),
        "PREFIX": identity.prefix or "",
        "FIRST": identity.given or "",
        "MIDDLE": identity.middle or "",
        "LAST": identity.family or "",
        "SUFFIX": identity.suffix or "",
        "MAIDEN": identity.maiden or "",
        "GENDER": CSV_SEX_CODES.get((identity.sex or "").lower(), identity.sex or ""),
        "ADDRESS": identity.address_line or "",
        "CITY": identity.city or "",
        "STATE": identity.state or "",
        "ZIP": identity.postal_code or "",
    })
    if include_phone and identity.phone:
        row["PHONE"] = identity.phone
    else:
        row.pop("PHONE", None)
    return row


def csv_draft(identity: Identity, patient: CsvPatient, local_id: str, include_phone: bool, is_constructed: bool = False) -> SourceRecordDraft:
    payload = {
        "patient": render_csv_row(identity, patient.row, local_id, include_phone),
        "allergies": patient.allergies,
        "medications": patient.medications,
        "encounters": patient.encounters,
    }
    payload = _replace_person_id(payload, patient.patient_id, local_id)
    return SourceRecordDraft(SOURCE_CLINIC_CSV, local_id, payload, identity_from_row(payload["patient"]), is_constructed)


def plain_fhir_draft(bundle: FhirPatientBundle) -> SourceRecordDraft:
    """The sample bundle as-is (local id = Synthea id); used by loader tests and ad-hoc loads."""
    return fhir_draft(bundle.identity, bundle, bundle.patient_id)


def plain_csv_draft(patient: CsvPatient) -> SourceRecordDraft:
    return csv_draft(patient.identity, patient, patient.patient_id, include_phone=True)
