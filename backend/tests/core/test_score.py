import json
import math

import pytest

from backend.core.features import FEATURE_NAMES, MISSING_NAMES, compute_features
from backend.core.normalize import normalize_record
from backend.core.score import (
    HANDSET_SCORER_VERSION,
    HANDSET_WEIGHTS,
    Weights,
    display_probability,
    load_weights,
    save_weights,
    score_pair,
    sigmoid,
)

BASE = {
    "given_name": "Maria",
    "family_name": "Garcia",
    "dob": "1990-03-07",
    "sex": "F",
    "phone": "617-555-2368",
    "address": "12 Main St",
    "zip": "02139",
}
PAIRS = [
    (BASE, BASE),
    (BASE, {**BASE, "dob": "1990-07-03"}),
    (BASE, {"given_name": "Zed", "family_name": "Quill"}),
    ({"given_name": "Unknown", "family_name": "Unknown"}, {"given_name": "Unknown", "family_name": "Unknown"}),
    (BASE, {**BASE, "phone": None, "address": None, "zip": None, "sex": None}),
]


@pytest.mark.parametrize("a,b", PAIRS)
def test_contributions_sum_to_logit_minus_intercept(a, b):
    fv = compute_features(normalize_record(a), normalize_record(b))
    result = score_pair(fv, HANDSET_WEIGHTS)
    total = math.fsum(c.logit for c in result.contributions)
    assert total == pytest.approx(result.raw_score - HANDSET_WEIGHTS.intercept, abs=1e-9)
    assert [c.feature for c in result.contributions] == list(FEATURE_NAMES) + list(MISSING_NAMES)


def test_missing_feature_contributes_zero_and_its_indicator_contributes_its_weight():
    fv = compute_features(normalize_record(BASE), normalize_record({**BASE, "phone": None}))
    result = score_pair(fv, HANDSET_WEIGHTS)
    by_name = {c.feature: c for c in result.contributions}
    assert by_name["phone_match"].value is None and by_name["phone_match"].logit == 0.0
    assert by_name["missing_phone"].value == 1.0
    assert by_name["missing_phone"].logit == HANDSET_WEIGHTS.weights["missing_phone"]


def test_p_is_monotone_in_logit_and_display_only_and_never_calibrated():
    logits = [-30.0, -5.0, -1.0, 0.0, 0.5, 3.0, 12.0, 40.0]
    ps = [sigmoid(x) for x in logits]
    assert ps == sorted(ps) and all(0.0 <= p <= 1.0 for p in ps)
    assert sigmoid(0.0) == 0.5
    fv = compute_features(normalize_record(BASE), normalize_record(BASE))
    result = score_pair(fv, HANDSET_WEIGHTS)
    assert result.p == pytest.approx(sigmoid(result.raw_score))
    assert result.is_calibrated is False and result.p_is_display_only is True


def test_platt_display_map_is_monotone_when_a_is_negative():
    platt = Weights(
        scorer_version="platt-test",
        intercept=HANDSET_WEIGHTS.intercept,
        weights=HANDSET_WEIGHTS.weights,
        platt_a=-0.7,
        platt_b=0.3,
    )
    ps = [display_probability(s, platt) for s in (-5.0, 0.0, 2.0, 9.0)]
    assert ps == sorted(ps)


def test_handset_weights_version_and_identical_record_scores_high_different_people_low():
    assert HANDSET_WEIGHTS.scorer_version == HANDSET_SCORER_VERSION == "handset-0"
    same = score_pair(compute_features(normalize_record(BASE), normalize_record(BASE)), HANDSET_WEIGHTS)
    other = score_pair(
        compute_features(
            normalize_record(BASE),
            normalize_record({"given_name": "Zed", "family_name": "Quill", "dob": "1950-12-25", "sex": "M"}),
        ),
        HANDSET_WEIGHTS,
    )
    assert same.raw_score > 4.0
    assert other.raw_score < 0.0


def test_weights_reject_unknown_or_missing_names():
    with pytest.raises(ValueError):
        Weights(scorer_version="bad", intercept=0.0, weights={**HANDSET_WEIGHTS.weights, "bogus": 1.0})
    with pytest.raises(ValueError):
        Weights(
            scorer_version="bad",
            intercept=0.0,
            weights={k: v for k, v in HANDSET_WEIGHTS.weights.items() if k != "sex_match"},
        )
    with pytest.raises(ValueError):
        Weights(scorer_version="bad", intercept=0.0, weights=HANDSET_WEIGHTS.weights, platt_a=-1.0)
    with pytest.raises(ValueError):
        Weights(scorer_version="bad", intercept=0.0, weights=HANDSET_WEIGHTS.weights, platt_a=0.5, platt_b=0.0)


def test_weights_json_round_trip(tmp_path):
    path = tmp_path / "w.json"
    save_weights(HANDSET_WEIGHTS, path)
    loaded = load_weights(path)
    assert loaded == HANDSET_WEIGHTS
    assert json.loads(path.read_text())["scorer_version"] == "handset-0"


def test_handset_json_on_disk_equals_the_in_code_weights():
    assert load_weights("handset-0") == HANDSET_WEIGHTS


def test_load_weights_distinguishes_paths_from_version_names(tmp_path):
    with pytest.raises(FileNotFoundError) as info:
        load_weights(tmp_path / "missing.json")
    assert str(tmp_path / "missing.json") in str(info.value)
    with pytest.raises(FileNotFoundError) as info:
        load_weights("no-such-version")
    assert "no-such-version.json" in str(info.value)


def test_platt_parameters_round_trip_through_json(tmp_path):
    platt = Weights(
        scorer_version="platt-test", intercept=-11.0, weights=HANDSET_WEIGHTS.weights, platt_a=-0.7, platt_b=0.3
    )
    path = tmp_path / "platt.json"
    save_weights(platt, path)
    loaded = Weights.from_json_dict(json.loads(path.read_text()))
    assert loaded == platt and loaded.platt_a == -0.7


def _raw(a, b):
    return score_pair(compute_features(normalize_record(a), normalize_record(b)), HANDSET_WEIGHTS)


WILLIE = {**BASE, "given_name": "Willie"}


def test_nickname_credit_is_capped_at_what_the_given_name_lost():
    same = _raw(WILLIE, WILLIE)
    will = _raw(WILLIE, {**WILLIE, "given_name": "Will"})
    assert will.raw_score == pytest.approx(same.raw_score, abs=1e-9)  # cap engaged: lands on identical
    nick = {c.feature: c for c in will.contributions}["given_nickname"]
    assert 0.0 < nick.value < 1.0 and nick.logit == pytest.approx(
        HANDSET_WEIGHTS.weights["given_nickname"] * nick.value
    )


def test_nickname_cap_leaves_pairs_that_lost_more_than_the_credit_untouched():
    robert = {**BASE, "given_name": "Robert"}
    bob = _raw(robert, {**robert, "given_name": "Bob"})
    nick = {c.feature: c for c in bob.contributions}["given_nickname"]
    assert nick.value == 1.0 and nick.logit == HANDSET_WEIGHTS.weights["given_nickname"]


def test_nickname_cap_is_inert_for_a_non_positive_weight_and_for_missing_names():
    from backend.core.score import capped_nickname_value

    flat = Weights(scorer_version="flat", intercept=0.0, weights={**HANDSET_WEIGHTS.weights, "given_nickname": -0.2})
    assert capped_nickname_value({"given_nickname": 1.0}, flat) == 1.0
    assert capped_nickname_value({"given_nickname": None}, HANDSET_WEIGHTS) is None
