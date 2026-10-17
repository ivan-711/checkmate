"""S5 score: a logistic scorer whose evidence is the per-feature logit contribution.

``raw_score`` (the logit) is what decides bands (section 6). ``p`` is display-only: either the
plain sigmoid of the logit or, once Q5 fits one, the development Platt map. ``is_calibrated``
is False on every result; "calibrated" is a word the UI may use only beside a held-out ECE
interval (evaluation plan section 5), never because a fit succeeded.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.core.features import FEATURE_NAMES, MISSING_NAMES, MISSING_PREFIX, FeatureVector
from contracts.models.common import Contribution

ALL_WEIGHT_NAMES: tuple[str, ...] = FEATURE_NAMES + MISSING_NAMES
WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"
# handset-1 replaced handset-0 when the capped nickname credit and the punctuation fold changed some
# scores; evidence snapshots and the harness record this string, so the name must change with them.
HANDSET_SCORER_VERSION = "handset-1"


@dataclass(frozen=True)
class Weights:
    """Feature weights + intercept under one ``scorer_version``; every weight name is required."""

    scorer_version: str
    intercept: float
    weights: Mapping[str, float]
    # scikit-learn's sigmoid calibrator convention: p = expit(-(a * s + b)); a < 0 means monotone.
    platt_a: float | None = None
    platt_b: float | None = None
    trained_on: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        expected, got = set(ALL_WEIGHT_NAMES), set(self.weights)
        if got != expected:
            missing, unknown = sorted(expected - got), sorted(got - expected)
            raise ValueError(f"weights for {self.scorer_version}: missing {missing}, unknown {unknown}")
        if (self.platt_a is None) != (self.platt_b is None):
            raise ValueError("platt_a and platt_b must be set together")
        if self.platt_a is not None and self.platt_a >= 0:
            # sklearn's sigmoid calibrator gives p = expit(-(a*s + b)); p increases in s only for a < 0
            # (evaluation plan section 5, contract item 3: asserted, not assumed).
            raise ValueError(f"platt_a must be negative so p increases in the raw score, got {self.platt_a}")
        object.__setattr__(self, "weights", dict(self.weights))

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "scorer_version": self.scorer_version,
            "intercept": self.intercept,
            "weights": {name: self.weights[name] for name in ALL_WEIGHT_NAMES},
            "platt_a": self.platt_a,
            "platt_b": self.platt_b,
            "trained_on": dict(self.trained_on),
        }

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> Weights:
        return cls(
            scorer_version=str(data["scorer_version"]),
            intercept=float(data["intercept"]),
            weights={k: float(v) for k, v in data["weights"].items()},
            platt_a=None if data.get("platt_a") is None else float(data["platt_a"]),
            platt_b=None if data.get("platt_b") is None else float(data["platt_b"]),
            trained_on=dict(data.get("trained_on") or {}),
        )


def save_weights(weights: Weights, path: Path) -> None:
    path.write_text(json.dumps(weights.to_json_dict(), indent=2, sort_keys=True) + "\n")


def load_weights(path_or_version: str | Path) -> Weights:
    """A path to a weights JSON, or a bare version name resolved under ``backend/core/weights``."""
    text = str(path_or_version)
    is_bare_version = isinstance(path_or_version, str) and "/" not in text and not text.endswith(".json")
    path = WEIGHTS_DIR / f"{text}.json" if is_bare_version else Path(path_or_version)
    return Weights.from_json_dict(json.loads(path.read_text()))


@dataclass(frozen=True)
class ScoreResult:
    raw_score: float
    p: float  # display-only
    contributions: tuple[Contribution, ...]
    scorer_version: str
    is_calibrated: bool = False
    p_is_display_only: bool = True


def sigmoid(x: float) -> float:
    # Split at zero so neither branch overflows for a large |x|.
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def display_probability(raw_score: float, weights: Weights) -> float:
    if weights.platt_a is None or weights.platt_b is None:
        return sigmoid(raw_score)
    return sigmoid(-(weights.platt_a * raw_score + weights.platt_b))


NICKNAME_FEATURE = "given_nickname"
# The given-name similarity features a nickname stands in for; an identical name scores 1.0 on each.
GIVEN_SIMILARITY_FEATURES: tuple[str, ...] = tuple(
    name for name in FEATURE_NAMES if name.startswith("given_") and name != NICKNAME_FEATURE
)


def capped_nickname_value(values: Mapping[str, float | None], weights: Weights) -> float | None:
    """The nickname feature's effective value: it may restore at most what the given name lost.

    A nickname pair ("Will" / "Willie") would otherwise earn its full credit on top of a near-identical
    spelling and outscore the unchanged name. Capping the credit at the gap to an identical given name
    leaves every pair that lost more than the credit (Bob/Robert, Paco/Francisco) untouched.
    """
    value = values.get(NICKNAME_FEATURE)
    weight = weights.weights[NICKNAME_FEATURE]
    if value is None or value == 0.0 or weight <= 0.0:
        return value
    identical = math.fsum(weights.weights[name] for name in GIVEN_SIMILARITY_FEATURES)
    actual = math.fsum(weights.weights[name] * (values.get(name) or 0.0) for name in GIVEN_SIMILARITY_FEATURES)
    room = max(0.0, identical - actual)
    return min(value, room / weight)


def score_pair(fv: FeatureVector, weights: Weights) -> ScoreResult:
    """Contributions are weight x value in logit space and sum to ``raw_score - intercept``.

    Each contribution's ``value`` is the value that was weighted; for ``given_nickname`` that is the
    capped value (``capped_nickname_value``), which can be below the raw feature in ``fv``.
    """
    contributions: list[Contribution] = []
    for name in FEATURE_NAMES:
        value = capped_nickname_value(fv.values, weights) if name == NICKNAME_FEATURE else fv.values.get(name)
        logit = 0.0 if value is None else weights.weights[name] * value
        contributions.append(Contribution(feature=name, logit=logit, value=value))
    for group, flag in fv.missing.items():
        name = MISSING_PREFIX + group
        value = 1.0 if flag else 0.0
        contributions.append(Contribution(feature=name, logit=weights.weights[name] * value, value=value))
    raw = weights.intercept + math.fsum(c.logit for c in contributions)
    return ScoreResult(
        raw_score=raw,
        p=display_probability(raw, weights),
        contributions=tuple(contributions),
        scorer_version=weights.scorer_version,
    )


# Hand-set weights for the 15:30 checkpoint, in logit units, under DEMO_THRESHOLDS (c_high 4.0):
# an identical full record scores +5.5; a day/month swap (4.7) or a one-digit day edit (4.3)
# stays AUTO_LINK; any year change (3.5 or lower) drops to REVIEW, which is the CHANGE_BIRTH_YEAR
# band-changer; siblings sharing surname, address and phone never reach AUTO_LINK. The trained
# scorer replaces these and they are never called calibrated. backend/core/weights/handset-1.json
# is this object on disk; a test keeps the two equal.
HANDSET_WEIGHTS = Weights(
    scorer_version=HANDSET_SCORER_VERSION,
    intercept=-11.0,
    weights={
        # The folded forms carry more weight than the accented ones so an accent or hyphen
        # variant loses little; the nickname table is the only way "Paco" reaches "Francisco".
        "given_jw": 1.0,
        "given_jw_folded": 1.5,
        "given_dl": 0.5,
        "given_dmeta": 0.5,
        "given_nickname": 1.5,
        "given_initial": 0.3,
        "given_token_overlap": 0.5,
        "family_jw": 1.0,
        "family_jw_folded": 1.5,
        "family_dl": 0.5,
        "family_dmeta": 0.7,
        "family_token_overlap": 0.8,
        # The named DOB edits keep most of the exact-match credit: the engine has a feature for
        # each, which is the point of the what-if buttons.
        "dob_exact": 3.0,
        "dob_day_month_swap": 2.2,
        "dob_one_digit_edit": 1.8,
        "dob_one_component_off": 1.2,
        "dob_year_match": 0.8,
        "sex_match": 0.6,
        "phone_match": 1.5,
        "address_jaccard": 1.2,
        "zip_match": 0.6,
        # Missing evidence costs a little, so an empty record cannot ride on a shared surname.
        "missing_given_name": -0.5,
        "missing_family_name": -0.5,
        "missing_dob": -1.0,
        "missing_sex": -0.1,
        "missing_phone": -0.3,
        "missing_address": -0.3,
        "missing_zip": -0.2,
    },
)
