"""Threshold selection: false-merge first, the support floor, the documented fallback."""
from __future__ import annotations

import pytest

from eval.harness.metrics import ScoredPair
from eval.harness.thresholds import ThresholdConfig, select_thresholds


def sp(i, s, match, comp=None, rules=()):
    e = f"E{i}" if match else f"E{i}x"
    c = comp or f"C{i}"
    return ScoredPair(f"a{i}", f"b{i}", f"E{i}", e, c, c if match else f"{c}y", s, 0.5, tuple(rules))


def _separable(n=120):
    # true pairs score 2..6, false pairs score -3..1 except one false at 3.0 (a lucky noisy region)
    rows = [sp(i, 2.0 + (i % 5), True) for i in range(n)]
    rows += [sp(1000 + i, -3.0 + (i % 5), False) for i in range(n)]
    rows.append(sp(5000, 3.0, False))
    return rows


def test_c_high_reaches_alpha_at_the_support_floor():
    sel = select_thresholds(_separable(), ThresholdConfig(alpha=0.01, beta=0.02, min_components=50))
    assert sel.c_high_reachable and not sel.c_high_fallback_used
    assert sel.components_at_c_high >= 50
    # c = 3 holds 97 auto-links with one false (1.03%), too few to resolve alpha, so it does not enter the
    # envelope of lower cutoffs; c = 2 holds 121 auto-links with the same false pair: 0.83% <= alpha
    assert sel.c_high == 2.0
    assert sel.envelope_at_c_high == pytest.approx(1 / 121)
    assert sel.c_low <= sel.c_high


def test_lucky_dip_under_a_resolvable_dirty_region_is_not_picked():
    # 100 clean pairs at 6; 48 true + 2 false at 5 (1.33% at c=5, 150 auto-links, resolvable);
    # 100 clean pairs at 4 dilute the rate at c=4 to 0.8%. The envelope keeps c=4 and c=5 above alpha.
    rows = [sp(i, 6.0, True) for i in range(100)]
    rows += [sp(200 + i, 5.0, True) for i in range(48)] + [sp(400 + i, 5.0, False) for i in range(2)]
    rows += [sp(600 + i, 4.0, True) for i in range(100)]
    sel = select_thresholds(rows, ThresholdConfig(alpha=0.01, min_components=50))
    assert sel.c_high_reachable and sel.c_high == 6.0 and sel.envelope_at_c_high == 0.0


def test_support_floor_forces_fallback_when_too_few_components():
    # 30 true components plus two components behind every false pair: no cutoff ever reaches 50
    rows = [sp(i, 2.0 + (i % 5), True) for i in range(30)]
    rows += [sp(1000 + i, -3.0 + (i % 5), False, comp="Cf") for i in range(30)]
    sel = select_thresholds(rows, ThresholdConfig(alpha=0.01, min_components=50))
    assert not sel.c_high_reachable and sel.c_high_fallback_used
    assert sel.auto_links_at_c_high == 0
    assert "unreachable" in sel.note


def test_fallback_picks_lowest_envelope_when_alpha_unreachable():
    # 10% of auto-links are false everywhere above the floor: alpha 0.01 is unreachable
    rows = [sp(i, 3.0, True) for i in range(90)] + [sp(900 + i, 3.0, False) for i in range(10)]
    sel = select_thresholds(rows, ThresholdConfig(alpha=0.01, min_components=50))
    assert sel.c_high_fallback_used and not sel.c_high_reachable
    assert sel.envelope_at_c_high == pytest.approx(0.10)
    assert sel.components_at_c_high >= 50


def test_c_low_reports_failed_constraint():
    # every true pair sits in a wide band of scores, so beta and the burden cap cannot both hold
    rows = [sp(i, -2.0 + 4.0 * i / 99, True) for i in range(100)]
    rows += [sp(500 + i, -2.0 + 4.0 * i / 99, False) for i in range(100)]
    sel = select_thresholds(rows, ThresholdConfig(alpha=0.01, beta=0.02, min_components=50, review_burden_max=0.20))
    assert sel.c_low_constraint_failed is not None
    assert sel.missed_true_rate_at_c_low <= 0.02 or "unreachable" in sel.c_low_constraint_failed


def test_demoted_pairs_never_count_as_auto_links():
    rows = [sp(i, 5.0, True) for i in range(60)] + [sp(900 + i, 5.0, False, rules=("TWIN",)) for i in range(20)]
    sel = select_thresholds(rows, ThresholdConfig(alpha=0.01, min_components=50))
    assert sel.c_high_reachable and sel.envelope_at_c_high == 0.0


def test_empty_input_rejected():
    with pytest.raises(ValueError):
        select_thresholds([])
