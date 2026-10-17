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


def test_rendered_fhir_never_echoes_the_original_name_or_shares_clinical_ids(bundles):
    from dataclasses import replace

    a = bundles[PATIENT_A]
    changed = replace(a.identity, given="Pepe", family="Nunes")
    one = fhir_draft(changed, a, "ER-V1")
    two = fhir_draft(a.identity, a, "ER-V2")
    text = json.dumps(one.raw_payload, ensure_ascii=False)
    for original in ("Núñez", "Nunez", "José", "Jose", "Núñez-García77", "José45"):
        assert original not in text, original
    assert one.raw_payload["encounters"][0]["subject"]["display"] == "Pepe Nunes"
    assert one.raw_payload["encounters"][0]["subject"]["reference"] == f"urn:uuid:{one.id}"
    ids = lambda d: {r["id"] for k in ("allergyIntolerances", "medicationRequests", "encounters", "medications") for r in d.raw_payload[k]}
    assert ids(one) and not ids(one) & ids(two)  # re-minted per record
    original_ids = {r["id"] for r in a.allergies + a.medication_requests + a.encounters + a.medications}
    assert not ids(one) & original_ids
    # references inside the record still resolve: the order points at this record's encounter and medication
    mr = one.raw_payload["medicationRequests"][0]
    assert mr["encounter"]["reference"] == f"urn:uuid:{one.raw_payload['encounters'][0]['id']}"
    assert mr["medicationReference"]["reference"] == f"urn:uuid:{one.raw_payload['medications'][0]['id']}"


def test_variants_of_one_entity_share_no_identifier(bundles):
    a = bundles[PATIENT_A]
    one, two = fhir_draft(a.identity, a, "ER-V1"), fhir_draft(a.identity, a, "ER-V2")
    values = lambda d: {i["value"] for i in d.raw_payload["patient"]["identifier"]}
    assert values(one) == {"ER-V1"} and values(two) == {"ER-V2"}
    assert "999-11-1111" not in json.dumps(one.raw_payload)  # SSN, licence and passport are never rendered


def test_csv_variants_share_no_encounter_id_and_mixed_case_headers_cannot_leak(bundles, csv_patients):
    from dataclasses import replace

    a = bundles[PATIENT_A]
    base = csv_patients[PATIENT_A]
    one = csv_draft(a.identity, base, "CL-V1", include_phone=True)
    two = csv_draft(a.identity, base, "CL-V2", include_phone=True)
    enc = lambda d: {d.raw_payload["encounters"][0]["Id"], d.raw_payload["allergies"][0]["ENCOUNTER"]}
    assert len(enc(one)) == 1 and not enc(one) & enc(two)
    assert "aaaaaaaa-0000-4000-8000-000000000002" not in json.dumps(one.raw_payload)
    from backend.ingest.csvio import CsvPatient

    mixed = CsvPatient(PATIENT_A, base.identity, {"Id": PATIENT_A, "Last": "Núñez-García", "Phone": "555-123-4567", "BIRTHDATE": "1990-03-07"})
    draft = csv_draft(replace(a.identity, family="Nunes"), mixed, "CL-MIXED", include_phone=False)
    row = draft.raw_payload["patient"]
    assert row["LAST"] == "Nunes" and "Last" not in row and "Phone" not in row and "PHONE" not in row
    assert draft.identity.family == "Nunes" and draft.identity.phone is None
    assert "Núñez" not in json.dumps(draft.raw_payload, ensure_ascii=False)


def test_load_sample_counts_skipped_bundles_and_keeps_the_good_ones(tmp_path):
    from backend.ingest.cli import load_sample

    fhir, csv_dir = tmp_path / "fhir", tmp_path / "csv"
    fhir.mkdir(), csv_dir.mkdir()
    for name in ("patients", "allergies", "medications", "encounters"):
        (csv_dir / f"{name}.csv").write_text((FIXTURES / "csv" / f"{name}.csv").read_text())
    (fhir / "a.json").write_text((FIXTURES / "bundle_a.json").read_text())
    (fhir / "bad_json.json").write_text("{not json")
    (fhir / "no_id.json").write_text(json.dumps({"entry": [{"resource": {"resourceType": "Patient"}}]}))
    skipped: list[str] = []
    bundles, csv_patients = load_sample(tmp_path, skipped=skipped)
    assert set(bundles) == {PATIENT_A} and set(csv_patients) == {PATIENT_A}
    assert sorted(skipped) == ["bad_json.json", "no_id.json"]
