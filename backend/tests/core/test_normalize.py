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
    # Both forms come from one token split (so fold(accented) == folded); punctuation becomes a space.
    assert n.family_name == "garcía lópez"
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
    assert parse_dob_parts("0000-01-01") == (None, None, None)


def test_surname_codes_skip_particles_and_derived_fields_survive_replace():
    import dataclasses

    n = normalize_record({"family_name": "De la Cruz García"})
    assert n.family_codes == normalize_record({"family_name": "Cruz García"}).family_codes
    assert normalize_record({"family_name": "de la"}).family_codes  # nothing but particles: keep them
    assert normalize_record({"given_name": "Unknown", "family_name": "Unknown"}).name_is_placeholder is True
    swapped = dataclasses.replace(n, family_tokens=("garcia",), family_name_folded="garcia")
    assert swapped.family_codes == normalize_record({"family_name": "García"}).family_codes


def test_suffix_survives_the_stored_shapes():
    n = normalize_record({"given_name": "Robert", "family_name": "Smith Jr."})
    assert n.to_contract_dict()["family_name"] == "smith jr"
    assert coerce_normalized(n.to_contract_dict()).suffix == "JR"
    assert coerce_normalized(n.to_row_dict()).family_name == "smith"


def test_placeholder_dates_outside_the_year_window_are_kept_whole_for_the_rules():
    assert parse_dob_parts("0001-01-01") == (1, 1, 1)
    assert parse_dob_parts("9999-12-31") == (9999, 12, 31)
    assert parse_dob_parts("0500-06-07") == (None, None, None)


def test_accented_title_is_removed_from_the_accented_form_too():
    n = normalize_record({"given_name": "Doña María"})
    assert n.given_name == "maría" and n.given_name_folded == "maria"


def test_suffix_without_family_name_does_not_become_a_surname():
    n = normalize_record({"given_name": "Robert", "suffix": "Jr"})
    assert n.suffix == "JR" and n.to_contract_dict()["family_name"] is None


def test_glued_suffix_and_title_leave_both_forms_in_step():
    n = normalize_record({"family_name": "Smith-Jr"})
    assert (n.family_name, n.family_name_folded, n.suffix) == ("smith", "smith", "JR")
    again = coerce_normalized(n.to_contract_dict())
    assert (again.family_name_folded, again.suffix) == ("smith", "JR")
    assert normalize_record({"given_name": "Dr.Robert"}).given_name == "robert"
    odd = normalize_record({"family_name": "V Smith V"})
    assert odd.family_name == "v smith" and odd.family_name_folded == "v smith" and odd.suffix == "V"


def test_date_objects_get_the_same_window_as_strings():
    assert parse_dob_parts(date(1500, 1, 1)) == (None, None, None)
    assert parse_dob_parts(date(1900, 1, 1)) == (1900, 1, 1)


def test_standalone_surnames_that_look_like_particles_still_share_codes():
    assert (
        normalize_record({"family_name": "Le"}).family_codes[0]
        in normalize_record({"family_name": "Le Tran"}).family_codes
    )


def test_derived_fields_cannot_be_passed_in():
    import pytest

    with pytest.raises(TypeError):
        Normalized(name_is_placeholder=True)


def test_inline_ordinal_suffix_and_stored_row_idempotence():
    n = normalize_record({"given_name": "John", "family_name": "Smith 3rd"})
    assert n.suffix == "III" and n.family_tokens == ("smith",)
    odd = normalize_record({"given_name": "Ann", "family_name": "Smith, III Don"})
    assert normalize_record(odd.to_row_dict()) == odd
    for given, family in (("Jr.", "Sr.-Sr."), ("López", "Mr-Dr.-Jr."), ("Sr", "Sra.-Sr-de la")):
        m = normalize_record({"given_name": given, "family_name": family})
        assert fold_text(m.family_name) == m.family_name_folded and fold_text(m.given_name) == m.given_name_folded


def test_phone_with_real_area_code_and_placeholder_line_is_a_placeholder():
    from backend.core.placeholders import is_placeholder_phone

    assert is_placeholder_phone("6170000000") and not is_placeholder_phone("6175552368")
