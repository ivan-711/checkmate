import pytest

from backend.core.features import FEATURE_NAMES, MISSING_GROUPS, compute_features
from backend.core.normalize import normalize_record


def feats(a: dict, b: dict):
    return compute_features(normalize_record(a), normalize_record(b))


BASE = {
    "given_name": "Maria",
    "family_name": "Garcia",
    "dob": "1990-03-07",
    "sex": "F",
    "phone": "617-555-2368",
    "address": "12 Main St",
    "zip": "02139",
}


def test_every_feature_is_in_unit_interval_or_none_and_identical_records_score_one():
    fv = feats(BASE, BASE)
    assert set(fv.values) == set(FEATURE_NAMES)
    assert set(fv.missing) == set(MISSING_GROUPS)
    for name, v in fv.values.items():
        assert v is None or 0.0 <= v <= 1.0, name
    assert fv.values["given_jw"] == fv.values["family_jw"] == fv.values["dob_exact"] == 1.0
    assert fv.values["phone_match"] == fv.values["address_jaccard"] == fv.values["zip_match"] == 1.0
    assert not any(fv.missing.values())


def test_day_month_swap_fires_swap_signal_and_exact_is_zero():
    fv = feats(BASE, {**BASE, "dob": "1990-07-03"})
    assert fv.values["dob_day_month_swap"] == 1.0
    assert fv.values["dob_exact"] == 0.0
    assert fv.values["dob_one_component_off"] == 0.0
    assert fv.values["dob_year_match"] == 1.0


def test_one_digit_edit_and_one_component_off():
    edit = feats({**BASE, "dob": "1985-11-02"}, {**BASE, "dob": "1985-11-12"})
    assert edit.values["dob_one_digit_edit"] == 1.0 and edit.values["dob_exact"] == 0.0
    year = feats({**BASE, "dob": "1989-11-02"}, {**BASE, "dob": "1990-11-02"})
    assert year.values["dob_one_component_off"] == 1.0 and year.values["dob_one_digit_edit"] == 0.0
    assert year.values["dob_year_match"] == 0.0


def test_year_only_dob_keeps_year_match_and_flags_dob_missing():
    fv = feats(BASE, {**BASE, "dob": "1990"})
    assert fv.values["dob_exact"] is None
    assert fv.values["dob_year_match"] == 1.0
    assert fv.missing["dob"] is True


def test_placeholder_dob_is_treated_as_missing():
    fv = feats({**BASE, "dob": "1900-01-01"}, {**BASE, "dob": "1900-01-01"})
    assert fv.values["dob_exact"] is None and fv.missing["dob"] is True


def test_accent_and_hyphen_variants_of_surname_score_close_to_identical():
    same = feats(BASE, {**BASE, "family_name": "García-López"})
    variant = feats({**BASE, "family_name": "García-López"}, {**BASE, "family_name": "Garcia Lopez"})
    assert variant.values["family_jw_folded"] == 1.0
    assert variant.values["family_dl"] == 1.0
    assert variant.values["family_dmeta"] == 1.0
    assert variant.values["family_token_overlap"] == 1.0
    assert variant.values["family_jw"] >= 0.9
    assert same.values["family_jw_folded"] < variant.values["family_jw_folded"]


def test_maternal_surname_dropped_keeps_token_overlap_at_one():
    fv = feats({**BASE, "family_name": "García López"}, {**BASE, "family_name": "García"})
    assert fv.values["family_token_overlap"] == 1.0


def test_nickname_and_initial_signals():
    assert feats({**BASE, "given_name": "Francisco"}, {**BASE, "given_name": "Paco"}).values["given_nickname"] == 1.0
    assert feats({**BASE, "given_name": "Robert"}, {**BASE, "given_name": "Bob"}).values["given_nickname"] == 1.0
    assert (
        feats({**BASE, "given_name": "Ma. Guadalupe"}, {**BASE, "given_name": "María Guadalupe"}).values[
            "given_nickname"
        ]
        == 1.0
    )
    assert feats({**BASE, "given_name": "Robert"}, {**BASE, "given_name": "Susan"}).values["given_nickname"] == 0.0
    initial = feats({**BASE, "given_name": "Ana Lucia"}, {**BASE, "given_name": "A."})
    assert initial.values["given_initial"] == 1.0


def test_sex_phone_address_zip_signals():
    fv = feats(BASE, {**BASE, "sex": "M", "phone": "617-555-2369", "address": "12 Main Street", "zip": "02138"})
    assert fv.values["sex_match"] == 0.0
    assert fv.values["phone_match"] == pytest.approx(0.8)
    assert fv.values["address_jaccard"] == 1.0
    assert fv.values["zip_match"] == 0.5
    assert feats(BASE, {**BASE, "phone": "212-867-5309"}).values["phone_match"] == 0.0


def test_placeholder_phone_on_both_sides_is_missing_not_a_match():
    fv = feats({**BASE, "phone": "555-555-5555"}, {**BASE, "phone": "555-555-5555"})
    assert fv.values["phone_match"] is None and fv.missing["phone"] is True


def test_placeholder_name_yields_missing_name_features():
    fv = feats(
        {**BASE, "given_name": "Baby", "family_name": "Doe"}, {**BASE, "given_name": "Baby", "family_name": "Doe"}
    )
    assert fv.values["given_jw"] is None and fv.values["family_jw"] is None
    assert fv.missing["given_name"] and fv.missing["family_name"]


def test_equal_tokens_earn_the_nickname_credit_so_a_nickname_never_outscores_the_name():
    assert feats(BASE, BASE).values["given_nickname"] == 1.0
    fv = feats({**BASE, "given_name": "Maria Jose"}, {**BASE, "given_name": "Maria Fernanda"})
    assert fv.values["given_nickname"] == 1.0 and fv.values["given_token_overlap"] == 0.5


def test_one_digit_edit_and_one_component_off_are_exclusive():
    fv = feats({**BASE, "dob": "1985-11-02"}, {**BASE, "dob": "1985-11-12"})
    assert fv.values["dob_one_digit_edit"] == 1.0 and fv.values["dob_one_component_off"] == 0.0


def test_dropped_maternal_surname_still_matches_phonetically():
    fv = feats({**BASE, "family_name": "García López"}, {**BASE, "family_name": "García"})
    assert fv.values["family_dmeta"] == 1.0
    swapped = feats({**BASE, "family_name": "García López"}, {**BASE, "family_name": "López García"})
    assert swapped.values["family_dmeta"] == 1.0 and swapped.values["family_token_overlap"] == 1.0


def test_features_of_entry_point_matches_compute_features():
    from backend.core.band import features_of

    assert features_of(BASE, BASE).values == feats(BASE, BASE).values
