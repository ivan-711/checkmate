"""Metrics (eval plan section 5): per-band precision and recall with n as pairs, entities and
components; blocking recall; reduction ratio; review burden; false-merge rate; one interval method
(percentile bootstrap over dependency components, seeded resamples); the support floor.
"""
from __future__ import annotations

import itertools
import random
from collections import Counter
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


def _aggregate(numer: Sequence[ScoredPair], denom: Sequence[ScoredPair]):
    """Per-component (numerator, denominator) pair counts, plus the cross-component pairs.

    A pair inside one component takes that component's draw count; a cross-component pair takes the
    product of both endpoints' draw counts (eval plan section 5), so both endpoints are resampled."""
    numer_keys = Counter((p.record_a, p.record_b, p.entity_a, p.entity_b) for p in numer)
    within: dict[str, list[int]] = {}
    cross: dict[tuple[str, str], list[int]] = {}
    for p in denom:
        hit = 1 if numer_keys[(p.record_a, p.record_b, p.entity_a, p.entity_b)] > 0 else 0
        if p.component_a == p.component_b:
            cell = within.setdefault(p.component_a, [0, 0])
        else:
            cell = cross.setdefault((p.component_a, p.component_b), [0, 0])
        cell[0] += hit
        cell[1] += 1
    return within, cross


def bootstrap_ci(numer: Sequence[ScoredPair], denom: Sequence[ScoredPair], seed: int,
                 resamples: int = BOOTSTRAP_RESAMPLES) -> list[float] | None:
    """Percentile grouped bootstrap over dependency components. Returns ``[low, high]`` or None when
    the denominator is empty. The resampling unit is the component; ``numer`` is a subset of ``denom``."""
    if not denom:
        return None
    within, cross = _aggregate(numer, denom)
    components = sorted({c for p in denom for c in p.components})
    rng = random.Random(seed)
    n = len(components)
    values: list[float] = []
    for _ in range(resamples):
        counts = Counter(rng.choices(components, k=n))
        num = den = 0
        for comp, (h, d) in within.items():
            k = counts.get(comp, 0)
            if k:
                num += k * h
                den += k * d
        for (ca, cb), (h, d) in cross.items():
            k = counts.get(ca, 0) * counts.get(cb, 0)
            if k:
                num += k * h
                den += k * d
        if den:
            values.append(num / den)
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


def band_metrics(pairs: Sequence[ScoredPair], missed_true: Sequence[ScoredPair], c_low: float, c_high: float,
                 seed: int, resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, dict]:
    """Per-band precision and recall (the PRD wording), STRICT and LENIENT, false-merge rate,
    review burden, missed-match rate. ``missed_true`` are the true pairs blocking never proposed, each
    with its own entities and components, so end-to-end recall counts them as misses (|P| denominator)."""
    by_band: dict[str, list[ScoredPair]] = {b: [] for b in BANDS}
    for p in pairs:
        by_band[p.band(c_low, c_high)].append(p)
    true_blocked = [p for p in pairs if p.is_match]
    all_true = list(true_blocked) + list(missed_true)
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


def blocking_metrics(true_pairs: Sequence[ScoredPair], blocked: set[tuple[str, str]], all_pairs_n: int,
                     seed: int, resamples: int = BOOTSTRAP_RESAMPLES) -> dict:
    """Blocking recall |P ∩ B| / |P| (a rate with n and its interval) and reduction ratio 1 − |B| / N, quoted with N."""
    hits = [p for p in true_pairs if (p.record_a, p.record_b) in blocked or (p.record_b, p.record_a) in blocked]
    recall = rate(hits, true_pairs, seed, resamples)
    recall.update(n_true_pairs=len(true_pairs), n_hit=len(hits),
                  note="keys were built after reading the taxonomy; partly by construction")
    return {
        "blocking.recall": recall,
        "blocking.reduction_ratio": {"value": (1 - len(blocked) / all_pairs_n) if all_pairs_n else None,
                                     "n_blocked": len(blocked), "N": all_pairs_n},
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
