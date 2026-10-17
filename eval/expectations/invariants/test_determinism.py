"""Determinism (eval plan section 9): two harness runs with the same seed give identical metrics.json."""
from __future__ import annotations

import json
from pathlib import Path

from eval.harness.testing import fast_run, fresh_run_dir


def test_same_seed_gives_identical_metrics_json():
    first = fast_run()
    second = fast_run(out_dir=fresh_run_dir())
    a = json.loads((first.run_dir / "metrics.json").read_text())
    b = json.loads((second.run_dir / "metrics.json").read_text())
    assert a == b


def test_idempotent_ingest_invariant_holds():
    assert fast_run().metrics["invariants"]["idempotent_ingest"] is True


def test_metrics_json_carries_no_run_id_or_timestamp():
    result = fast_run()
    text = (Path(result.run_dir) / "metrics.json").read_text()
    assert result.run_id not in text
    assert "createdAt" not in text
