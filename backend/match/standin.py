"""STAND-IN for lane W2's matching core. Delete when ``backend.core.api.CORE`` lands.

It exists so the API routes, the review state machine and the tiles can be built and
tested before the real features and scorer merge. Shapes are the real ones (the frozen
``EvidenceSnapshot``); the numbers are not: string similarity is ``difflib`` instead of
Jaro-Winkler, weights are hand-set, and only two negative rules are implemented.
Nothing here is calibrated or evaluated. ``scorer_version`` says so.
"""

from __future__ import annotations

import math
import re
from datetime import date
from difflib import SequenceMatcher

from backend.match.seam import BlockKey, MatchResult, Thresholds
from contracts.models.common import Band, Contribution, NegativeRule
from contracts.models.pairs import EvidenceSnapshot
from contracts.models.records import NormalizedRecord

SCORER_VERSION = "standin-scorer-w3a-0"

# Hand-set logistic weights on features in [0,1]; the hero fixture lands in REVIEW under
# the current threshold row (raw score about 1.2; provisional-1 is c_low 0.0, c_high 4.0). A missing
# feature contributes 0.
WEIGHTS: dict[str, float] = {
    "given_name_jw": 1.0,
    "family_name_jw": 1.0,
    "dob_exact": 1.5,
    "dob_day_month_swap": 1.0,
    "sex_match": 0.25,
    "phone_match": 0.75,
    "address_jaccard": 0.75,
    "zip_match": 0.5,
}
INTERCEPT = -4.5
BIRTH_YEAR_GAP_MAX = 2  # BIRTH_YEAR_GAP_GT_2

PLACEHOLDER_NAME_RE = re.compile(r"placeholder|^(unknown|test|patient|baby|boy|girl)$", re.IGNORECASE)
PLACEHOLDER_DOBS = frozenset({date(1900, 1, 1), date(1901, 1, 1), date(1970, 1, 1)})
PLACEHOLDER_PHONE_RE = re.compile(r"^\+?1?(\d)\1{6,}$|^\+?1?55501\d{2}$")  # one repeated digit, or 555-01xx


def _is_placeholder_name(name: str | None) -> bool:
    return not name or bool(PLACEHOLDER_NAME_RE.search(name))


def _is_placeholder_phone(phone: str | None) -> bool:
    return not phone or bool(PLACEHOLDER_PHONE_RE.match(phone))


def _swap_day_month(d: date) -> date | None:
    try:
        return date(d.year, d.day, d.month)
    except ValueError:
        return None


def _similarity(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return SequenceMatcher(None, a, b).ratio()


def _equal(a, b) -> float | None:
    if a is None or b is None or a == "" or b == "":
        return None
    return 1.0 if a == b else 0.0


def _jaccard(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    ta, tb = set(a.lower().split()), set(b.lower().split())
    if not ta or not tb:
        return None
    return len(ta & tb) / len(ta | tb)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class StandInCore:
    scorer_version = SCORER_VERSION

    def block_keys(self, record: NormalizedRecord) -> list[BlockKey]:
        keys: list[BlockKey] = []
        family = record.family_name_folded or record.family_name
        if record.birth_date and not _is_placeholder_name(family):
            alnum = re.sub(r"[^a-z]", "", family.lower())
            if alnum:
                keys.append(BlockKey("family_year", f"{alnum}:{record.birth_date.year}"))
        if record.birth_date and record.birth_date not in PLACEHOLDER_DOBS:
            keys.append(BlockKey("dob", record.birth_date.isoformat()))
            swapped = _swap_day_month(record.birth_date)
            if swapped and swapped != record.birth_date:
                # the exact-DOB key type also stores the day/month-swapped value (architecture §4)
                keys.append(BlockKey("dob", swapped.isoformat()))
        if not _is_placeholder_phone(record.phone_e164):
            digits = re.sub(r"\D", "", record.phone_e164 or "")
            if len(digits) >= 7:
                keys.append(BlockKey("phone7", digits[-7:]))
        given = record.given_name_folded or record.given_name
        if record.zip5 and not _is_placeholder_name(given):
            keys.append(BlockKey("zip_initial", f"{record.zip5}:{given[0].lower()}"))
        return keys

    def match(self, a: NormalizedRecord, b: NormalizedRecord, thresholds: Thresholds) -> MatchResult:
        features = self._features(a, b)
        contributions = [
            Contribution(feature=f, logit=(0.0 if features[f] is None else WEIGHTS[f] * features[f]), value=features[f])
            for f in WEIGHTS
        ]
        raw = INTERCEPT + sum(c.logit for c in contributions)
        rules = self._negative_rules(a, b)
        band = band_for(raw, thresholds.c_low, thresholds.c_high, rules)
        p = _sigmoid(raw)  # display-only; no Platt map exists for the stand-in
        evidence = EvidenceSnapshot(
            features=features,
            missing_flags={f: features[f] is None for f in WEIGHTS},
            weights=dict(WEIGHTS),
            intercept=INTERCEPT,
            contributions=contributions,
            raw_score=raw,
            c_low=thresholds.c_low,
            c_high=thresholds.c_high,
            platt_a=thresholds.platt_a,
            platt_b=thresholds.platt_b,
            t_low_display=thresholds.t_low_display,
            t_high_display=thresholds.t_high_display,
            negative_rules_fired=[r.value for r in rules],
            scorer_version=self.scorer_version,
            threshold_set_id=thresholds.threshold_set_id,
        )
        return MatchResult(evidence=evidence, logit=raw, p=p, band=band)

    @staticmethod
    def _features(a: NormalizedRecord, b: NormalizedRecord) -> dict[str, float | None]:
        dob_exact = _equal(a.birth_date, b.birth_date)
        swap: float | None = None
        if a.birth_date and b.birth_date:
            swapped = _swap_day_month(a.birth_date)
            swap = 1.0 if (dob_exact == 0.0 and swapped is not None and swapped == b.birth_date) else 0.0
        return {
            "given_name_jw": _similarity(a.given_name_folded or a.given_name, b.given_name_folded or b.given_name),
            "family_name_jw": _similarity(a.family_name_folded or a.family_name, b.family_name_folded or b.family_name),
            "dob_exact": dob_exact,
            "dob_day_month_swap": swap,
            "sex_match": _equal(a.sex, b.sex),
            "phone_match": _equal(a.phone_e164, b.phone_e164),
            "address_jaccard": _jaccard(a.address_line, b.address_line),
            "zip_match": _equal(a.zip5, b.zip5),
        }

    @staticmethod
    def _negative_rules(a: NormalizedRecord, b: NormalizedRecord) -> list[NegativeRule]:
        rules: list[NegativeRule] = []
        if a.sex and b.sex and a.sex != b.sex:
            rules.append(NegativeRule.SEX_CONFLICT)
        if a.birth_date and b.birth_date and abs(a.birth_date.year - b.birth_date.year) > BIRTH_YEAR_GAP_MAX:
            rules.append(NegativeRule.BIRTH_YEAR_GAP_GT_2)
        return rules


def band_for(raw_score: float, c_low: float, c_high: float, rules_fired: list) -> Band:
    """Architecture §6: cut on the raw score; a negative rule demotes AUTO_LINK to REVIEW only."""
    if raw_score < c_low:
        return Band.KEEP_SEPARATE
    if raw_score < c_high:
        return Band.REVIEW
    return Band.REVIEW if rules_fired else Band.AUTO_LINK
