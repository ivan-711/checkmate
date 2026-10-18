"""Ingest's block_key rows are backend.core's keys (issue #10); one vocabulary for every writer."""

from importlib.metadata import version

from backend.core.api import CORE
from backend.core.block import (
    KEY_DMETA_FAMILY_YEAR,
    KEY_DOB_DAY_MONTH_SWAP,
    KEY_DOB_EXACT,
    KEY_PHONE_LAST7,
    KEY_ZIP5_INITIAL,
)
from backend.core.block import KEY_TYPES as CORE_KEY_TYPES
from backend.core.phonetics import PHONETICS_LIBRARY, double_metaphone
from backend.ingest.blocking import KEY_TYPES, block_keys
from backend.ingest.normalize import Identity, normalize_identity


def keys_for(**kwargs) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for key_type, value in block_keys(normalize_identity(Identity(**kwargs))):
        grouped.setdefault(key_type, set()).add(value)
    return grouped


def test_one_vocabulary_and_the_phonetics_pick():
    assert KEY_TYPES == CORE_KEY_TYPES
    assert PHONETICS_LIBRARY == "metaphone" and version("metaphone") == "0.6"  # first in the install order


def test_full_key_set_in_cores_vocabulary():
    keys = keys_for(given="José", family="García", birth_date="1990-03-07", phone="555-123-4567", postal_code="01604")
    assert keys[KEY_DMETA_FAMILY_YEAR] == {f"{code}|1990" for code in double_metaphone("garcia") if code}
    assert keys[KEY_DOB_EXACT] == {"1990-03-07"}
    assert keys[KEY_DOB_DAY_MONTH_SWAP] == {"1990-03-07"}  # the unordered (month, day) pair
    assert keys[KEY_PHONE_LAST7] == {"1234567"}
    assert keys[KEY_ZIP5_INITIAL] == {"01604|j"}


def test_rows_equal_core_block_keys_over_the_stored_row():
    """The gate's property: what ingest writes is what CORE.block_keys computes from the row it reads."""
    n = normalize_identity(
        Identity(
            given="María",
            family="García López",
            birth_date="1990-03-07",
            sex="female",
            phone="617-555-2368",
            postal_code="02139",
        )
    )
    row = n.to_row_dict()
    from_core = {(k.key_type, k.key_value) for k in CORE.block_keys(row)}
    assert set(block_keys(n)) == set(block_keys(row)) == from_core
    assert block_keys(row) == sorted(from_core)  # sorted and unique


def test_day_month_swap_shares_a_block_only_when_the_day_could_be_a_month():
    assert (
        keys_for(birth_date="1990-03-07")[KEY_DOB_DAY_MONTH_SWAP]
        == keys_for(birth_date="1990-07-03")[KEY_DOB_DAY_MONTH_SWAP]
    )
    assert KEY_DOB_DAY_MONTH_SWAP not in keys_for(birth_date="1990-03-17")
    assert KEY_DOB_DAY_MONTH_SWAP not in keys_for(birth_date="1990-03-03")


def test_surname_variants_share_a_phonetic_block():
    def dmeta(family: str) -> set[str]:
        return keys_for(family=family, birth_date="1990-03-07")[KEY_DMETA_FAMILY_YEAR]

    full = dmeta("García López")
    assert dmeta("Garcia") & full  # S1 + S3: accent and maternal surname dropped
    assert dmeta("García-López") == full  # S5
    assert dmeta("de la Cruz") == dmeta("Cruz")  # particles never key on their own


def test_placeholders_never_form_keys():
    keys = keys_for(given="Unknown", family="Doe", birth_date="1900-01-01", phone="555-555-5555", postal_code="01604")
    assert not keys  # placeholder name, DOB and phone; no initial for a placeholder given name


def test_placeholder_zip_and_phone_suffix_never_form_keys():
    keys = keys_for(given="Ana", family="Garcia", birth_date="1990-03-07", phone="617-000-0000", postal_code="00000")
    assert KEY_ZIP5_INITIAL not in keys and KEY_PHONE_LAST7 not in keys
    assert KEY_ZIP5_INITIAL in keys_for(given="Ana", family="Garcia", birth_date="1990-03-07", postal_code="01604")


def test_missing_values_give_no_keys_of_that_type():
    keys = keys_for(given="Ana", family="Garcia", birth_date="1990-03-07")
    assert KEY_PHONE_LAST7 not in keys and KEY_ZIP5_INITIAL not in keys
    assert block_keys(normalize_identity(Identity())) == []
