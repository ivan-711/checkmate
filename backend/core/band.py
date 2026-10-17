"""S6 band: raw-score cutoffs decide, negative rules demote AUTO_LINK to REVIEW only.

``match`` is the one entry point the evaluation runner and the FrontDesk gate call. It takes
two normalized records, a weights object and a ``ThresholdSet``; it never takes a case id or
a rationale, because nothing here may depend on who is asking.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.core.features import FeatureVector, compute_features
from backend.core.nicknames import same_nickname_family
from backend.core.normalize import Normalized, coerce_normalized
from backend.core.placeholders import is_placeholder_dob
from backend.core.score import Weights, display_probability, score_pair
from contracts.models.common import Band, Contribution, NegativeRule
from contracts.models.pairs import EvidenceSnapshot
from contracts.models.thresholds import ThresholdSet

# Named cut-offs for the negative rules (reviewer checklist 2: no magic numbers).
BIRTH_YEAR_GAP_MAX = 2  # BIRTH_YEAR_GAP_GT_2 fires above this
PARENT_CHILD_MIN_YEAR_GAP = 18  # taxonomy N3: same full name, DOB at least 18 years apart
TWIN_GIVEN_JW_MAX = 0.85  # taxonomy N2: same DOB and surname, clearly different given name
SAME_NAME_JW_MIN = 0.95  # "same full name" for the parent/child rule

# A placeholder threshold set so the 15:30 checkpoint can band pairs under handset-0.
# W3a replaces it with cutoffs chosen on out-of-fold development raw scores (section 6).
DEMO_THRESHOLDS = ThresholdSet(
    thresholds_id="demo-handset-0",
    c_low=0.0,
    c_high=4.0,
    auto_link_enabled=False,
    is_calibrated=False,
)


def band_from_score(raw_score: float, thresholds: ThresholdSet) -> Band:
    """``s < c_low`` KEEP_SEPARATE; ``c_low <= s < c_high`` REVIEW; ``s >= c_high`` AUTO_LINK."""
    if raw_score < thresholds.c_low:
        return Band.KEEP_SEPARATE
    if raw_score < thresholds.c_high:
        return Band.REVIEW
    return Band.AUTO_LINK


def negative_rules_for(a: Normalized, b: Normalized, fv: FeatureVector) -> list[NegativeRule]:
    """Every rule that fires for this pair, in the glossary's order."""
    fired: list[NegativeRule] = []
    values = fv.values
    if a.sex and b.sex and a.sex != b.sex:
        fired.append(NegativeRule.SEX_CONFLICT)
    years_known = a.birth_year is not None and b.birth_year is not None
    year_gap = abs(a.birth_year - b.birth_year) if years_known else None
    if year_gap is not None and year_gap > BIRTH_YEAR_GAP_MAX:
        fired.append(NegativeRule.BIRTH_YEAR_GAP_GT_2)
    same_family = values.get("family_jw_folded") == 1.0
    given_jw = values.get("given_jw_folded")
    # Twins share DOB and surname but have different given names: some token of the shorter given
    # name has no equal or nickname partner in the other ("Maria Jose" / "Maria Fernanda" fires;
    # "Maria Jose" / "Maria", a dropped compound name, and "Robert" / "Bob" do not).
    first_names_differ = given_names_differ(a.given_tokens, b.given_tokens)
    if (
        values.get("dob_exact") == 1.0
        and same_family
        and given_jw is not None
        and given_jw < TWIN_GIVEN_JW_MAX
        and first_names_differ
    ):
        fired.append(NegativeRule.TWIN)
    same_full_name = (
        given_jw is not None
        and given_jw >= SAME_NAME_JW_MIN
        and (values.get("family_jw_folded") or 0.0) >= SAME_NAME_JW_MIN
    )
    if same_full_name and year_gap is not None and year_gap >= PARENT_CHILD_MIN_YEAR_GAP:
        fired.append(NegativeRule.PARENT_CHILD)
    if a.suffix and b.suffix and a.suffix != b.suffix:
        fired.append(NegativeRule.GENERATION_SUFFIX_MISMATCH)
    if a.name_is_placeholder or b.name_is_placeholder:
        fired.append(NegativeRule.PLACEHOLDER_NAME)
    if is_placeholder_dob(a.birth_year, a.birth_month, a.birth_day) or is_placeholder_dob(
        b.birth_year, b.birth_month, b.birth_day
    ):
        fired.append(NegativeRule.PLACEHOLDER_DOB)
    return fired


