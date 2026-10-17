"""Latency of ``match()`` measured in-process (eval plan section 5, latency row).

Warm: warm-up calls, then timed calls; p50, p95, p99 with n. p99 from 1,000 calls rests on about
10 values; the output says so. The machine is recorded so the number is never quoted bare.
"""
from __future__ import annotations

import platform
import time
from collections.abc import Mapping, Sequence

from eval.harness.metrics import percentiles_ms
from eval.harness.types import MatchFn, Record

WARMUP_CALLS = 50
TIMED_CALLS = 1000


def machine() -> dict:
    return {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
            "python": platform.python_version()}


def measure_match(match: MatchFn, pairs: Sequence[tuple[Record, Record]], weights: Mapping[str, float],
                  thresholds: Mapping[str, float], warmup: int = WARMUP_CALLS, timed: int = TIMED_CALLS) -> dict:
    if not pairs:
        return {"p50_ms": None, "p95_ms": None, "p99_ms": None, "n": 0, "method": "in-process, warm", "machine": machine()}
    n = len(pairs)
    for i in range(warmup):
        a, b = pairs[i % n]
        match(a, b, weights, thresholds)
    samples: list[float] = []
    for i in range(timed):
        a, b = pairs[i % n]
        t0 = time.perf_counter()
        match(a, b, weights, thresholds)
        samples.append((time.perf_counter() - t0) * 1000.0)
    out = percentiles_ms(samples)
    out.update(method="in-process, warm", warmup=warmup, machine=machine(),
               note=f"p99 from {timed} calls rests on about {max(timed // 100, 1)} values")
    return out
