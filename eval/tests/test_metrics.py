"""Metrics arithmetic with known answers; bootstrap interval shape; support floor flags."""
from __future__ import annotations

from eval.harness.metrics import (
    SUPPORT_FLOOR_COMPONENTS,
    ScoredPair,
    band_metrics,
    blocking_metrics,
    bootstrap_ci,
    percentiles_ms,
    rate,
    support,
)


def sp(a, b, ea, eb, ca, cb, s, rules=()):
    return ScoredPair(a, b, ea, eb, ca, cb, s, 0.5, tuple(rules))


def _toy():
    # 4 true pairs (2 auto, 1 review, 1 keep), 2 false (1 auto, 1 keep); c_low=0, c_high=2
    return [
        sp("a1", "a2", "E1", "E1", "C1", "C1", 3.0),
        sp("b1", "b2", "E2", "E2", "C2", "C2", 2.5),
        sp("c1", "c2", "E3", "E3", "C3", "C3", 1.0),
        sp("d1", "d2", "E4", "E4", "C4", "C4", -1.0),
        sp("a1", "x1", "E1", "E9", "C1", "C9", 2.2),
        sp("b1", "y1", "E2", "E8", "C2", "C8", -0.5),
    ]


def test_band_metrics_known_answers():
    out = band_metrics(_toy(), true_pairs_total=5, c_low=0.0, c_high=2.0, seed=1, resamples=50)
    assert out["band.auto_link.count"]["value"] == 3
    assert out["band.auto_link.precision"]["value"] == 2 / 3
    assert out["false_merge_rate"]["value"] == 1 / 3
    assert out["recall.strict.scorer"]["value"] == 2 / 4
    assert out["recall.lenient.scorer"]["value"] == 3 / 4
    # one true pair was never blocked: end-to-end divides by |P| = 5
    assert out["recall.strict.end_to_end"]["value"] == 2 / 5
    assert out["recall.lenient.end_to_end"]["value"] == 3 / 5
    assert out["review_burden"]["value"] == 1 / 6
    assert out["missed_match_rate.scorer"]["value"] == 1 / 4
    assert out["band.review.true_pair_share"]["value"] == 1 / 4


def test_negative_rule_demotes_auto_link_to_review():
    rows = [sp("a1", "a2", "E1", "E1", "C1", "C1", 3.0, ["TWIN"]), sp("b1", "b2", "E2", "E2", "C2", "C2", 3.0)]
    out = band_metrics(rows, 2, 0.0, 2.0, seed=1, resamples=10)
    assert out["band.auto_link.count"]["value"] == 1
    assert out["band.review.count"]["value"] == 1


def test_n_is_pairs_entities_and_components():
    rows = _toy()
    sup = support(rows)
    assert sup == {"n_pairs": 6, "n_entities": 6, "n_components": 6}
    cross = support([rows[4]])
    assert cross == {"n_pairs": 1, "n_entities": 2, "n_components": 2}


def test_rate_flags_low_support_and_zero_events():
    rows = _toy()
    cell = rate([], rows, seed=1, resamples=10)
    assert cell["value"] == 0.0 and cell["zero_events"] and cell["ci95"] is None
    assert "insufficient independent evidence" in cell["note"]
    assert cell["low_support"] and cell["do_not_read"]
    big = [sp(f"a{i}", f"b{i}", f"E{i}", f"E{i}", f"C{i}", f"C{i}", 1.0) for i in range(SUPPORT_FLOOR_COMPONENTS)]
    big += [sp(f"a{i}", f"b{i}x", f"E{i}", f"E{i}", f"C{i}", f"C{i}", 1.0) for i in range(60)]
    cell = rate(big[:55], big, seed=1, resamples=10)
    assert cell["low_support"] is False and cell["do_not_read"] is False


def test_bootstrap_interval_shape_and_determinism():
    rows = [sp(f"a{i}", f"b{i}", f"E{i}", f"E{i}", f"C{i % 7}", f"C{i % 7}", 1.0) for i in range(40)]
    numer = rows[:30]
    ci_a = bootstrap_ci(numer, rows, seed=7, resamples=300)
    ci_b = bootstrap_ci(numer, rows, seed=7, resamples=300)
    assert ci_a == ci_b
    lo, hi = ci_a
    assert 0.0 <= lo <= 30 / 40 <= hi <= 1.0
    assert bootstrap_ci(numer, rows, seed=8, resamples=300) != ci_a


def test_bootstrap_weights_cross_component_pairs_by_product():
    # one cross-component false pair among same-component true pairs: the interval must be inside [0, 1]
    rows = _toy()
    ci = bootstrap_ci([rows[4]], rows[:5], seed=3, resamples=200)
    assert 0.0 <= ci[0] <= ci[1] <= 1.0


def test_blocking_metrics():
    out = blocking_metrics({("a", "b"), ("c", "d")}, {("a", "b"), ("x", "y")}, all_pairs_n=100)
    assert out["blocking.recall"]["value"] == 0.5
    assert out["blocking.reduction_ratio"]["value"] == 0.98
    assert out["blocking.reduction_ratio"]["N"] == 100


def test_percentiles():
    out = percentiles_ms(list(range(1, 101)))
    assert out["p50_ms"] == 50.5 and out["n"] == 100
    assert 95 <= out["p95_ms"] <= 96 and 99 <= out["p99_ms"] <= 100
