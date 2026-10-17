"""Metrics (eval plan section 5): per-band precision and recall with n as pairs, entities and
components; blocking recall; reduction ratio; review burden; false-merge rate; one interval method
(percentile bootstrap over dependency components, seeded resamples); the support floor.
"""
from __future__ import annotations

import itertools
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from eval.harness.types import BAND_AUTO_LINK, BAND_KEEP_SEPARATE, BAND_REVIEW, BANDS, band_for

SUPPORT_FLOOR_COMPONENTS = 50       # architecture section 6: never a headline below this
DO_NOT_READ_COMPONENTS = 30         # eval plan section 5: flagged "do not read"
DO_NOT_READ_PAIRS = 100
BOOTSTRAP_RESAMPLES = 1000
CI_LOW, CI_HIGH = 0.025, 0.975


@dataclass(frozen=True)
class ScoredPair:
    """One blocked pair with its out-of-fold raw score and the truth."""

    record_a: str
    record_b: str
    entity_a: str
    entity_b: str
    component_a: str
    component_b: str
    raw_score: float
    p: float
    negative_rules_fired: tuple[str, ...]
    categories: tuple[str, ...] = ()

    @property
    def is_match(self) -> bool:
        return self.entity_a == self.entity_b

    @property
    def components(self) -> tuple[str, ...]:
        return (self.component_a,) if self.component_a == self.component_b else (self.component_a, self.component_b)

    @property
    def entities(self) -> tuple[str, ...]:
        return (self.entity_a,) if self.is_match else (self.entity_a, self.entity_b)

    def band(self, c_low: float, c_high: float) -> str:
        return band_for(self.raw_score, c_low, c_high, self.negative_rules_fired)


def support(pairs: Iterable[ScoredPair]) -> dict[str, int]:
    pairs = list(pairs)
    entities = {e for p in pairs for e in p.entities}
    components = {c for p in pairs for c in p.components}
    return {"n_pairs": len(pairs), "n_entities": len(entities), "n_components": len(components)}


def _weighted_rate(numer: Sequence[ScoredPair], denom: Sequence[ScoredPair], counts: dict[str, int]) -> float | None:
    """A pair inside one component takes that component's draw count; a cross-component pair takes
    the product of both endpoints' draw counts (eval plan section 5)."""

    def weight(p: ScoredPair) -> int:
        if p.component_a == p.component_b:
            return counts.get(p.component_a, 0)
        return counts.get(p.component_a, 0) * counts.get(p.component_b, 0)

    d = sum(weight(p) for p in denom)
    if d == 0:
        return None
    return sum(weight(p) for p in numer) / d


def bootstrap_ci(numer: Sequence[ScoredPair], denom: Sequence[ScoredPair], seed: int,
                 resamples: int = BOOTSTRAP_RESAMPLES) -> list[float] | None:
    """Percentile grouped bootstrap over dependency components. Returns ``[low, high]`` or None when
    the denominator is empty. The resampling unit is the component."""
    components = sorted({c for p in denom for c in p.components})
    if not components or not denom:
        return None
    rng = random.Random(seed)
    values: list[float] = []
    n = len(components)
    for _ in range(resamples):
        counts: dict[str, int] = {}
        for _ in range(n):
            c = components[rng.randrange(n)]
            counts[c] = counts.get(c, 0) + 1
        rate = _weighted_rate(numer, denom, counts)
        if rate is not None:
            values.append(rate)
    if not values:
        return None
    values.sort()
    return [_percentile(values, CI_LOW), _percentile(values, CI_HIGH)]


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def rate(numer: Sequence[ScoredPair], denom: Sequence[ScoredPair], seed: int, resamples: int = BOOTSTRAP_RESAMPLES,
         with_ci: bool = True) -> dict:
    """A published number: value, n as pairs/entities/components, the interval and the support flags.
    Zero observed events print no upper bound (eval plan section 5)."""
    sup = support(denom)
    value = (len(numer) / len(denom)) if denom else None
    zero_events = bool(denom) and len(numer) == 0
    out = {
        "value": value,
        **sup,
        "ci95": None,
        "low_support": sup["n_components"] < SUPPORT_FLOOR_COMPONENTS,
        "do_not_read": sup["n_components"] < DO_NOT_READ_COMPONENTS or sup["n_pairs"] < DO_NOT_READ_PAIRS,
        "zero_events": zero_events,
    }
    if zero_events:
        out["note"] = "zero observed; insufficient independent evidence for a tight pair-error bound"
    elif with_ci and denom:
        out["ci95"] = bootstrap_ci(numer, denom, seed, resamples)
    return out


def count(pairs: Sequence[ScoredPair]) -> dict:
    return {"value": len(pairs), **support(pairs)}


