"""Choosing the operating point, false-merge first (eval plan section 5; architecture section 6).

On out-of-fold development raw scores:
    curve  = monotone envelope of FP_auto(c) / N_auto(c) (see ``_envelope``)
    c_high = smallest c with curve(c) <= alpha and auto-links at c drawn from >= min_components
             fallback if unreachable: the c with the lowest envelope value among c meeting the floor
    c_low  = largest c with missed_true(c) / N_true_blocked <= beta and review_burden <= max burden
             if impossible, the failed constraint is reported
The envelope value is descriptive, never a guarantee.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from eval.harness.metrics import ScoredPair


@dataclass(frozen=True)
class ThresholdConfig:
    alpha: float = 0.01
    beta: float = 0.02
    min_components: int = 50
    review_burden_max: float = 0.20


@dataclass
class ThresholdSelection:
    c_low: float
    c_high: float
    alpha: float
    beta: float
    min_components: int
    review_burden_max: float
    envelope_at_c_high: float | None
    components_at_c_high: int
    auto_links_at_c_high: int
    c_high_fallback_used: bool
    c_high_reachable: bool
    c_low_constraint_failed: str | None
    missed_true_rate_at_c_low: float | None
    review_burden_at_c_low: float | None
    note: str

    def as_json(self) -> dict:
        return asdict(self)


def _candidates(pairs: Sequence[ScoredPair]) -> list[float]:
    scores = sorted({p.raw_score for p in pairs})
    if not scores:
        return []
    # cutoffs sit at each observed score and one step above the top so "no auto-links" is a candidate
    return scores + [scores[-1] + 1.0]


def _auto_at(pairs: Sequence[ScoredPair], c: float) -> list[ScoredPair]:
    return [p for p in pairs if p.raw_score >= c and not p.negative_rules_fired]


def _envelope(raw_rate: list[float | None], autos: list[int], comps: list[int],
              cfg: ThresholdConfig) -> list[float | None]:
    """Monotone envelope from the right over the cutoffs whose rate can be trusted.

    envelope(c) = max(rate(c), max of rate(c') over every c' > c that is *resolvable*). A cutoff is
    resolvable when it meets the component support floor and holds at least ceil(1 / alpha) auto-links,
    so one event moves its rate by no more than alpha. That keeps the envelope's purpose (a lucky dip
    at a low c cannot win while a resolvable higher cutoff is dirtier) without letting one false pair
    in a thin top region (n = 1, or 81 auto-links where one event is 1.2%) make alpha unreachable at
    every cutoff below it (R5 #3). Derived from alpha and the floor; no new threshold value.
    """
    resolve_n = math.ceil(1.0 / cfg.alpha) if cfg.alpha > 0 else 1
    envelope: list[float | None] = [None] * len(raw_rate)
    running: float | None = None
    for i in range(len(raw_rate) - 1, -1, -1):
        own = raw_rate[i]
        if own is not None:
            envelope[i] = own if running is None else max(running, own)
        resolvable = own is not None and comps[i] >= cfg.min_components and autos[i] >= resolve_n
        if resolvable:
            running = own if running is None else max(running, own)
    return envelope


def select_thresholds(pairs: Sequence[ScoredPair], cfg: ThresholdConfig | None = None) -> ThresholdSelection:
    cfg = cfg or ThresholdConfig()
    if not pairs:
        raise ValueError("no out-of-fold pairs to choose thresholds on")
    cuts = _candidates(pairs)
    raw_rate: list[float | None] = []
    comps: list[int] = []
    autos: list[int] = []
    for c in cuts:
        auto = _auto_at(pairs, c)
        autos.append(len(auto))
        comps.append(len({k for p in auto for k in p.components}))
        raw_rate.append((sum(1 for p in auto if not p.is_match) / len(auto)) if auto else None)
    supported = [i for i in range(len(cuts)) if comps[i] >= cfg.min_components and raw_rate[i] is not None]
    envelope = _envelope(raw_rate, autos, comps, cfg)
    reachable = [i for i in supported if envelope[i] <= cfg.alpha]
    fallback = False
    if reachable:
        hi = reachable[0]
        note = "c_high: smallest c with envelope <= alpha at the support floor"
    elif supported:
        hi = min(supported, key=lambda i: (envelope[i], -i))
        fallback = True
        note = "c_high fallback: alpha unreachable at the support floor; lowest envelope value reported as such"
    else:
        hi = len(cuts) - 1
        fallback = True
        note = "c_high unreachable: no cutoff meets the component support floor; no auto-links"
    c_high = cuts[hi]
    true_blocked = [p for p in pairs if p.is_match]
    n_true = len(true_blocked)
    n_pairs = len(pairs)
    c_low = cuts[0]
    failed: str | None = None
    chosen = None
    for i in range(len(cuts) - 1, -1, -1):
        c = cuts[i]
        if c > c_high:
            continue
        missed = sum(1 for p in true_blocked if p.raw_score < c) / n_true if n_true else 0.0
        review = sum(1 for p in pairs if c <= p.raw_score < c_high or (p.raw_score >= c_high and p.negative_rules_fired))
        burden = review / n_pairs
        if missed <= cfg.beta and burden <= cfg.review_burden_max:
            chosen = (c, missed, burden)
            break
    if chosen is None:
        # report the failed constraint and fall back to the largest c meeting beta alone, else the floor
        for i in range(len(cuts) - 1, -1, -1):
            c = cuts[i]
            if c > c_high:
                continue
            missed = sum(1 for p in true_blocked if p.raw_score < c) / n_true if n_true else 0.0
            if missed <= cfg.beta:
                review = sum(1 for p in pairs if c <= p.raw_score < c_high or (p.raw_score >= c_high and p.negative_rules_fired))
                chosen = (c, missed, review / n_pairs)
                failed = f"review_burden <= {cfg.review_burden_max} unreachable with missed_true <= {cfg.beta}"
                break
        if chosen is None:
            c = min(cuts[0], c_high)
            missed = sum(1 for p in true_blocked if p.raw_score < c) / n_true if n_true else 0.0
            review = sum(1 for p in pairs if c <= p.raw_score < c_high or (p.raw_score >= c_high and p.negative_rules_fired))
            chosen = (c, missed, review / n_pairs)
            failed = f"missed_true <= {cfg.beta} unreachable; c_low set to the lowest observed score"
    c_low, missed_rate, burden = chosen
    return ThresholdSelection(
        c_low=c_low, c_high=c_high, alpha=cfg.alpha, beta=cfg.beta, min_components=cfg.min_components,
        review_burden_max=cfg.review_burden_max, envelope_at_c_high=envelope[hi], components_at_c_high=comps[hi],
        auto_links_at_c_high=autos[hi], c_high_fallback_used=fallback, c_high_reachable=bool(reachable),
        c_low_constraint_failed=failed, missed_true_rate_at_c_low=missed_rate, review_burden_at_c_low=burden,
        note=note + "; development, descriptive; configuration, not clinical thresholds",
    )
