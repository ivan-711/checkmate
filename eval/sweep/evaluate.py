"""``evaluate_manifest(entry)``: one harness run for one manifest entry, on whichever executor calls it.

Wraps ``eval.harness.run.run`` unchanged: the numbers are the harness's, the sweep adds nothing to them. The
tier picks the inputs. ``synthea`` is the production command's own configuration (W1's corpus, W2's engine,
the current threshold row); ``fixture`` is the harness self-test. The entry's scorer version must be the one
the loaded engine reports, or the run is refused: a sweep never mislabels what it measured.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from eval.harness.fixture import FixtureConfig
from eval.harness.product import DEFAULT_RAW_DIR
from eval.harness.run import RUNS_DIR, RunConfig, product_config, run
from eval.sweep.manifest import CONFIG_FAST, TIER_FIXTURE, TIER_SYNTHEA, ManifestEntry

LATENCY_PREFIX = "latency."
FIXTURE_ENTITIES = 150  # the harness's own self-test fixture size (eval.harness.testing)
FIXTURE_HARD_NEGATIVES = 20
SWEEP_MANIFEST_KEY = "sweep"


class ScorerVersionMismatch(RuntimeError):
    """The manifest names a scorer version the loaded engine does not report."""


def run_config_for(entry: ManifestEntry, out_dir: Path | None = None, raw_dir: Path | None = None) -> RunConfig:
    out = out_dir or RUNS_DIR
    fast = entry.config == CONFIG_FAST
    if entry.tier == TIER_FIXTURE:
        cfg = RunConfig(
            name=entry.config,
            seed=entry.seed,
            fast=fast,
            out_dir=out,
            fixture=FixtureConfig(
                seed=entry.seed, entities=FIXTURE_ENTITIES, hard_negative_pairs=FIXTURE_HARD_NEGATIVES
            ),
        )
    elif entry.tier == TIER_SYNTHEA:
        # the production command's own configuration, so a sweep measures what `python -m eval.harness.run` does
        args = argparse.Namespace(
            seed=entry.seed, raw=raw_dir or DEFAULT_RAW_DIR, fast=fast, test_pass=False, out=out, database_url=None
        )
        cfg = product_config(args)
    else:
        raise ValueError(f"unknown tier {entry.tier!r}")
    if cfg.scorer_version != entry.scorer_version:
        raise ScorerVersionMismatch(
            f"the manifest names scorer version {entry.scorer_version!r} but the "
            f"{entry.tier} tier's engine reports {cfg.scorer_version!r}"
        )
    cfg.extra_manifest = {
        SWEEP_MANIFEST_KEY: {
            "sweepSha256": entry.sweep_sha256,
            "entrySha256": entry.sha256,
            "tier": entry.tier,
            "splitId": entry.split_id,
        }
    }
    return cfg


def evaluate_manifest(entry: ManifestEntry, *, out_dir: Path | None = None, raw_dir: Path | None = None) -> dict:
    """One harness run. Returns a JSON-serializable record: the entry and both hashes, the run id and directory,
    the published numbers (latency kept apart, as ADR-012 excludes it from the cross-executor comparison), the
    invariants, the operating point and the wall time."""
    cfg = run_config_for(entry, out_dir, raw_dir)
    started = time.perf_counter()
    result = run(cfg)
    elapsed = time.perf_counter() - started
    numbers = {k: v for k, v in result.numbers.items() if not k.startswith(LATENCY_PREFIX)}
    latency = {k: v for k, v in result.numbers.items() if k.startswith(LATENCY_PREFIX)}
    return {
        "entry": entry.as_dict(),
        "entrySha256": entry.sha256,
        "sweepSha256": entry.sweep_sha256,
        "runId": result.run_id,
        "runDir": str(result.run_dir),
        "gitSha": result.manifest["gitSha"],
        "numbers": numbers,
        "latency": latency,
        "invariants": result.metrics["invariants"],
        "thresholds": {
            "thresholdsId": result.manifest["thresholdSetId"],
            "cLow": result.manifest["thresholds"]["cLow"],
            "cHigh": result.manifest["thresholds"]["cHigh"],
        },
        "elapsedSeconds": elapsed,
    }
