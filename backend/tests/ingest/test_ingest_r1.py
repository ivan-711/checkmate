"""R1 reviewer tests for lane W1 (branch review/w1). Each test names the finding it covers; the
ones expected to fail on lane/w1 at c7ddf8a are marked in the docstring.

The builder's fixture bundles have no ``Encounter.subject.display``; the Nov 2021 sample has one on
every Encounter ("Mr. Abdul218 Harris789", the original name with Synthea's per-person digits), so
these tests add it to the fixture before drafting, the way the real sample arrives.
"""

from __future__ import annotations

import json
import random
import re

import pytest

from backend.ingest import corruptor as c
from backend.ingest.cli import load_sample
from backend.ingest.csvio import CsvPatient, read_csv_dir
from backend.ingest.fhir import parse_bundle
from backend.ingest.normalize import Identity
from backend.ingest.records import SOURCE_ER_FHIR, csv_draft, fhir_draft
from backend.ingest.store import ingest
from backend.tests.ingest.conftest import FIXTURES, PATIENT_A, PATIENT_B

# "Given123 Family456": a Synthea person tag. Never allowed in a stored payload.
DIGIT_NAME = re.compile(r"[A-Za-zÀ-ÿ'-]{2,}\d{1,3} [A-Za-zÀ-ÿ'-]{2,}\d{1,3}")


def _bundle_with_display(name: str) -> dict:
    """bundle_a with the sample's real shape: every Encounter carries subject.display."""
    bundle = json.loads((FIXTURES / "bundle_a.json").read_text())
    for entry in bundle["entry"]:
        if entry["resource"]["resourceType"] == "Encounter":
            entry["resource"]["subject"]["display"] = name
    return bundle


def _clone_cohort(bundles, csv_patients, n: int):
    """n entities cloned from the two fixtures with fresh ids. Unlike the builder's helper, the clones keep
    their clinical resources and rows, because that is where the shared-id leak lives."""
    cloned_bundles, cloned_csv = {}, {}
    sources = list(bundles.values())
    for i in range(n):
        src = sources[i % len(sources)]
        new_id = f"{i:08x}-0000-4000-8000-00000000c10e"
        resources = [src.patient, *src.encounters, *src.allergies, *src.medication_requests, *src.medications]
        entries = json.loads(
            json.dumps([{"fullUrl": f"urn:uuid:{r['id']}", "resource": r} for r in resources]).replace(
                src.patient_id, new_id
            )
        )
        cloned_bundles[new_id] = parse_bundle({"entry": entries})
        base_csv = csv_patients[src.patient_id]
        rows = {
            k: json.loads(json.dumps(getattr(base_csv, k)).replace(src.patient_id, new_id))
            for k in ("allergies", "medications", "encounters")
        }
        cloned_csv[new_id] = CsvPatient(new_id, base_csv.identity, {**base_csv.row, "Id": new_id}, **rows)
    return cloned_bundles, cloned_csv


# ---- finding 1 (blocking): the ER payload's clinical resources carry the original digit name ----


def test_er_clinical_resources_never_carry_the_original_name():
    """Expected to FAIL on lane/w1: fhir_draft rewrites the Patient but leaves Encounter.subject.display."""
    bundle = parse_bundle(_bundle_with_display("Mr. José45 Núñez-García77"))
    corrupted = c.edit_t1(bundle.identity, random.Random(3))[0]  # the registration desk misspelt the surname
    draft = fhir_draft(corrupted, bundle, "ER-LEAK1")
    clinical = json.dumps({k: v for k, v in draft.raw_payload.items() if k != "patient"}, ensure_ascii=False)
    assert not DIGIT_NAME.search(clinical), "Synthea's digit-tagged name survives in the clinical resources"
    assert "Núñez-García" not in clinical, "the uncorrupted surname is readable beside the corrupted one"


def test_loaded_er_payloads_reveal_no_origin_name_or_id(db, csv_patients):
    """Expected to FAIL on lane/w1. A truth-leak probe over the database: no stored ER payload may carry
    a digit-tagged name or the Synthea person id (evaluation plan §3, leakage)."""
    bundle = parse_bundle(_bundle_with_display("Mr. José45 Núñez-García77"))
    corpus = c.build_corpus(11, {PATIENT_A: bundle}, csv_patients)
    ingest(db, (rec.draft for rec in corpus.records))
    rows = db.execute("SELECT source_system, raw_payload::text FROM source_record").fetchall()
    assert rows
    for system, text in rows:
        assert PATIENT_A not in text
        assert not DIGIT_NAME.search(text), f"{system}: {DIGIT_NAME.search(text).group(0)!r}"


# ---- finding 2 (should-fix): within-system duplicates share every clinical resource id ----


