from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from backend.golden.survivorship import (
    RULE_CONFLICT,
    RULE_MAJORITY,
    RULE_MOST_FREQUENT,
    RULE_MOST_RECENT,
    MemberDemographics,
    golden_demographics,
)

T0 = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)


def m(i: int, minutes: int, **kw) -> MemberDemographics:
    base = {"given_name": "Ana", "family_name": "Acuna", "birth_date": date(1985, 7, 3), "sex": "FEMALE", "phone_e164": "+15555550100",
                "address_line": "100 Placeholder St", "zip5": "54311"}
    base.update(kw)
    return MemberDemographics(source_system=f"S{i}", source_local_id=f"L{i}", ingested_at=T0 + timedelta(minutes=minutes), **base)


def by_field(fields):
    return {f.field: f for f in fields}


def test_names_most_frequent_then_most_recent():
    g = by_field(golden_demographics([m(1, 0, given_name="Ana"), m(2, 1, given_name="Anna"), m(3, 2, given_name="ana")]))
    assert g["givenName"].value == "ana" and g["givenName"].rule == RULE_MOST_FREQUENT
    assert [a.value for a in g["givenName"].alternates] == ["Anna", "Ana"]
    assert g["givenName"].alternates[0].crosswalk.source_record_id == "L2"
    tie = by_field(golden_demographics([m(1, 0, family_name="Acuna"), m(2, 1, family_name="Acuña")]))
    assert tie["familyName"].value == "Acuña" and tie["familyName"].rule == RULE_MOST_RECENT
    assert tie["familyName"].crosswalk.source_record_id == "L2"


def test_dob_and_sex_majority_else_conflict_unresolved():
    g = by_field(golden_demographics([m(1, 0), m(2, 1, birth_date=date(1985, 3, 7)), m(3, 2)]))
    assert g["birthDate"].value == "1985-07-03" and g["birthDate"].rule == RULE_MAJORITY
    c = by_field(golden_demographics([m(1, 0), m(2, 1, birth_date=date(1985, 3, 7), sex="MALE")]))
    assert c["birthDate"].rule == RULE_CONFLICT and c["birthDate"].value is None
    assert sorted(a.value for a in c["birthDate"].alternates) == ["1985-03-07", "1985-07-03"]
    assert c["sex"].rule == RULE_CONFLICT and c["sex"].value is None
    assert c["birthDate"].crosswalk.source_record_id == "L2"


def test_phone_address_zip_most_recent():
    g = by_field(golden_demographics([m(1, 5, phone_e164="+15555550001", address_line="old"), m(2, 1, phone_e164="+15555550002")]))
    assert g["phone"].value == "+15555550001" and g["phone"].rule == RULE_MOST_RECENT and g["phone"].crosswalk.source_record_id == "L1"
    assert g["address"].value == "old" and g["zip5"].rule == RULE_MOST_RECENT


def test_missing_values_are_skipped_and_every_value_has_a_crosswalk():
    fields = golden_demographics([m(1, 0, phone_e164=None, address_line=None), m(2, 1, phone_e164=None, zip5="")])
    names = {f.field for f in fields}
    assert "phone" not in names and "address" in names and "zip5" in names
    for f in fields:
        assert f.crosswalk.source_system and f.crosswalk.source_record_id
        for a in f.alternates:
            assert a.crosswalk.source_record_id


def test_clinical_union_prefers_the_active_allergy_and_keeps_distinct_orders():
    from backend.golden.service import clinical_union
    from backend.tests.rule.test_bl_amox_01 import (
        clinic_member,
        csv_allergy_row,
        er_member,
        fhir_order,
    )
    member = clinic_member(allergies=[csv_allergy_row(stop="2020-01-01"), csv_allergy_row()])
    (allergy,) = [f for f in clinical_union([member]) if f.field == "allergy"]
    assert allergy.value["status"] == "active" and allergy.value["resourceId"] == "allergies.csv:1"
    reversed_member = clinic_member(allergies=[csv_allergy_row(), csv_allergy_row(stop="2020-01-01")])
    (allergy,) = [f for f in clinical_union([reversed_member]) if f.field == "allergy"]
    assert allergy.value["status"] == "active" and allergy.value["resourceId"] == "allergies.csv:0"
    second = fhir_order(); second["id"] = "mr-2"
    orders = [f for f in clinical_union([er_member(fhir_order(), second)]) if f.field == "activeMedicationOrder"]
    assert sorted(f.value["resourceId"] for f in orders) == ["MedicationRequest/mr-1", "MedicationRequest/mr-2"]
