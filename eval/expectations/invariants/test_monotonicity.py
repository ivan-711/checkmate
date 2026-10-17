"""Monotonicity contract (eval plan section 5): the display map is strictly increasing and
band(p, T) equals band(s, c) on every row. A failed assertion blocks the freeze."""
from __future__ import annotations

from eval.harness.metrics import check_band_agreement, check_monotone
from eval.harness.standin import display_p
from eval.harness.testing import fast_run


def test_display_map_is_strictly_increasing():
    result = fast_run()
    assert result.metrics["invariants"]["monotone_display_map"] is True
    assert check_monotone(lambda s: display_p(s, {}), [x / 10 for x in range(-80, 80)])


def test_bands_from_p_equal_bands_from_raw_on_every_row():
    result = fast_run()
    assert result.metrics["invariants"]["band_agreement_p_vs_raw"] is True


def test_a_decreasing_map_is_rejected():
    assert check_monotone(lambda s: -s, [0.0, 1.0, 2.0]) is False


def test_band_agreement_detects_a_remapped_cutoff():
    from eval.harness.metrics import ScoredPair

    rows = [ScoredPair("a", "b", "e1", "e1", "c1", "c1", s, 0.0, ()) for s in (-1.0, 0.5, 2.0)]
    assert check_band_agreement(rows, 0.0, 1.0, lambda s: s) is True
    assert check_band_agreement(rows, 0.0, 1.0, lambda s: -s) is False