def test_within_system_duplicates_do_not_share_clinical_resource_ids(bundles, csv_patients):
    """Expected to FAIL on lane/w1. 'Shares a clinical resource id' separates SAME from NOT_SAME
    perfectly for same-system pairs (134/134 vs 0/116 at seed 20261017)."""
    cloned_bundles, cloned_csv = _clone_cohort(bundles, csv_patients, 60)
    corpus = c.build_corpus(5, cloned_bundles, cloned_csv)
    by_id = {str(r.draft.id): r.draft for r in corpus.records}

    def resource_ids(draft) -> set[str]:
        if draft.source_system == SOURCE_ER_FHIR:
            return {
                r["id"]
                for key in ("encounters", "medicationRequests", "allergyIntolerances", "medications")
                for r in draft.raw_payload[key]
                if r.get("id")
            }
        return {r["Id"] for r in draft.raw_payload["encounters"] if r.get("Id")}

    same_system_pairs = [
        p for p in corpus.pairs if by_id[p["record_a_id"]].source_system == by_id[p["record_b_id"]].source_system
    ]
    assert same_system_pairs, "the cohort must produce within-system duplicates"
    shared = [
        p for p in same_system_pairs if resource_ids(by_id[p["record_a_id"]]) & resource_ids(by_id[p["record_b_id"]])
    ]
    assert not shared, f"{len(shared)} of {len(same_system_pairs)} same-system pairs share a clinical resource id"


# ---- finding 3 (should-fix): malformed bundles abort the whole load; duplicate ids collapse silently ----


def _write_raw_dir(tmp_path, extra: dict[str, str]):
    fhir, csv_dir = tmp_path / "fhir", tmp_path / "csv"
    fhir.mkdir(), csv_dir.mkdir()
    for name in ("patients", "allergies", "medications", "encounters"):
        (csv_dir / f"{name}.csv").write_text((FIXTURES / "csv" / f"{name}.csv").read_text())
    (fhir / "a_good.json").write_text((FIXTURES / "bundle_a.json").read_text())
    (fhir / "b_good.json").write_text((FIXTURES / "bundle_b.json").read_text())
    for name, text in extra.items():
        (fhir / name).write_text(text)
    return tmp_path


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("no_patient.json", json.dumps({"resourceType": "Bundle", "entry": []})),
        ("truncated.json", '{"resourceType":"Bundle","entry":['),
        (
            "patient_without_id.json",
            json.dumps({"entry": [{"resource": {"resourceType": "Patient", "name": [{"family": "X1"}]}}]}),
        ),
    ],
)
def test_one_malformed_bundle_does_not_abort_the_load(tmp_path, name, text):
    """Expected to FAIL on lane/w1 (KeyError / ValueError / JSONDecodeError escape load_sample)."""
    bundles, _ = load_sample(_write_raw_dir(tmp_path, {name: text}))
    assert set(bundles) == {PATIENT_A, PATIENT_B}, "the two good bundles load; the bad one is skipped"


def test_duplicate_patient_ids_are_not_silently_collapsed(tmp_path):
    """Expected to FAIL on lane/w1: a second file with the same Patient id overwrites the first without a word."""
    dup = json.loads((FIXTURES / "bundle_a.json").read_text())
    dup["entry"][0]["resource"]["birthDate"] = "1991-01-01"  # same id, different person data
    root = _write_raw_dir(tmp_path, {"zz_duplicate_of_a.json": json.dumps(dup)})
    with pytest.raises(Exception, match="(?i)duplicate|already"):
        load_sample(root)


def test_bundles_without_birthdate_or_name_still_load(tmp_path):
    """Gap coverage (expected to pass): a Patient with no birthDate or name is a record without those values."""
    bare = json.loads((FIXTURES / "bundle_b.json").read_text())
    bare["entry"][0]["resource"].pop("birthDate")
    bare["entry"][0]["resource"].pop("name")
    bare["entry"][0]["resource"]["id"] = "dddddddd-0000-4000-8000-000000000001"
    bundles, _ = load_sample(_write_raw_dir(tmp_path, {"d_bare.json": json.dumps(bare)}))
    ident = bundles["dddddddd-0000-4000-8000-000000000001"].identity
    assert ident.birth_date is None and ident.given is None and ident.family is None


# ---- hot blocks (architecture §3): placeholder values never form a block key, end to end ----


