from datetime import date

import pytest

from backend.ingest.normalize import (
    Identity,
    fold,
    is_placeholder_dob,
    is_placeholder_name,
    is_placeholder_phone,
    normalize_identity,
    parse_date,
    phone_to_e164,
    strip_synthea_digits,
    zip5,
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
def test_strip_synthea_digits(raw, expected):
    assert strip_synthea_digits(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("José", "jose"),
        ("Núñez", "nunez"),
        ("GARCÍA", "garcia"),
        ("García-López", "garcia lopez"),
        ("O'Reilly", "oreilly"),
        ("  Ma.  Guadalupe ", "ma guadalupe"),
        ("de la Cruz", "de la cruz"),
        ("", None),
    ],
)
def test_fold_accent_case_hyphen(raw, expected):
    assert fold(raw) == expected


def test_parse_date_iso_and_clinic_formats():
    assert parse_date("1990-03-07") == date(1990, 3, 7)
    assert parse_date("03/07/1990") == date(1990, 3, 7)
    assert parse_date("1990-02-30") is None  # impossible date stays a record, just without a DOB
    assert parse_date("March 7 1990") is None
    assert parse_date(None) is None


def test_phone_to_e164():
    assert phone_to_e164("555-768-4657") == "+15557684657"
    assert phone_to_e164("(555) 768 4657") == "+15557684657"
    assert phone_to_e164("1-555-768-4657") == "+15557684657"
    assert phone_to_e164("4657") is None
    assert phone_to_e164(None) is None


def test_zip5():
    assert zip5("01604") == "01604"
    assert zip5("01604-1234") == "01604"
    assert zip5("") is None
    assert zip5("160") is None


def test_placeholders():
    assert is_placeholder_name("unknown")
    assert is_placeholder_name(None)
    assert not is_placeholder_name("garcia")
    assert is_placeholder_dob(date(1900, 1, 1))
    assert not is_placeholder_dob(date(1990, 3, 7))
    assert is_placeholder_phone("+15555555555")  # one repeated digit
    assert is_placeholder_phone("+16175550123")  # NXX-555-01XX fictional block
    assert not is_placeholder_phone("+15557684657")  # Synthea's own 555 area code is real enough to block on


def test_normalize_identity_keeps_original_beside_folded():
    fields = normalize_identity(Identity(given="José45", family="Núñez-García77", birth_date="1990-03-07", sex="male",
                                         phone="555-123-4567", address_line="  857  Kling Arcade ", postal_code="01604"))
    assert (fields.given_name, fields.family_name) == ("José", "Núñez-García")
    assert (fields.given_name_folded, fields.family_name_folded) == ("jose", "nunez garcia")
    assert (fields.birth_year, fields.birth_month, fields.birth_day) == (1990, 3, 7)
    assert fields.sex == "MALE"
    assert fields.phone_e164 == "+15551234567"
    assert fields.address_line == "857 Kling Arcade"
    assert fields.zip5 == "01604"


def test_normalize_identity_csv_sex_codes_and_missing_values():
    fields = normalize_identity(Identity(given="Robert", family="Smith", sex="F"))
    assert fields.sex == "FEMALE"
    assert fields.birth_date is None and fields.phone_e164 is None and fields.zip5 is None


def test_placeholder_phone_rejects_repeated_local_suffix_and_fictional_block():
    from backend.ingest.normalize import is_placeholder_phone as ph
    assert ph(phone_to_e164("617-000-0000"))  # 0000000 suffix
    assert ph(phone_to_e164("617-555-0100"))  # NXX-555-01XX fictional block
    assert ph(phone_to_e164("555-555-0199"))
    assert ph(phone_to_e164("999-999-9999"))
    assert not ph(phone_to_e164("617-555-0200"))  # 555-02XX is outside the fictional block
    assert not ph(phone_to_e164("555-768-4657"))


def test_placeholder_zip():
    from backend.ingest.normalize import is_placeholder_zip
    assert is_placeholder_zip("00000") and is_placeholder_zip("99999") and is_placeholder_zip("11111") and is_placeholder_zip("12345")
    assert is_placeholder_zip(None)
    assert not is_placeholder_zip("01604")
