"""The constructed allergy/order overlay on the selected hero (Synthea data plan section 4, Selection 1-3).

Applied after selection; it touches clinical content only and keeps every identity field exactly as
selected. Placement, which everyone follows:

- the allergy lives in the Clinic CSV source as an ``allergies.csv``-shaped row (Synthea's column set
  plus a ``CONSTRUCTED`` column): a natural RxNorm 7984 row is kept, and a SEVERE anaphylaxis row is
  added only if no 7984 row is SEVERE; with no natural row, the allergy row itself is added;
- the order and the ER registration live in the ER FHIR source: a ``Patient`` (registered without the
  allergy history: no ``AllergyIntolerance``), an emergency ``Encounter`` and an active
  ``MedicationRequest`` for RxNorm 308192 authored after the allergy START, with a new id;
- every FHIR overlay resource carries ``meta.tag = urn:chartguard:provenance#constructed-scenario`` and
  ``scenario_manifest.json`` lists each item with the provenance sentence.

The writer is deterministic (fixed dates, uuid5 ids) so CI can regenerate and diff the directory.
W3a's loader reads it with ``CHECKMATE_HERO_SOURCE=corpus`` (``fhir/*.json`` and ``csv/``).
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from eval.harness.types import Record

PROVENANCE_SYSTEM = "urn:chartguard:provenance"
PROVENANCE_CODE = "constructed-scenario"
PROVENANCE_SENTENCE = "added by the ChartGuard team; not produced by Synthea"
OVERLAY_NAMESPACE = uuid.UUID("6f1b4a3e-2c7d-4d0a-9a6e-0f0e7a1a0000")  # new ids, never a Synthea id

ALLERGY_RXNORM = "7984"            # penicillin V; the rule treats it as penicillin-class
ALLERGY_DESCRIPTION = "penicillin V"
ANAPHYLAXIS_SNOMED = "39579001"
ORDER_RXNORM = "308192"
ORDER_DISPLAY = "Amoxicillin 500 MG Oral Tablet"
RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"
ALLERGY_START = "2024-03-02"       # the scenario timeline's allergy date
ORDER_AUTHORED_ON = "2026-10-17T18:00:00Z"  # after ALLERGY_START, the scenario's order time
ENCOUNTER_START = "2026-10-17T17:20:00Z"

# Synthea's allergies.csv writer (CSVExporter.exportAllergy) plus the overlay's CONSTRUCTED column
ALLERGY_COLUMNS = ("START", "STOP", "PATIENT", "ENCOUNTER", "CODE", "SYSTEM", "DESCRIPTION", "TYPE", "CATEGORY",
                   "REACTION1", "DESCRIPTION1", "SEVERITY1", "REACTION2", "DESCRIPTION2", "SEVERITY2", "CONSTRUCTED")
PATIENT_COLUMNS = ("Id", "BIRTHDATE", "DEATHDATE", "SSN", "DRIVERS", "PASSPORT", "PREFIX", "FIRST", "LAST", "SUFFIX",
                   "MAIDEN", "MARITAL", "RACE", "ETHNICITY", "GENDER", "BIRTHPLACE", "ADDRESS", "CITY", "STATE",
                   "COUNTY", "ZIP", "LAT", "LON", "HEALTHCARE_EXPENSES", "HEALTHCARE_COVERAGE", "PHONE")
CSV_GENDER = {"FEMALE": "F", "MALE": "M"}
FHIR_GENDER = {"FEMALE": "female", "MALE": "male"}

FHIR_FILE = "fhir/hero_er.json"
PATIENTS_FILE = "csv/patients.csv"
ALLERGIES_FILE = "csv/allergies.csv"
MANIFEST_FILE = "scenario_manifest.json"


@dataclass(frozen=True)
class OverlayRefs:
    """Ids the scenario export cites (timeline, alert card)."""

    clinic_patient_id: str
    er_patient_id: str
    order_id: str
    encounter_id: str
    allergy_resource_id: str
    order_resource_id: str


def _id(kind: str, entity_id: str) -> str:
    return str(uuid.uuid5(OVERLAY_NAMESPACE, f"{kind}:{entity_id}"))


def refs_for(entity_id: str) -> OverlayRefs:
    clinic_pid, order_id = _id("clinic-patient", entity_id), _id("order", entity_id)
    return OverlayRefs(
        clinic_patient_id=clinic_pid, er_patient_id=_id("er-patient", entity_id), order_id=order_id,
        encounter_id=_id("er-encounter", entity_id),
        allergy_resource_id=f"allergies.csv:{clinic_pid}:{ALLERGY_RXNORM}:{ALLERGY_START}",
        order_resource_id=f"MedicationRequest/{order_id}",
    )


def _tag() -> dict:
    return {"tag": [{"system": PROVENANCE_SYSTEM, "code": PROVENANCE_CODE}]}


def allergy_rows(patient_id: str, natural: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep natural rows (CONSTRUCTED false); add a 7984 SEVERE anaphylaxis row only when no 7984 row is SEVERE."""
    rows = [{**{c: "" for c in ALLERGY_COLUMNS}, **row, "CONSTRUCTED": "false"} for row in natural]
    penicillin = [r for r in rows if r.get("CODE") == ALLERGY_RXNORM]
    if any("SEVERE" in (r.get("SEVERITY1"), r.get("SEVERITY2")) for r in penicillin):
        return rows
    start = penicillin[0]["START"] if penicillin else ALLERGY_START
    rows.append({**{c: "" for c in ALLERGY_COLUMNS}, "START": start, "PATIENT": patient_id, "CODE": ALLERGY_RXNORM,
                 "SYSTEM": "RxNorm", "DESCRIPTION": ALLERGY_DESCRIPTION, "TYPE": "allergy", "CATEGORY": "medication",
                 "REACTION1": ANAPHYLAXIS_SNOMED, "DESCRIPTION1": "Anaphylaxis", "SEVERITY1": "SEVERE",
                 "CONSTRUCTED": "true"})
    return rows


