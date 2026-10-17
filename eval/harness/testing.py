"""Test helpers: one cached fast run per process so invariant tests share it."""
from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from eval.harness.fixture import FixtureConfig
from eval.harness.run import RunConfig, RunResult, run

TEST_SEED = 20261017
TEST_FIXTURE = FixtureConfig(seed=TEST_SEED, entities=150, hard_negative_pairs=20)


def fresh_run_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="checkmate-eval-"))


@lru_cache(maxsize=4)
def _cached(seed: int, out_dir: str) -> RunResult:
    cfg = RunConfig(name="fast", seed=seed, fast=True, out_dir=Path(out_dir),
                    fixture=FixtureConfig(seed=seed, entities=TEST_FIXTURE.entities,
                                          hard_negative_pairs=TEST_FIXTURE.hard_negative_pairs))
    return run(cfg)


def fast_run(seed: int = TEST_SEED, out_dir: Path | None = None) -> RunResult:
    """Cached per (seed, out_dir); a fresh ``out_dir`` forces a second real run."""
    return _cached(seed, str(out_dir) if out_dir else _default_dir())


@lru_cache(maxsize=1)
def _default_dir() -> str:
    return str(fresh_run_dir())
