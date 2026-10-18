"""Ingest's hand-off into backend.core.normalize (issue #10): ingest owns the fielded Identity and
the date it re-renders; folding, phones, ZIPs and placeholders are core's and tested there."""

from datetime import date

import pytest

from backend.core.normalize import normalize_record, strip_synthea_digits
from backend.ingest.normalize import Identity, identity_fields, normalize_identity, parse_date

JOSE = Identity(
    given="José",
    family="Núñez-García",
    birth_date="1990-03-07",
    sex="male",
    phone="555-123-4567",
    address_line="  857  Kling Arcade ",
    postal_code="01604",
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ahmed109", "Ahmed"),
        ("O'Reilly797", "O'Reilly"),
        ("Isabela97 Vásquez905", "Isabela Vásquez"),
        ("de Anda905", "de Anda"),
        ("Smith", "Smith"),
        ("123", None),
        (None, None),
    ],
)
def test_loaders_strip_synthea_digits_with_cores_rule(raw, expected):
    assert strip_synthea_digits(raw) == expected


def test_normalize_identity_is_cores_normalize_record():
    assert normalize_identity(JOSE) == normalize_record(identity_fields(JOSE))


def test_accents_case_and_hyphen_follow_core():
    n = normalize_identity(JOSE)
    assert (n.given_name, n.family_name) == ("josé", "núñez garcía")  # case-folded, accents kept
    assert (n.given_name_folded, n.family_name_folded) == ("jose", "nunez garcia")
    assert n.family_tokens == ("nunez", "garcia")
    assert (n.birth_year, n.birth_month, n.birth_day) == (1990, 3, 7)
    assert n.sex == "M" and n.phone_e164 == "+15551234567" and n.zip5 == "01604"
    assert n.address_line == "857 kling arcade"


def test_clinic_codes_and_missing_values():
    n = normalize_identity(Identity(given="Robert", family="Smith", sex="F", birth_date="11/02/1985"))
    assert n.sex == "F" and n.birth_date == date(1985, 11, 2)
    assert n.phone_e164 is None and n.zip5 is None and n.address_line is None


def test_generation_suffix_reaches_core_and_professional_suffix_does_not():
    assert normalize_identity(Identity(given="Robert", family="Smith", suffix="Jr.")).suffix == "JR"
    assert normalize_identity(Identity(given="Robert", family="Smith", suffix="MD")).suffix is None


@pytest.mark.parametrize(
    "identity",
    [JOSE, Identity(given="Robert", family="Smith", suffix="Jr.", birth_date="1985-11-02"), Identity(family="de la Cruz López")],
)
def test_stored_row_renormalizes_to_the_same_record(identity):
    """store.py writes ``to_row_dict()`` and keys it from that row; the gate re-reads the row."""
    n = normalize_identity(identity)
    assert normalize_record(n.to_row_dict()) == n


def test_parse_date_returns_a_full_date_or_none():
    assert parse_date("1990-03-07") == date(1990, 3, 7)
    assert parse_date("03/07/1990") == date(1990, 3, 7)
    assert parse_date("1990-02-30") is None  # impossible: the record stays, the date does not
    assert parse_date("1990") is None  # year only is not a date to re-render
    assert parse_date("March 7 1990") is None
    assert parse_date(None) is None


def test_normalized_row_keeps_the_registration_spelling_where_it_is_shown():
    from backend.ingest.normalize import normalized_row

    row = normalized_row(JOSE)
    assert (row["given_name"], row["family_name"], row["address_line"], row["sex"]) == (
        "José",
        "Núñez-García",
        "857 Kling Arcade",
        "MALE",
    )
    assert (row["given_name_folded"], row["family_name_folded"], row["zip5"]) == ("jose", "nunez garcia", "01604")
    assert normalized_row(Identity(sex="F"))["sex"] == "FEMALE" and normalized_row(Identity())["sex"] is None


def test_generation_suffix_rides_on_the_surname_and_a_professional_one_does_not():
    from backend.ingest.normalize import normalized_row

    assert normalized_row(Identity(given="Robert", family="Smith", suffix="Jr."))["family_name"] == "Smith Jr."
    assert normalized_row(Identity(given="Ana", family="Ruiz", suffix="MD"))["family_name"] == "Ruiz"


@pytest.mark.parametrize(
    "identity",
    [
        JOSE,
        Identity(given="Robert", family="Smith", suffix="Jr.", birth_date="1985-11-02", sex="M"),
        Identity(given="Ana", family="Ruiz", suffix="MD", sex="F", phone="(617) 555-2368"),
        Identity(family="de la Cruz López"),
        Identity(),
    ],
)
def test_core_reads_the_stored_row_as_it_reads_the_identity(identity):
    """The row is display spelling plus core's columns; core must not see a different record."""
    from backend.ingest.normalize import normalized_row

    assert normalize_record(normalized_row(identity)) == normalize_record(identity_fields(identity))
