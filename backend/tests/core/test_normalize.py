from datetime import date

from backend.core.normalize import (
    Normalized,
    coerce_normalized,
    fold_text,
    normalize_phone,
    normalize_record,
    normalize_zip5,
    parse_dob_parts,
)


def test_casefold_happens_before_features_and_accents_are_kept_in_accented_form():
    n = normalize_record({"given_name": "JOSÉ", "family_name": "García-López"})
    assert n.given_name == "josé"
    assert n.family_name == "garcía-lópez"
    assert n.given_name_folded == "jose"
    assert n.family_name_folded == "garcia lopez"
    assert n.family_tokens == ("garcia", "lopez")


def test_fold_text_strips_enye_apostrophe_and_hyphen():
    assert fold_text("Muñoz") == "munoz"
    assert fold_text("O'Reilly") == "o reilly"
    assert fold_text("De la Cruz") == "de la cruz"
    assert fold_text("  ") is None


def test_synthea_digits_are_stripped_from_names():
    n = normalize_record({"given_name": "Ahmed109", "family_name": "Khan72"})
    assert n.given_name == "ahmed"
    assert n.family_name_folded == "khan"


def test_generation_suffix_is_split_out_of_family_name():
    n = normalize_record({"given_name": "Robert", "family_name": "Smith Jr."})
    assert n.suffix == "JR"
    assert n.family_name_folded == "smith"
    explicit = normalize_record({"given_name": "Robert", "family_name": "Smith", "suffix": "III"})
    assert explicit.suffix == "III"


def test_dob_parts_from_iso_us_compact_and_year_only():
    assert parse_dob_parts("1990-03-07") == (1990, 3, 7)
    assert parse_dob_parts("03/07/1990") == (1990, 3, 7)
    assert parse_dob_parts("19900307") == (1990, 3, 7)
    assert parse_dob_parts("1990") == (1990, None, None)
    assert parse_dob_parts(date(1985, 11, 2)) == (1985, 11, 2)
    assert parse_dob_parts("") == (None, None, None)
    assert parse_dob_parts("not a date") == (None, None, None)


def test_impossible_day_is_dropped_not_raised():
    assert parse_dob_parts("1990-02-30") == (1990, 2, None)
    assert parse_dob_parts("1990-13-01") == (1990, None, 1)


def test_phone_to_e164_us_only():
    assert normalize_phone("(617) 555-0199") == ("+16175550199", "6175550199")
    assert normalize_phone("1-617-555-0199") == ("+16175550199", "6175550199")
    assert normalize_phone("555-0199") == (None, None)
    assert normalize_phone(None) == (None, None)


def test_zip5_from_zip_plus_four_and_lost_leading_zero():
    assert normalize_zip5("02139-1234") == "02139"
    assert normalize_zip5("2139") == "02139"
    assert normalize_zip5("ABCDE") is None


def test_address_abbreviations_expand_to_shared_tokens():
    a = normalize_record({"address": "12 Main St, Apt 4"})
    b = normalize_record({"address": "12 Main Street #4"})
    assert a.address_tokens == b.address_tokens == ("12", "main", "street", "apartment", "4")


def test_sex_mapping():
    assert normalize_record({"sex": "male"}).sex == "M"
    assert normalize_record({"gender": "F"}).sex == "F"
    assert normalize_record({"sex": "unknown"}).sex is None


def test_coerce_is_idempotent_on_contract_shape():
    n = normalize_record({"record_id": "r1", "given_name": "Ana", "family_name": "Pérez", "dob": "1990-01-02"})
    again = coerce_normalized(n.to_contract_dict())
    assert again.given_name_folded == n.given_name_folded
    assert again.birth_date == n.birth_date == date(1990, 1, 2)
    assert isinstance(coerce_normalized(n), Normalized)


def test_year_only_dob_survives_the_table_row_but_not_the_contract_shape():
    n = normalize_record({"record_id": "r1", "given_name": "Ana", "family_name": "Pérez", "dob": "1990"})
    assert n.birth_year == 1990 and n.birth_date is None
    assert coerce_normalized(n.to_row_dict()).birth_year == 1990
    assert coerce_normalized(n.to_contract_dict()).birth_year is None  # documented limit of the contract


def test_contract_dict_builds_the_frozen_model():
    from uuid import uuid4

    from contracts.models.records import NormalizedRecord

    n = normalize_record({"record_id": str(uuid4()), "given_name": "Ana", "family_name": "Pérez", "dob": "1990-01-02"})
    model = NormalizedRecord(**n.to_contract_dict())
    assert model.family_name_folded == "perez"
    assert coerce_normalized(model).family_tokens == ("perez",)


def test_middle_initial_is_not_a_generation_suffix_and_only_the_last_family_token_is():
    n = normalize_record({"given_name": "Mary V", "family_name": "Smith"})
    assert n.suffix is None and n.given_tokens == ("mary", "v")
    assert normalize_record({"given_name": "Robert", "family_name": "Jr Smith"}).suffix is None
    assert normalize_record({"given_name": "Robert", "family_name": "Smith Jr"}).suffix == "JR"


def test_titles_are_removed_from_both_forms_and_senor_is_a_title_not_a_suffix():
    n = normalize_record({"given_name": "Dr. Robert", "family_name": "Sr. García"})
    assert n.given_name == "robert" and n.given_tokens == ("robert",)
    assert n.family_name == "garcía" and n.suffix is None
    jr = normalize_record({"given_name": "Robert", "family_name": "Smith Jr."})
    assert jr.family_name == "smith" and jr.suffix == "JR"


def test_phone_extension_is_dropped_not_fatal():
    assert normalize_phone("617-555-2368 x123") == ("+16175550199".replace("0199", "2368"), "6175552368")
    assert normalize_phone("617-555-2368 ext. 12")[1] == "6175552368"


def test_date_regex_is_anchored_and_year_bounded():
    assert parse_dob_parts("1990-03-0712") == (None, None, None)
    assert parse_dob_parts("1990-03-07T00:00:00Z") == (1990, 3, 7)
    assert parse_dob_parts("0000-01-01") == (None, 1, 1)


def test_primary_surname_skips_particles_and_codes_cover_every_token():
    n = normalize_record({"family_name": "De la Cruz García"})
    assert n.family_primary == "cruz"
    assert len(n.family_codes) >= 2
    assert normalize_record({"given_name": "Unknown", "family_name": "Unknown"}).name_is_placeholder is True