def _csv(columns: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def clinic_patient_row(clinic: Record, patient_id: str) -> dict[str, str]:
    """The Clinic CSV identity exactly as selected (no field rewritten)."""
    row = {c: "" for c in PATIENT_COLUMNS}
    row.update(Id=patient_id, BIRTHDATE=clinic.get("birth_date") or "", FIRST=clinic.get("given_name") or "",
               LAST=clinic.get("family_name") or "", GENDER=CSV_GENDER.get(clinic.get("sex") or "", ""),
               ADDRESS=clinic.get("address_line") or "", ZIP=clinic.get("zip5") or "", PHONE=clinic.get("phone") or "")
    return row


def er_bundle(er: Record, refs: OverlayRefs) -> dict:
    """ER FHIR registration (identity exactly as selected) with the constructed order; no AllergyIntolerance."""
    patient_url, encounter_url = f"urn:uuid:{refs.er_patient_id}", f"urn:uuid:{refs.encounter_id}"
    patient: dict = {"resourceType": "Patient", "id": refs.er_patient_id, "meta": _tag(),
                     "name": [{"use": "official", "family": er.get("family_name"), "given": [er.get("given_name")]}],
                     "gender": FHIR_GENDER.get(er.get("sex") or "", "unknown"), "birthDate": er.get("birth_date")}
    if er.get("phone"):
        patient["telecom"] = [{"system": "phone", "value": er["phone"], "use": "home"}]
    if er.get("address_line") or er.get("zip5"):
        patient["address"] = [{"line": [er["address_line"]] if er.get("address_line") else [],
                               "postalCode": er.get("zip5"), "country": "US"}]
    display = f"{er.get('given_name')} {er.get('family_name')}"
    encounter = {"resourceType": "Encounter", "id": refs.encounter_id, "meta": _tag(), "status": "finished",
                 "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "EMER"},
                 "subject": {"reference": patient_url, "display": display},
                 "period": {"start": ENCOUNTER_START}}
    order = {"resourceType": "MedicationRequest", "id": refs.order_id, "meta": _tag(), "status": "active",
             "intent": "order",
             "medicationCodeableConcept": {"coding": [{"system": RXNORM_SYSTEM, "code": ORDER_RXNORM,
                                                       "display": ORDER_DISPLAY}], "text": ORDER_DISPLAY},
             "subject": {"reference": patient_url, "display": display}, "encounter": {"reference": encounter_url},
             "authoredOn": ORDER_AUTHORED_ON}
    return {"resourceType": "Bundle", "type": "transaction", "entry": [
        {"fullUrl": patient_url, "resource": patient},
        {"fullUrl": encounter_url, "resource": encounter},
        {"fullUrl": f"urn:uuid:{refs.order_id}", "resource": order},
    ]}


def write_overlay(out: Path, entity_id: str, er: Record, clinic: Record,
                  natural_allergies: list[dict[str, str]] | None = None) -> OverlayRefs:
    refs = refs_for(entity_id)
    (out / "fhir").mkdir(parents=True, exist_ok=True)
    (out / "csv").mkdir(parents=True, exist_ok=True)
    rows = allergy_rows(refs.clinic_patient_id, list(natural_allergies or []))
    (out / FHIR_FILE).write_text(json.dumps(er_bundle(er, refs), indent=2, ensure_ascii=False) + "\n")
    (out / PATIENTS_FILE).write_text(_csv(PATIENT_COLUMNS, [clinic_patient_row(clinic, refs.clinic_patient_id)]))
    (out / ALLERGIES_FILE).write_text(_csv(ALLERGY_COLUMNS, rows))
    constructed = [
        {"item": "ER registration without the allergy history (no AllergyIntolerance in the ER source)",
         "file": FHIR_FILE, "resource": f"Patient/{refs.er_patient_id}", "label": "constructed scenario",
         "provenance": PROVENANCE_SENTENCE},
        {"item": "ER emergency encounter", "file": FHIR_FILE, "resource": f"Encounter/{refs.encounter_id}",
         "label": "constructed scenario", "provenance": PROVENANCE_SENTENCE},
        {"item": f"active order RxNorm {ORDER_RXNORM} {ORDER_DISPLAY}, authoredOn {ORDER_AUTHORED_ON}",
         "file": FHIR_FILE, "resource": refs.order_resource_id, "label": "constructed scenario",
         "provenance": PROVENANCE_SENTENCE},
    ]
    constructed += [{"item": f"allergy row RxNorm {r['CODE']} ({r['DESCRIPTION']}), reaction {r['DESCRIPTION1']} "
                             f"{r['SEVERITY1']}, START {r['START']}",
                     "file": ALLERGIES_FILE, "resource": refs.allergy_resource_id, "label": "constructed scenario",
                     "provenance": PROVENANCE_SENTENCE} for r in rows if r["CONSTRUCTED"] == "true"]
    manifest = {
        "heroEntityId": entity_id,
        "provenance": PROVENANCE_SENTENCE,
        "metaTag": {"system": PROVENANCE_SYSTEM, "code": PROVENANCE_CODE},
        "placement": {"allergy": "Clinic CSV (allergies.csv row)", "order": "ER FHIR (MedicationRequest)",
                      "erAllergyHistory": "absent by construction"},
        "identity": "identity fields exactly as selected by data/hero_select.py; the overlay touches clinical content only",
        "naturalAllergyRowsKept": sum(1 for r in rows if r["CONSTRUCTED"] == "false"),
        "constructed": constructed,
        "wording": "the allergy reveal is a constructed demonstration, not a measured outcome",
    }
    (out / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return refs
