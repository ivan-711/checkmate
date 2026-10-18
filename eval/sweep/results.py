"""One results table per sweep: for each scorer version x tier, every numeric harness metric's mean and
95% interval across seeds, for the metrics the harness lets anyone read.

The interval is a two-sided Student t interval on the per-seed values (n seeds is small, so the t critical
value, not 1.96). A rate's interval is clipped to [0, 1], because a proportion cannot leave it. A metric the
harness marks ``do_not_read`` on any seed, or whose support is under the harness's own floor, is withheld:
no mean, no interval, no per-seed values in this table. Each entry keeps the harness's cells as the harness
stores them; this table is the across-seed view. Latency never enters the table (ADR-012 excludes it from any
cross-executor comparison).
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from scipy.stats import t as student_t

from eval.harness.metrics import DO_NOT_READ_COMPONENTS, DO_NOT_READ_PAIRS
from eval.harness.summary import ROWS
from eval.sweep.evaluate import LATENCY_PREFIX

CONFIDENCE_QUANTILE = 0.975  # two-sided 95%
INTERVAL_METHOD = "Student t, two-sided 95%, across seeds"
INTERVAL_NOTE = (
    "rate intervals are clipped to [0, 1]; a metric the harness marks do-not-read on any seed "
    f"(under {DO_NOT_READ_COMPONENTS} components or {DO_NOT_READ_PAIRS} pairs) is not reported; "
    "with few seeds (df = n - 1) the interval is wide, so read the per-seed values too"
)
NOT_REPORTED = "not reported (below the harness floor)"
UNIT_RATIO_KEYS = frozenset({"blocking.reduction_ratio"})
"""Proportions the harness publishes without its own ``ci95`` cell field."""
DECIMALS = 3


def t_critical_95(degrees_of_freedom: int) -> float:
    if degrees_of_freedom < 1:
        raise ValueError("a t interval needs at least one degree of freedom")
    return float(student_t.ppf(CONFIDENCE_QUANTILE, degrees_of_freedom))


def interval_95(values: Sequence[float]) -> dict:
    """Mean, sample sd and the 95% t interval of ``values``; sd and interval are None below two values."""
    vals = [float(v) for v in values]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "ci95": None, "values": []}
    mean = statistics.fmean(vals)
    if n < 2:
        return {"n": n, "mean": mean, "sd": None, "ci95": None, "values": vals}
    sd = statistics.stdev(vals)
    half = t_critical_95(n - 1) * sd / math.sqrt(n)
    return {"n": n, "mean": mean, "sd": sd, "ci95": [mean - half, mean + half], "values": vals}


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _cell(result: dict, key: str) -> dict:
    cell = result["numbers"].get(key)
    return cell if isinstance(cell, dict) else {}


def _below_floor(cell: dict) -> bool:
    """The harness's own rule (``metrics.rate``): flagged, or under the component or pair floor. A cell that
    carries no support counts (a config value such as a cutoff) has no floor to fall under."""
    return (
        bool(cell.get("do_not_read"))
        or cell.get("n_components", DO_NOT_READ_COMPONENTS) < DO_NOT_READ_COMPONENTS
        or cell.get("n_pairs", DO_NOT_READ_PAIRS) < DO_NOT_READ_PAIRS
    )


def _is_rate(key: str, cells: Sequence[dict]) -> bool:
    return key in UNIT_RATIO_KEYS or any("ci95" in cell for cell in cells)


def _clip_to_unit(interval: list[float]) -> list[float]:
    return [min(max(end, 0.0), 1.0) for end in interval]


def _metric(key: str, seeds: Sequence[int], cells: Sequence[dict]) -> dict:
    """One metric across seeds: withheld if any seed is below the floor or has no value (an empty denominator
    is flagged by the harness anyway), else its mean and interval, clipped to [0, 1] for a rate."""
    withheld = [s for s, c in zip(seeds, cells) if _below_floor(c) or not _numeric(c.get("value"))]
    if withheld:
        return {"reported": False, "reason": NOT_REPORTED, "seedsBelowFloor": withheld}
    stats = interval_95([c["value"] for c in cells])
    rate = _is_rate(key, cells)
    interval = stats["ci95"]
    clipped = False
    if rate and interval is not None:
        unit = _clip_to_unit(interval)
        clipped, interval = unit != interval, unit
    return {"reported": True, **stats, "ci95": interval, "rate": rate, "clipped": clipped}


def aggregate(results: Sequence[dict]) -> dict:
    """Group entry results by (scorer version, tier) and reduce every numeric metric across their seeds."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for result in results:
        key = (result["entry"]["scorerVersion"], result["entry"]["tier"])
        groups.setdefault(key, []).append(result)
    cells = []
    for (scorer, tier), members in sorted(groups.items()):
        members = sorted(members, key=lambda r: r["entry"]["seed"])
        seeds = [r["entry"]["seed"] for r in members]
        keys = sorted(
            {
                k
                for r in members
                for k in r["numbers"]
                if not k.startswith(LATENCY_PREFIX) and _numeric(_cell(r, k).get("value"))
            }
        )
        metrics = {k: _metric(k, seeds, [_cell(r, k) for r in members]) for k in keys}
        cells.append({"scorerVersion": scorer, "tier": tier, "seeds": seeds, "metrics": metrics})
    return {"interval": INTERVAL_METHOD, "note": INTERVAL_NOTE, "cells": cells}


def _fmt(x) -> str:
    return "n/a" if x is None else f"{x:.{DECIMALS}f}"


def render_table(table: dict) -> str:
    """The headline rows (the same ones the per-merge summary posts) per cell, as Markdown."""
    lines: list[str] = []
    for cell in table["cells"]:
        seeds = ", ".join(str(s) for s in cell["seeds"])
        lines.append(
            f"### scorer {cell['scorerVersion']} · tier {cell['tier']} · n seeds {len(cell['seeds'])} ({seeds})"
        )
        lines.append("| metric | mean | 95% interval | per seed |")
        lines.append("|---|---|---|---|")
        for label, key in ROWS:
            m = cell["metrics"].get(key)
            if m is None:
                lines.append(f"| {label} | n/a | n/a | n/a |")
            elif not m["reported"]:
                lines.append(f"| {label} | {m['reason']} | n/a | n/a |")
            else:
                ci = f"[{_fmt(m['ci95'][0])}, {_fmt(m['ci95'][1])}]" if m["ci95"] else "n/a (one seed)"
                lines.append(f"| {label} | {_fmt(m['mean'])} | {ci} | {', '.join(_fmt(v) for v in m['values'])} |")
        lines.append(f"interval: {table['interval']}; {table['note']}")
        lines.append("")
    return "\n".join(lines)
