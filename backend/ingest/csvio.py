"""S1 loader for the Synthea CSV export: patients, allergies, medications, encounters.

The Nov 2021 sample's headers are UPPERCASE (``FIRST``, ``LAST``, ``BIRTHDATE``, ``ZIP``), not the
Title case the data plan assumed, so lookups here are case-insensitive. The same reader accepts
the clinic rows the corruptor renders (same columns, optional ``PHONE``, DOB as MM/DD/YYYY).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from backend.core.normalize import strip_synthea_digits
from backend.ingest.normalize import Identity

CSV_FILES = ("patients", "allergies", "medications", "encounters")
PATIENT_COLUMN = "patient"


@dataclass
class CsvPatient:
    patient_id: str
    identity: Identity
    row: dict[str, str]
    allergies: list[dict[str, str]] = field(default_factory=list)
    medications: list[dict[str, str]] = field(default_factory=list)
    encounters: list[dict[str, str]] = field(default_factory=list)


def _lower(row: dict[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in row.items() if k is not None}


def _value(row: dict[str, str], key: str) -> str | None:
    value = row.get(key)
    return value.strip() if value and value.strip() else None


def identity_from_row(row: dict[str, str]) -> Identity:
    """Digits stripped first; ``PHONE`` is absent in Synthea's own export and optional in clinic rows."""
    r = _lower(row)
    return Identity(
        given=strip_synthea_digits(_value(r, "first")),
        middle=strip_synthea_digits(_value(r, "middle")),
        family=strip_synthea_digits(_value(r, "last")),
        prefix=_value(r, "prefix"),
        suffix=_value(r, "suffix"),
        maiden=strip_synthea_digits(_value(r, "maiden")),
        birth_date=_value(r, "birthdate"),
        sex=_value(r, "gender"),
        phone=_value(r, "phone"),
        address_line=_value(r, "address"),
        city=_value(r, "city"),
        state=_value(r, "state"),
        postal_code=_value(r, "zip"),
        language=None,
        mother_maiden=None,
    )


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _group_by_patient(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    if not rows:
        return grouped
    column = next((k for k in rows[0] if k and k.lower() == PATIENT_COLUMN), None)
    if column is None:
        return grouped
    for row in rows:
        if row.get(column):
            grouped[row[column]].append(row)
    return grouped


def read_csv_dir(csv_dir: Path, patient_ids: set[str] | None = None) -> dict[str, CsvPatient]:
    """Patients keyed by Synthea id, each with their own clinical rows. ``patient_ids`` limits the
    result to the FHIR cohort (the CSV sample also carries deceased patients the FHIR zip lacks)."""
    patients: dict[str, CsvPatient] = {}
    for row in read_rows(csv_dir / "patients.csv"):
        pid = _lower(row).get("id")
        if not pid or (patient_ids is not None and pid not in patient_ids):
            continue
        patients[pid] = CsvPatient(patient_id=pid, identity=identity_from_row(row), row=row)
    for name in ("allergies", "medications", "encounters"):
        path = csv_dir / f"{name}.csv"
        if not path.exists():
            continue
        for pid, rows in _group_by_patient(read_rows(path)).items():
            if pid in patients:
                setattr(patients[pid], name, rows)
    return patients
