import pytest

from backend.core.band import (
    DEMO_THRESHOLDS,
    MatchResult,
    apply_negative_rules,
    band_from_score,
    evidence_snapshot,
    match,
)
from backend.core.score import HANDSET_WEIGHTS
from contracts.models.common import Band, NegativeRule
from contracts.models.pairs import EvidenceSnapshot
from contracts.models.thresholds import ThresholdSet

T = ThresholdSet(thresholds_id="t", c_low=0.0, c_high=4.0)
# Cutoffs far below any score force AUTO_LINK before rules, so each rule's demotion is visible.
FORCE_AUTO = ThresholdSet(thresholds_id="force-auto", c_low=-1000.0, c_high=-999.0)
FORCE_SEPARATE = ThresholdSet(thresholds_id="force-separate", c_low=1000.0, c_high=2000.0)

BASE = {
    "given_name": "Robert",
    "family_name": "Smith",
    "dob": "1990-03-07",
    "sex": "M",
    "phone": "617-555-2368",
    "address": "12 Main St",
    "zip": "02139",
}


def test_band_cutoffs_are_inclusive_at_the_lower_bound_of_each_band():
    assert band_from_score(-0.001, T) is Band.KEEP_SEPARATE
    assert band_from_score(0.0, T) is Band.REVIEW
    assert band_from_score(3.999, T) is Band.REVIEW
    assert band_from_score(4.0, T) is Band.AUTO_LINK


RULE_CASES = {
    NegativeRule.SEX_CONFLICT: (BASE, {**BASE, "sex": "F"}),
    NegativeRule.BIRTH_YEAR_GAP_GT_2: (BASE, {**BASE, "dob": "1993-03-07"}),
    NegativeRule.TWIN: (BASE, {**BASE, "given_name": "Zachary"}),
    NegativeRule.PARENT_CHILD: (BASE, {**BASE, "dob": "1960-03-07"}),
    NegativeRule.GENERATION_SUFFIX_MISMATCH: ({**BASE, "suffix": "Jr"}, {**BASE, "suffix": "Sr"}),
    NegativeRule.PLACEHOLDER_NAME: (BASE, {**BASE, "given_name": "Baby", "family_name": "Doe"}),
    NegativeRule.PLACEHOLDER_DOB: (BASE, {**BASE, "dob": "1900-01-01"}),
}


@pytest.mark.parametrize("rule", list(RULE_CASES))
def test_each_negative_rule_fires_and_demotes_auto_link_to_review_only(rule):
    a, b = RULE_CASES[rule]
    result = match(a, b, HANDSET_WEIGHTS, FORCE_AUTO)
    assert rule in result.negative_rules_fired
    assert result.band_before_rules is Band.AUTO_LINK
    assert result.band is Band.REVIEW
    # Never below REVIEW, and KEEP_SEPARATE is untouched by the same rule.
    separate = match(a, b, HANDSET_WEIGHTS, FORCE_SEPARATE)
    assert rule in separate.negative_rules_fired and separate.band is Band.KEEP_SEPARATE


def test_apply_negative_rules_only_touches_auto_link():
    fired = [NegativeRule.SEX_CONFLICT]
    assert apply_negative_rules(Band.AUTO_LINK, fired) is Band.REVIEW
    assert apply_negative_rules(Band.REVIEW, fired) is Band.REVIEW
    assert apply_negative_rules(Band.KEEP_SEPARATE, fired) is Band.KEEP_SEPARATE
    assert apply_negative_rules(Band.AUTO_LINK, []) is Band.AUTO_LINK


def test_rules_do_not_fire_on_benign_variants():
    year_off_by_one = match(BASE, {**BASE, "dob": "1991-03-07"}, HANDSET_WEIGHTS, T)
    assert NegativeRule.BIRTH_YEAR_GAP_GT_2 not in year_off_by_one.negative_rules_fired
    nickname = match(BASE, {**BASE, "given_name": "Bob"}, HANDSET_WEIGHTS, T)
    assert NegativeRule.TWIN not in nickname.negative_rules_fired
    dropped_suffix = match({**BASE, "suffix": "Jr"}, BASE, HANDSET_WEIGHTS, T)
    assert NegativeRule.GENERATION_SUFFIX_MISMATCH not in dropped_suffix.negative_rules_fired
    assert match(BASE, BASE, HANDSET_WEIGHTS, T).negative_rules_fired == ()
    compound = match({**BASE, "given_name": "Maria Jose"}, {**BASE, "given_name": "Maria Fernanda"}, HANDSET_WEIGHTS, T)
    assert NegativeRule.TWIN in compound.negative_rules_fired