def given_names_differ(tokens_a: tuple[str, ...], tokens_b: tuple[str, ...]) -> bool:
    if not tokens_a or not tokens_b:
        return False
    shorter, longer = sorted((tokens_a, tokens_b), key=len)
    return any(not any(same_nickname_family(x, y) for y in longer) for x in shorter)


def apply_negative_rules(band: Band, fired: list[NegativeRule]) -> Band:
    """A fired rule turns AUTO_LINK into REVIEW; REVIEW and KEEP_SEPARATE are untouched."""
    if fired and band is Band.AUTO_LINK:
        return Band.REVIEW
    return band


@dataclass(frozen=True)
class MatchResult:
    raw_score: float
    p: float  # display-only
    band: Band
    contributions: tuple[Contribution, ...]
    negative_rules_fired: tuple[NegativeRule, ...]
    features: dict[str, float | None]
    missing: dict[str, bool]
    band_before_rules: Band
    scorer_version: str
    thresholds_id: str
    is_calibrated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_score": self.raw_score,
            "p": self.p,
            "band": self.band,
            "contributions": list(self.contributions),
            "negative_rules_fired": [r.value for r in self.negative_rules_fired],
            "features": dict(self.features),
            "missing": dict(self.missing),
            "band_before_rules": self.band_before_rules,
            "scorer_version": self.scorer_version,
            "thresholds_id": self.thresholds_id,
            "is_calibrated": self.is_calibrated,
        }


def match(record_a_norm: Any, record_b_norm: Any, weights: Weights, thresholds: ThresholdSet) -> MatchResult:
    """S4 + S5 + S6 for one pair. Pure: same inputs, same result, whoever calls it."""
    a, b = coerce_normalized(record_a_norm), coerce_normalized(record_b_norm)
    fv = compute_features(a, b)
    scored = score_pair(fv, weights)
    before = band_from_score(scored.raw_score, thresholds)
    fired = negative_rules_for(a, b, fv)
    return MatchResult(
        raw_score=scored.raw_score,
        p=scored.p,
        band=apply_negative_rules(before, fired),
        contributions=scored.contributions,
        negative_rules_fired=tuple(fired),
        features=dict(fv.values),
        missing=dict(fv.missing),
        band_before_rules=before,
        scorer_version=weights.scorer_version,
        thresholds_id=thresholds.thresholds_id,
    )


def evidence_snapshot(
    result: MatchResult, weights: Weights, thresholds: ThresholdSet, policy_version: str | None = None
) -> EvidenceSnapshot:
    """The frozen contract snapshot W3a stores with a decision; never re-derived later."""
    return EvidenceSnapshot(
        features=result.features,
        missing_flags=result.missing,
        weights=dict(weights.weights),
        intercept=weights.intercept,
        contributions=list(result.contributions),
        raw_score=result.raw_score,
        c_low=thresholds.c_low,
        c_high=thresholds.c_high,
        platt_a=weights.platt_a,
        platt_b=weights.platt_b,
        # The threshold row's display values win, so the snapshot agrees with /threshold-sets/current.
        t_low_display=(
            thresholds.t_low_display
            if thresholds.t_low_display is not None
            else display_probability(thresholds.c_low, weights)
        ),
        t_high_display=(
            thresholds.t_high_display
            if thresholds.t_high_display is not None
            else display_probability(thresholds.c_high, weights)
        ),
        negative_rules_fired=[r.value for r in result.negative_rules_fired],
        scorer_version=weights.scorer_version,
        threshold_set_id=thresholds.thresholds_id,
        policy_version=policy_version,
    )


def features_of(
    record_a_norm: Mapping[str, Any] | Normalized, record_b_norm: Mapping[str, Any] | Normalized
) -> FeatureVector:
    """Features only (for the evaluation harness' ablations); same coercion as ``match``."""
    return compute_features(coerce_normalized(record_a_norm), coerce_normalized(record_b_norm))
