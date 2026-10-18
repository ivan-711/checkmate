"""One results table per sweep: for each scorer version x tier, every numeric harness metric's mean and
95% interval across seeds.

The interval is a two-sided Student t interval on the per-seed values (n seeds is small, so the t critical
value, not 1.96). Each entry keeps its own per-run bootstrap intervals in its numbers; this table is the
across-seed view. Latency never enters the table (ADR-012 excludes it from any cross-executor comparison).
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from eval.harness.summary import ROWS
from eval.sweep.evaluate import LATENCY_PREFIX

T_CRITICAL_95 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}
"""Two-sided 95% Student t critical values by degrees of freedom (the standard table); past 30, the normal value."""
Z_95 = statistics.NormalDist().inv_cdf(0.975)
INTERVAL_METHOD = "Student t, two-sided 95%, across seeds"
INTERVAL_NOTE = (
    "the interval is not clipped to [0, 1]; with few seeds (df = n - 1) it is wide, so read the per-seed values too"
)
DECIMALS = 3


def t_critical_95(degrees_of_freedom: int) -> float:
    if degrees_of_freedom < 1:
        raise ValueError("a t interval needs at least one degree of freedom")
    return T_CRITICAL_95.get(degrees_of_freedom, Z_95)


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


def _numeric_value(result: dict, key: str):
    cell = result["numbers"].get(key)
    return cell.get("value") if isinstance(cell, dict) else None


def aggregate(results: Sequence[dict]) -> dict:
    """Group entry results by (scorer version, tier) and reduce every numeric metric across their seeds."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for result in results:
        key = (result["entry"]["scorerVersion"], result["entry"]["tier"])
        groups.setdefault(key, []).append(result)
    cells = []
    for (scorer, tier), members in sorted(groups.items()):
        members = sorted(members, key=lambda r: r["entry"]["seed"])
        keys = sorted(
            {
                k
                for r in members
                for k in r["numbers"]
                if not k.startswith(LATENCY_PREFIX) and _numeric(_numeric_value(r, k))
            }
        )
        metrics = {
            k: interval_95([_numeric_value(r, k) for r in members if _numeric(_numeric_value(r, k))]) for k in keys
        }
        cells.append(
            {"scorerVersion": scorer, "tier": tier, "seeds": [r["entry"]["seed"] for r in members], "metrics": metrics}
        )
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
                continue
            ci = f"[{_fmt(m['ci95'][0])}, {_fmt(m['ci95'][1])}]" if m["ci95"] else "n/a (one seed)"
            lines.append(f"| {label} | {_fmt(m['mean'])} | {ci} | {', '.join(_fmt(v) for v in m['values'])} |")
        lines.append(f"interval: {table['interval']}; {table['note']}")
        lines.append("")
    return "\n".join(lines)
