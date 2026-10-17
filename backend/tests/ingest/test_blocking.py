from datetime import date

from backend.ingest.blocking import (
    KEY_DOB_EXACT,
    KEY_METAPHONE_SURNAME_BIRTH_YEAR,
    KEY_PHONE_LAST7,
    KEY_ZIP5_INITIAL,
    block_keys,
    surname_key_token,
    swapped_day_month,
)
from backend.ingest.normalize import Identity, normalize_identity
from backend.ingest.phonetics import LIBRARY, primary_code


def keys_for(**kwargs) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for key_type, value in block_keys(normalize_identity(Identity(**kwargs))):
        grouped.setdefault(key_type, set()).add(value)
    return grouped


def test_phonetics_library_pick_is_recorded():
    assert LIBRARY == "metaphone==0.6"
    assert primary_code("garcia") == primary_code("garsia")


def test_full_key_set():
    keys = keys_for(given="José", family="García", birth_date="1990-03-07", phone="555-123-4567", postal_code="01604")
    assert keys[KEY_METAPHONE_SURNAME_BIRTH_YEAR] == {f"{primary_code('garcia')}:1990"}
    assert keys[KEY_DOB_EXACT] == {"1990-03-07", "1990-07-03"}  # exact plus the day/month swap
    assert keys[KEY_PHONE_LAST7] == {"1234567"}
    assert keys[KEY_ZIP5_INITIAL] == {"01604:j"}


def test_swapped_dob_only_when_day_can_be_a_month():
    assert swapped_day_month(date(1990, 3, 7)) == date(1990, 7, 3)
    assert swapped_day_month(date(1990, 3, 17)) is None
    assert swapped_day_month(date(1990, 3, 3)) is None
    assert keys_for(family="Garcia", birth_date="1990-03-17")[KEY_DOB_EXACT] == {"1990-03-17"}


def test_surname_variants_share_the_metaphone_block():
    base = keys_for(family="García López", birth_date="1990-03-07")[KEY_METAPHONE_SURNAME_BIRTH_YEAR]
    assert keys_for(family="Garcia", birth_date="1990-03-07")[KEY_METAPHONE_SURNAME_BIRTH_YEAR] == base  # S1 + S3
    assert keys_for(family="García-López", birth_date="1990-03-07")[KEY_METAPHONE_SURNAME_BIRTH_YEAR] == base  # S5
    assert surname_key_token("de la cruz") == "cruz"
    assert surname_key_token("de") is None


def test_placeholders_never_form_keys():
    keys = keys_for(given="Unknown", family="Doe", birth_date="1900-01-01", phone="555-555-5555", postal_code="01604")
    assert KEY_DOB_EXACT not in keys
    assert KEY_METAPHONE_SURNAME_BIRTH_YEAR not in keys
    assert KEY_PHONE_LAST7 not in keys
    assert KEY_ZIP5_INITIAL not in keys  # placeholder given name gives no initial


def test_missing_values_give_no_keys_of_that_type():
    keys = keys_for(given="Ana", family="Garcia", birth_date="1990-03-07")
    assert KEY_PHONE_LAST7 not in keys and KEY_ZIP5_INITIAL not in keys
    assert block_keys(normalize_identity(Identity())) == []


def test_placeholder_zip_and_phone_suffix_never_form_keys():
    keys = keys_for(given="Ana", family="Garcia", birth_date="1990-03-07", phone="617-000-0000", postal_code="00000")
    assert KEY_ZIP5_INITIAL not in keys and KEY_PHONE_LAST7 not in keys
    assert KEY_ZIP5_INITIAL in keys_for(given="Ana", family="Garcia", birth_date="1990-03-07", postal_code="01604")
