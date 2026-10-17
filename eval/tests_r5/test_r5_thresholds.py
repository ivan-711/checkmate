"""R5: threshold selection (eval plan 5; architecture 6): fallback, c_high >= c_low, band agreement, envelope."""
from __future__ import annotations

import random

from eval.harness.metrics import ScoredPair, check_band_agreement
from eval.harness.standin import display_p
from eval.harness.thresholds import ThresholdConfig, select_thresholds
from eval.harness.types import band_for


def sp(i, s, match, comp=None, rules=()):
    e = f"E{i}" if match else f"E{i}x"
    c = comp or f"C{i}"
    return ScoredPair(f"a{i}", f"b{i}", f"E{i}", e, c, c if match else f"{c}y", s, 0.5, tuple(rules))


def test_alpha_unreachable_uses_the_documented_fallback_and_records_it():
    # tiny truth table: every supported cutoff has 5% false auto-links, so alpha = 1% is unreachable
    rows = [sp(i, 4.0, True) for i in range(95)] + [sp(900 + i, 4.0, False) for i in range(5)]
    sel = select_thresholds(rows, ThresholdConfig(alpha=0.01, min_components=50))
    assert sel.c_high_fallback_used is True and sel.c_high_reachable is False
    assert abs(sel.envelope_at_c_high - 0.05) < 1e-9 and sel.components_at_c_high >= 50
    assert "fallback" in sel.note and "unreachable" in sel.note
    assert sel.c_low <= sel.c_high
    js = sel.as_json()
    assert js["c_high_fallback_used"] and js["c_high_reachable"] is False


def test_c_high_is_never_below_c_low_and_bands_agree_on_random_tables():
    rng = random.Random(5)
    for trial in range(40):
        rows = []
        for i in range(rng.randint(5, 300)):
            match = rng.random() < 0.6
            s = rng.gauss(3.0 if match else -1.0, 1.5)
            rules = ("TWIN",) if rng.random() < 0.05 else ()
            rows.append(sp(i, round(s, 3), match, comp=f"C{rng.randint(0, 80)}", rules=rules))
        sel = select_thresholds(rows, ThresholdConfig())
        assert sel.c_low <= sel.c_high, trial
        g = lambda s: display_p(s, {})
        assert check_band_agreement(rows, sel.c_low, sel.c_high, g), trial
        t_low, t_high = g(sel.c_low), g(sel.c_high)
        for p in rows:
            assert band_for(g(p.raw_score), t_low, t_high, p.negative_rules_fired) == p.band(sel.c_low, sel.c_high)


def test_envelope_is_not_poisoned_by_one_false_pair_in_an_unsupported_top_region():
    """Architecture 6: the envelope exists to avoid picking a lucky noisy c. One false pair scoring above
    every true pair is an n=1 region far below the 50-component floor; it must not make alpha unreachable
    when the false-merge rate at every supported cutoff is 0.5%."""
    rows = [sp(i, 2.0 + (i % 5), True) for i in range(200)]
    rows.append(sp(9000, 7.5, False))
    sel = select_thresholds(rows, ThresholdConfig(alpha=0.01, min_components=50))
    assert sel.c_high_reachable, f"alpha reported unreachable: envelope {sel.envelope_at_c_high}, note {sel.note!r}"
    assert sel.c_high <= 2.0 + 1e-9
