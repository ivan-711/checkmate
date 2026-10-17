import json

from backend.ingest.csvio import identity_from_row, read_csv_dir
from backend.ingest.fhir import iter_bundle_paths, parse_bundle
from backend.ingest.records import (
    SOURCE_CLINIC_CSV,
    SOURCE_ER_FHIR,
    csv_draft,
    fhir_draft,
    plain_csv_draft,
    plain_fhir_draft,
    record_id,
)
from backend.tests.ingest.conftest import FIXTURES, PATIENT_A, PATIENT_B


def test_fhir_parses_only_the_four_resource_types(bundles):
    a = bundles[PATIENT_A]
    assert (len(a.allergies), len(a.medication_requests), len(a.encounters)) == (1, 1, 1)
    assert a.patient["resourceType"] == "Patient"
    assert [m["code"]["coding"][0]["code"] for m in a.medications] == ["308192"]  # referenced Medication followed
    text = json.dumps(plain_fhir_draft(a).raw_payload)
    assert "Observation" not in text and "Condition" not in text


def test_fhir_identity_strips_digits_first_and_reads_the_documented_paths(bundles):
    ident = bundles[PATIENT_A].identity
    assert (ident.given, ident.middle, ident.family) == ("José", "Luis", "Núñez-García")
    assert ident.prefix == "Mr." and ident.suffix is None
    assert ident.birth_date == "1990-03-07" and ident.sex == "male"
    assert ident.phone == "555-123-4567"
    assert (ident.address_line, ident.city, ident.state, ident.postal_code) == ("857 Kling Arcade", "Worcester", "MA", "01604")
    assert ident.language == "es"
    assert ident.mother_maiden == "Isabela de Anda"
    b = bundles[PATIENT_B].identity
    assert b.maiden == "Jones" and b.postal_code is None and b.language == "en-US"


def test_bundle_paths_skip_the_two_information_files(tmp_path):
    for name in ("x_1.json", "hospitalInformation1.json", "practitionerInformation1.json"):
        (tmp_path / name).write_text("{}")
    assert [p.name for p in iter_bundle_paths(tmp_path)] == ["x_1.json"]


def test_parse_bundle_requires_one_patient():
    try:
        parse_bundle({"entry": []})
    except ValueError as exc:
        assert "Patient" in str(exc)
    else:
        raise AssertionError("a bundle without a Patient must be rejected")


def test_csv_reader_restricts_to_cohort_and_groups_clinical_rows(csv_patients):
    assert set(csv_patients) == {PATIENT_A, PATIENT_B}  # the deceased third row is outside the FHIR cohort
    a = csv_patients[PATIENT_A]
    assert (len(a.allergies), len(a.medications), len(a.encounters)) == (1, 1, 1)
    assert a.allergies[0]["CODE"] == "7984"
    assert (a.identity.given, a.identity.family, a.identity.sex, a.identity.postal_code) == ("José", "Núñez-García", "M", "01604")
    assert csv_patients[PATIENT_B].identity.postal_code is None
    assert read_csv_dir(FIXTURES / "csv")[ "cccccccc-0000-4000-8000-000000000001"].identity.given == "Dora"


def test_csv_identity_accepts_clinic_rows_with_phone_and_us_dates():
    ident = identity_from_row({"FIRST": "Ana1", "LAST": "Ruiz2", "BIRTHDATE": "07/03/1985", "GENDER": "F", "PHONE": "555-000-1111", "ZIP": ""})
    assert (ident.given, ident.family, ident.birth_date, ident.phone, ident.postal_code) == ("Ana", "Ruiz", "07/03/1985", "555-000-1111", None)


def test_drafts_carry_the_right_kind_and_hide_the_synthea_id(bundles, csv_patients):
    a = bundles[PATIENT_A]
    er = fhir_draft(a.identity, a, "ER-TEST1")
    cl = csv_draft(a.identity, csv_patients[PATIENT_A], "CL-TEST1", include_phone=True)
    assert (er.source_system, er.kind.value) == (SOURCE_ER_FHIR, "FHIR_PATIENT")
    assert (cl.source_system, cl.kind.value) == (SOURCE_CLINIC_CSV, "CSV_ROW")
    assert er.id == record_id(SOURCE_ER_FHIR, "ER-TEST1") and er.id != cl.id
    for draft in (er, cl):
        assert PATIENT_A not in json.dumps(draft.raw_payload)
    assert er.raw_payload["patient"]["identifier"][0]["value"] == "ER-TEST1"
    assert "SSN" not in cl.raw_payload["patient"] and cl.raw_payload["patient"]["PHONE"] == "555-123-4567"
    assert cl.raw_payload["patient"]["BIRTHDATE"] == "03/07/1990"
    assert cl.raw_payload["allergies"][0]["PATIENT"] == "CL-TEST1"
    assert plain_csv_draft(csv_patients[PATIENT_B]).raw_payload["patient"].get("PHONE") is None


def test_same_input_same_hash(bundles):
    a = bundles[PATIENT_A]
    assert plain_fhir_draft(a).sha256 == plain_fhir_draft(a).sha256
    assert plain_fhir_draft(a).sha256 != plain_fhir_draft(bundles[PATIENT_B]).sha256