@pytest.mark.parametrize(
    ("identity", "forbidden_key_types"),
    [
        (
            Identity(given="Ana", family="Garcia", birth_date="1900-01-01", phone="555-123-4567", postal_code="01604"),
            {"DOB_EXACT", "DOB_DAY_MONTH_SWAP", "DMETA_FAMILY_BIRTH_YEAR"},
        ),
        (
            Identity(
                given="Unknown", family="Unknown", birth_date="1990-03-07", phone="555-123-4567", postal_code="01604"
            ),
            {"DMETA_FAMILY_BIRTH_YEAR", "ZIP5_FIRST_INITIAL"},
        ),
        (
            Identity(
                given="Baby Boy", family="Doe", birth_date="1990-03-07", phone="555-123-4567", postal_code="01604"
            ),
            {"DMETA_FAMILY_BIRTH_YEAR", "ZIP5_FIRST_INITIAL"},
        ),
        (
            Identity(given="Ana", family="Garcia", birth_date="1990-03-07", phone="555-555-5555", postal_code="01604"),
            {"PHONE_LAST7"},
        ),
        (
            Identity(given="Ana", family="Garcia", birth_date="1990-03-07", phone="617-555-0123", postal_code="01604"),
            {"PHONE_LAST7"},
        ),
        (
            Identity(given="Ana", family="Garcia", birth_date="1990-03-07", phone="000-000-0000", postal_code="01604"),
            {"PHONE_LAST7"},
        ),
        (
            Identity(given="Ana", family="Garcia", birth_date="1990-03-07", phone="555-123-4567", postal_code=""),
            {"ZIP5_FIRST_INITIAL"},
        ),
        (
            Identity(given="Ana", family="Garcia", birth_date="1990-03-07", phone="555-123-4567", postal_code="016"),
            {"ZIP5_FIRST_INITIAL"},
        ),
    ],
)
def test_placeholder_values_never_form_a_block_key_in_the_database(
    db, bundles, csv_patients, identity, forbidden_key_types
):
    """Gap coverage: the builder tests block_keys() in memory; this checks what lands in block_key through
    both renderers (the ER Patient and the clinic row) for each placeholder family of the hot-block rule.
    Key types are backend.core's (issue #10); the guard keeps a renamed type from passing vacuously."""
    from backend.core.block import KEY_TYPES

    assert forbidden_key_types <= set(KEY_TYPES)
    er = fhir_draft(identity, bundles[PATIENT_B], "ER-PH")
    cl = csv_draft(identity, csv_patients[PATIENT_B], "CL-PH", include_phone=True)
    ingest(db, [er, cl])
    rows = db.execute("SELECT key_type, key_value FROM block_key").fetchall()
    present = {key_type for key_type, _ in rows}
    assert not (present & forbidden_key_types), rows
    placeholder_values = {"1900-01-01", "5555555", "5550123", "0000000"}
    assert not {value for _, value in rows} & placeholder_values, rows


# ---- generator invariants the evaluation plan asks for ----


def test_corruption_rate_is_independent_of_label(bundles, csv_patients):
    """Evaluation plan §2: 'a test checks that corruption rate is independent of label'. Missing from the lane."""
    cloned_bundles, cloned_csv = _clone_cohort(bundles, csv_patients, 200)
    corpus = c.build_corpus(9, cloned_bundles, cloned_csv)
    family_of = {str(r.draft.id): r.family for r in corpus.records}
    rates = {}
    for label in (c.LABEL_SAME, c.LABEL_NOT_SAME):
        recs = {rid for p in corpus.pairs if p["label"] == label for rid in (p["record_a_id"], p["record_b_id"])}
        assert len(recs) >= 40, f"too few {label} records to compare"
        rates[label] = sum(family_of[r] != c.NO_EDIT for r in recs) / len(recs)
    assert abs(rates[c.LABEL_SAME] - rates[c.LABEL_NOT_SAME]) < 0.15, rates


def test_s3_keeps_a_particle_led_paternal_surname():
    """Expected to FAIL on lane/w1: 'de la Cruz López' minus the maternal surname is 'de la Cruz', not 'de'."""
    changed, _ = c.edit_s3(Identity(family="de la Cruz López"), random.Random(1))
    assert changed.family == "de la Cruz"


def test_l7_leaves_no_location_column_in_the_clinic_row(csv_patients, bundles):
    """Expected to FAIL on lane/w1: L7 blanks ADDRESS/CITY/STATE/ZIP but the clinic row still says COUNTY."""
    moved, _ = c.edit_l7(bundles[PATIENT_A].identity, random.Random(1))
    row = csv_draft(moved, csv_patients[PATIENT_A], "CL-L7", include_phone=True).raw_payload["patient"]
    assert not any(row.get(col) for col in ("ADDRESS", "CITY", "STATE", "ZIP", "COUNTY", "FIPS", "LAT", "LON")), row


def test_cohort_read_from_the_sample_dir_is_the_fhir_cohort(bundles):
    """Sanity for the tests above: the CSV reader restricted to the FHIR cohort keeps both fixture patients."""
    assert set(read_csv_dir(FIXTURES / "csv", patient_ids=set(bundles))) == {PATIENT_A, PATIENT_B}
