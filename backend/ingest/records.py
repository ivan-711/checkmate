"""Source record drafts: what the store writes. Ids are derived, not minted, so the same input
always yields the same record id and loading twice adds nothing (idempotent ingest).

Two renderers turn an Identity into a payload of the right kind: an ER FHIR Patient (with its
four parsed clinical resource lists) or a Clinic CSV row (with its clinical rows). The draft's
identity is then read back from the rendered payload by the same loaders the sample goes
through, so the normalized record can never carry a value the raw payload does not show.

Nothing in a rendered payload may tie two variants of one person together except what the
taxonomy row changed: the Synthea person id, narrative and extensions are dropped, identity
documents (SSN, licence, passport) are dropped, every clinical resource id is re-minted per
record, and display strings that echo the name are rewritten to the rendered name.
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
MRN_SYSTEM = "http://hospital.smarthealthit.org"
IDENTIFIER_TYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0203"
# Patient fields an ER registration carries. Everything else Synthea writes (text narrative with
# the person seed, race/ethnicity/birthsex/birthplace/DALY extensions, meta, SS/DL/PPN) is dropped.
PATIENT_KEPT_FIELDS = ("maritalStatus", "multipleBirthBoolean", "multipleBirthInteger", "communication")
FHIR_CLINICAL_LISTS = ("allergyIntolerances", "medicationRequests", "encounters", "medications")
# Keys whose value is a reference-with-display to the patient (the only place the name echoes).
PATIENT_REFERENCE_KEYS = ("subject", "patient")
# Columns that are never part of a clinic export (identity documents and geocoding).
CLINIC_DROPPED_COLUMNS = ("SSN", "DRIVERS", "PASSPORT", "LAT", "LON", "HEALTHCARE_EXPENSES", "HEALTHCARE_COVERAGE", "INCOME")
CSV_CLINICAL_LISTS = ("allergies", "medications", "encounters")
CSV_ENCOUNTER_ID_COLUMNS = ("ID", "ENCOUNTER")
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


def _remap_ids(payload: dict, id_map: dict[str, str]) -> dict:
    """One textual pass: every occurrence of an old id (person id, resource ids, references) becomes the new one."""
    text = json.dumps(payload, ensure_ascii=False)
    for old, new in id_map.items():
        text = text.replace(old, new)
    return json.loads(text)


def _per_record_id(record_uuid: str, old: str) -> str:
    return str(uuid5(RECORD_NAMESPACE, f"{record_uuid}:{old}"))


def display_name(identity: Identity) -> str:
    return " ".join(part for part in (identity.given, identity.family) if part)


def render_fhir_patient(identity: Identity, base: dict, local_id: str) -> dict:
    patient: dict = {
        "resourceType": "Patient",
        "id": str(record_id(SOURCE_ER_FHIR, local_id)),
        # the record's own MRN only; it is the source_local_id and never shared between records
        "identifier": [{"type": {"coding": [{"system": IDENTIFIER_TYPE_SYSTEM, "code": "MR", "display": "Medical Record Number"}]},
                        "system": MRN_SYSTEM, "value": local_id}],
    }
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


def _relabel_patient_references(resources: list[dict], name: str) -> None:
    for resource in resources:
        for key in PATIENT_REFERENCE_KEYS:
            ref = resource.get(key)
            if isinstance(ref, dict) and "display" in ref:
                ref["display"] = name


def fhir_draft(identity: Identity, bundle: FhirPatientBundle, local_id: str, is_constructed: bool = False) -> SourceRecordDraft:
    record_uuid = str(record_id(SOURCE_ER_FHIR, local_id))
    payload = {
        "patient": render_fhir_patient(identity, bundle.patient, local_id),
        "allergyIntolerances": bundle.allergies,
        "medicationRequests": bundle.medication_requests,
        "encounters": bundle.encounters,
        "medications": bundle.medications,
    }
    # Re-mint every clinical resource id per record so two variants of one person share none.
    id_map = {res["id"]: _per_record_id(record_uuid, res["id"]) for key in FHIR_CLINICAL_LISTS for res in payload[key] if res.get("id")}
    id_map[bundle.patient_id] = record_uuid
    payload = _remap_ids(payload, id_map)
    for key in FHIR_CLINICAL_LISTS:
        _relabel_patient_references(payload[key], display_name(identity))
    return SourceRecordDraft(SOURCE_ER_FHIR, local_id, payload, identity_from_patient(payload["patient"]), is_constructed)


def canonical_headers(row: dict[str, str]) -> dict[str, str]:
    """UPPERCASE keys, so a mixed-case header (``Last`` beside ``LAST``) cannot keep a value the
    renderer meant to replace or drop."""
    out: dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        upper = key.strip().upper()
        if upper not in out or not out[upper]:
            out[upper] = value
    return out


def render_csv_row(identity: Identity, base: dict[str, str], local_id: str, include_phone: bool) -> dict[str, str]:
    """A clinic-shaped row: Synthea columns minus identity documents, DOB as MM/DD/YYYY, phone sometimes."""
    row = {k: v for k, v in canonical_headers(base).items() if k not in CLINIC_DROPPED_COLUMNS}
    row["ID"] = local_id
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
    # Encounter ids are shared across the clinical rows of one person; re-mint them per record.
    id_map = {value: _per_record_id(local_id, value)
              for key in CSV_CLINICAL_LISTS for row in payload[key]
              for col, value in row.items() if col and col.upper() in CSV_ENCOUNTER_ID_COLUMNS and value}
    id_map[patient.patient_id] = local_id
    payload = _remap_ids(payload, id_map)
    return SourceRecordDraft(SOURCE_CLINIC_CSV, local_id, payload, identity_from_row(payload["patient"]), is_constructed)


def plain_fhir_draft(bundle: FhirPatientBundle) -> SourceRecordDraft:
    """The sample bundle as-is (local id = Synthea id); used by loader tests and ad-hoc loads."""
    return fhir_draft(bundle.identity, bundle, bundle.patient_id)


def plain_csv_draft(patient: CsvPatient) -> SourceRecordDraft:
    return csv_draft(patient.identity, patient, patient.patient_id, include_phone=True)