def test_match_returns_the_full_shape_and_accepts_contract_dicts():
    result = match(BASE, {**BASE, "dob": "1990-07-03"}, HANDSET_WEIGHTS, DEMO_THRESHOLDS)
    assert isinstance(result, MatchResult)
    d = result.as_dict()
    assert set(d) >= {"raw_score", "p", "band", "contributions", "negative_rules_fired", "features", "missing"}
    assert result.features["dob_day_month_swap"] == 1.0 and result.features["dob_exact"] == 0.0
    assert result.band is Band.AUTO_LINK and result.is_calibrated is False
    assert result.scorer_version == "handset-1" and result.thresholds_id == "demo-handset-0"
    snap = evidence_snapshot(result, HANDSET_WEIGHTS, DEMO_THRESHOLDS, policy_version="frontdesk-gate/1")
    assert isinstance(snap, EvidenceSnapshot)
    assert snap.raw_score == result.raw_score and snap.c_high == DEMO_THRESHOLDS.c_high
    assert snap.t_high_display is not None and 0.0 < snap.t_high_display < 1.0


def test_handset_demo_bands_separate_same_person_from_sibling():
    same = match(BASE, {**BASE, "family_name": "SMITH", "address": "12 Main Street"}, HANDSET_WEIGHTS, DEMO_THRESHOLDS)
    sibling = match(BASE, {**BASE, "given_name": "Zachary", "dob": "1992-11-20"}, HANDSET_WEIGHTS, DEMO_THRESHOLDS)
    assert same.band is Band.AUTO_LINK
    assert sibling.band is Band.KEEP_SEPARATE


def test_handset_demo_claims_hold():
    """Pins the behaviour the HANDSET_WEIGHTS comment promises for the checkpoint."""
    swap = match(BASE, {**BASE, "dob": "1990-07-03"}, HANDSET_WEIGHTS, DEMO_THRESHOLDS)
    day_edit = match(BASE, {**BASE, "dob": "1990-03-17"}, HANDSET_WEIGHTS, DEMO_THRESHOLDS)
    year_edit = match(BASE, {**BASE, "dob": "1991-03-07"}, HANDSET_WEIGHTS, DEMO_THRESHOLDS)
    assert swap.band is Band.AUTO_LINK and day_edit.band is Band.AUTO_LINK
    assert year_edit.band is Band.REVIEW
    for given, dob in (("Carmen", "1992-03-07"), ("Zachary", "1988-11-20"), ("Carmen", "1990-03-07")):
        sibling = match(BASE, {**BASE, "given_name": given, "dob": dob}, HANDSET_WEIGHTS, DEMO_THRESHOLDS)
        # The weights alone keep a sibling out of AUTO_LINK; the rules are not what saves it.
        assert sibling.band_before_rules is not Band.AUTO_LINK


def test_match_features_are_the_weighted_values_and_reproduce_the_raw_score():
    from backend.core.band import features_of

    willie = {**BASE, "given_name": "Willie"}
    will = {**willie, "given_name": "Will"}
    result = match(willie, will, HANDSET_WEIGHTS, DEMO_THRESHOLDS)
    assert 0.0 < result.features["given_nickname"] < 1.0  # capped
    assert features_of(willie, will).values["given_nickname"] == 1.0  # the raw feature, for ablations
    rebuilt = (
        HANDSET_WEIGHTS.intercept
        + sum(HANDSET_WEIGHTS.weights[k] * (v or 0.0) for k, v in result.features.items())
        + sum(HANDSET_WEIGHTS.weights[f"missing_{g}"] for g, flag in result.missing.items() if flag)
    )
    assert rebuilt == pytest.approx(result.raw_score, abs=1e-9)