def band_metrics(pairs: Sequence[ScoredPair], true_pairs_total: int, c_low: float, c_high: float, seed: int,
                 resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, dict]:
    """Per-band precision and recall (the PRD wording), STRICT and LENIENT, false-merge rate,
    review burden, missed-match rate. ``true_pairs_total`` is |P| so blocking misses count as misses."""
    by_band: dict[str, list[ScoredPair]] = {b: [] for b in BANDS}
    for p in pairs:
        by_band[p.band(c_low, c_high)].append(p)
    true_blocked = [p for p in pairs if p.is_match]
    all_true = _phantom_true_pairs(true_blocked, true_pairs_total)
    auto, review, keep = by_band[BAND_AUTO_LINK], by_band[BAND_REVIEW], by_band[BAND_KEEP_SEPARATE]
    auto_true = [p for p in auto if p.is_match]
    review_true = [p for p in review if p.is_match]
    keep_true = [p for p in keep if p.is_match]
    out: dict[str, dict] = {}
    for band, members in by_band.items():
        key = band.lower()
        out[f"band.{key}.count"] = count(members)
        out[f"band.{key}.precision"] = rate([p for p in members if p.is_match], members, seed, resamples)
        out[f"band.{key}.true_pair_share"] = rate([p for p in members if p.is_match], true_blocked, seed, resamples)
    out["false_merge_rate"] = rate([p for p in auto if not p.is_match], auto, seed, resamples)
    out["recall.strict.scorer"] = rate(auto_true, true_blocked, seed, resamples)
    out["recall.lenient.scorer"] = rate(auto_true + review_true, true_blocked, seed, resamples)
    out["recall.strict.end_to_end"] = rate(auto_true, all_true, seed, resamples)
    out["recall.lenient.end_to_end"] = rate(auto_true + review_true, all_true, seed, resamples)
    out["missed_match_rate.scorer"] = rate(keep_true, true_blocked, seed, resamples)
    out["review_burden"] = rate(review, pairs, seed, resamples)
    out["review.true_match_share"] = rate(review_true, review, seed, resamples)
    out["review.items_per_1000_pairs"] = {"value": (len(review) / len(pairs) * 1000) if pairs else None,
                                          **support(review)}
    return out


def _phantom_true_pairs(true_blocked: Sequence[ScoredPair], true_pairs_total: int) -> list[ScoredPair]:
    """End-to-end denominators include true pairs blocking missed. They enter with the component of a
    neighbour so the bootstrap keeps the right support; their score is -inf so they are never counted."""
    missed = true_pairs_total - len(true_blocked)
    phantoms: list[ScoredPair] = []
    for i in range(max(missed, 0)):
        anchor = true_blocked[i % len(true_blocked)] if true_blocked else None
        comp = anchor.component_a if anchor else f"missed:{i}"
        ent = anchor.entity_a if anchor else f"missed:{i}"
        phantoms.append(ScoredPair(f"missed:{i}", f"missed:{i}", ent, ent, comp, comp, float("-inf"), 0.0, ()))
    return list(true_blocked) + phantoms


def blocking_metrics(true_pairs: set[tuple[str, str]], blocked_pairs: set[tuple[str, str]], all_pairs_n: int) -> dict:
    """Blocking recall |P ∩ B| / |P| and reduction ratio 1 − |B| / N, quoted with N."""
    hit = len(true_pairs & blocked_pairs)
    return {
        "blocking.recall": {"value": (hit / len(true_pairs)) if true_pairs else None, "n_true_pairs": len(true_pairs),
                            "n_hit": hit, "note": "keys were built after reading the taxonomy; partly by construction"},
        "blocking.reduction_ratio": {"value": (1 - len(blocked_pairs) / all_pairs_n) if all_pairs_n else None,
                                     "n_blocked": len(blocked_pairs), "N": all_pairs_n},
    }


def check_monotone(g: Callable[[float], float], raw_scores: Sequence[float]) -> bool:
    """A display map must be strictly increasing on the observed raw scores (section 5 contract)."""
    xs = sorted(set(raw_scores))
    ys = [g(x) for x in xs]
    return all(b > a for a, b in itertools.pairwise(ys))


def check_band_agreement(pairs: Sequence[ScoredPair], c_low: float, c_high: float,
                         g: Callable[[float], float]) -> bool:
    """band(p, T) must equal band(s, c) on every row, with T = g(c)."""
    t_low, t_high = g(c_low), g(c_high)
    for p in pairs:
        by_p = band_for(g(p.raw_score), t_low, t_high, p.negative_rules_fired)
        if by_p != p.band(c_low, c_high):
            return False
    return True


def percentiles_ms(samples: Sequence[float]) -> dict:
    xs = sorted(samples)
    if not xs:
        return {"p50_ms": None, "p95_ms": None, "p99_ms": None, "n": 0}
    return {"p50_ms": _percentile(xs, 0.50), "p95_ms": _percentile(xs, 0.95), "p99_ms": _percentile(xs, 0.99),
            "n": len(xs)}
