"""The run writes every file the contract names and every published number carries its n."""
from __future__ import annotations

import json
from pathlib import Path

from eval.compare import compare
from eval.harness.fixture import FixtureConfig, build_fixture, corpus_hashes
from eval.harness.run import RunConfig, run
from eval.harness.summary import render
from eval.harness.testing import fast_run, fresh_run_dir

REQUIRED_FILES = ("manifest.json", "numbers.json", "metrics.json", "thresholds.json", "run.json", "splits.json",
                  "errors_by_band.csv", "manifest.sha256")
REQUIRED_KEYS = ("band.auto_link.precision", "band.review.precision", "band.keep_separate.precision",
                 "recall.strict.end_to_end", "recall.lenient.end_to_end", "false_merge_rate", "review_burden",
                 "blocking.recall", "blocking.reduction_ratio", "thresholds.c_low", "thresholds.c_high",
                 "thresholds.alpha_target_reachable", "latency.match.p50_ms", "latency.match.p95_ms")


def test_fixture_is_deterministic_and_labeled():
    a = build_fixture(FixtureConfig(seed=5, entities=40, hard_negative_pairs=6))
    b = build_fixture(FixtureConfig(seed=5, entities=40, hard_negative_pairs=6))
    assert corpus_hashes(a) == corpus_hashes(b)
    assert corpus_hashes(a) != corpus_hashes(build_fixture(FixtureConfig(seed=6, entities=40, hard_negative_pairs=6)))
    cats = {c for r in a.records for c in r["categories"]}
    assert {"N1", "N3"} <= cats and cats & {"T1", "D1", "D3", "L7"}
    assert len(a.dependency_edges) == 6
    assert all(len({t.record_id for t in a.truth}) == len(a.records) for _ in [0])


def test_run_writes_every_contract_file_and_number():
    result = fast_run()
    for name in REQUIRED_FILES:
        assert (result.run_dir / name).exists(), name
    numbers = json.loads((result.run_dir / "numbers.json").read_text())
    for key in REQUIRED_KEYS:
        assert key in numbers, key
    for key, cell in numbers.items():
        if key.startswith(("band.", "recall.", "false_merge", "review", "category.", "button.")) and "kind" not in key:
            assert {"n_pairs", "n_entities", "n_components"} <= set(cell), key
    manifest = json.loads((result.run_dir / "manifest.json").read_text())
    for key in ("fixtureHashes", "split", "seed", "scorerVersion", "thresholdSetId", "gitSha", "expectations"):
        assert key in manifest
    assert manifest["expectations"]["tolerance.json"]
    thresholds = json.loads((result.run_dir / "thresholds.json").read_text())
    assert thresholds["autoLinkEnabled"] is False and thresholds["isCalibrated"] is False
    assert thresholds["cLow"] <= thresholds["cHigh"]


def test_fast_config_never_touches_the_test_partition():
    result = fast_run()
    assert not any(k.startswith("test.") for k in result.numbers)
    assert result.manifest["regime"] == "development"


def test_test_pass_only_when_requested(tmp_path: Path):
    cfg = RunConfig(name="development", seed=3, fast=True, include_test_pass=True, out_dir=tmp_path,
                    fixture=FixtureConfig(seed=3, entities=120, hard_negative_pairs=12))
    result = run(cfg)
    assert "test.recall.lenient.end_to_end" in result.numbers
    assert json.loads((result.run_dir / "run.json").read_text())["testRuns"] == 1


def test_summary_renders_bands_with_n():
    result = fast_run()
    text = render(result.numbers, result.manifest)
    assert "AUTO_LINK precision" in text and "n components" in text and "c_high" in text


def test_compare_flags_a_recall_drop_and_passes_inside_tolerance():
    result = fast_run()
    tolerance = json.loads((Path(__file__).parents[1] / "expectations" / "tolerance.json").read_text())
    metrics = {"invariants": result.metrics["invariants"], "scorerVersion": "trained-scorer-1"}
    worse = json.loads(json.dumps(result.numbers))
    worse["recall.lenient.end_to_end"]["value"] -= 0.05
    breaches, _ = compare(result.numbers, worse, tolerance, metrics, metrics)
    assert any("LENIENT" in b for b in breaches)
    same, notes = compare(result.numbers, result.numbers, tolerance, metrics, metrics)
    assert same == [] and notes
    unreachable = json.loads(json.dumps(result.numbers))
    unreachable["thresholds.alpha_target_reachable"] = {"value": False, "fallback_used": True}
    breaches, _ = compare(result.numbers, unreachable, tolerance, metrics, metrics)
    assert any("unreachable" in b for b in breaches)


def test_compare_applies_only_invariants_for_the_stand_in_scorer():
    result = fast_run()
    tolerance = json.loads((Path(__file__).parents[1] / "expectations" / "tolerance.json").read_text())
    worse = json.loads(json.dumps(result.numbers))
    worse["recall.lenient.end_to_end"]["value"] = 0.0
    breaches, notes = compare(result.numbers, worse, tolerance, result.metrics, result.metrics)
    assert breaches == [] and any("stand-in" in n for n in notes)
    broken = {**result.metrics, "invariants": {**result.metrics["invariants"], "idempotent_ingest": False}}
    breaches, _ = compare(result.numbers, result.numbers, tolerance, result.metrics, broken)
    assert breaches == ["invariant idempotent_ingest failed"]


def test_second_seed_changes_metrics_but_keeps_shape():
    other = run(RunConfig(name="fast", seed=99, fast=True, out_dir=fresh_run_dir(),
                          fixture=FixtureConfig(seed=99, entities=150, hard_negative_pairs=20)))
    base = fast_run()
    assert set(other.numbers) == set(base.numbers)
    assert other.metrics["numbers"] != base.metrics["numbers"]


def test_operating_point_is_the_current_migration_row_and_bands_use_it(tmp_path: Path):
    from eval.harness.current_thresholds import from_migrations

    op = from_migrations()
    assert (op.thresholds_id, op.c_low, op.c_high) == ("provisional-1", 0.0, 4.0)
    result = run(RunConfig(name="fast", seed=3, fast=True, out_dir=tmp_path, operating_point=op,
                           fixture=FixtureConfig(seed=3, entities=120, hard_negative_pairs=12)))
    assert result.numbers["thresholds.c_high"]["value"] == 4.0
    assert result.numbers["thresholds.operating_point"]["value"] == "provisional-1"
    assert "thresholds.proposed.c_high" in result.numbers
    doc = json.loads((result.run_dir / "thresholds.json").read_text())
    assert doc["thresholdsId"] == "provisional-1" and doc["proposed"]["thresholdsId"].startswith("oof-")


def test_category_recall_counts_blocking_misses():
    from eval.harness.metrics import ScoredPair
    from eval.harness.run import category_numbers

    found = ScoredPair("a", "b", "E1", "E1", "C1", "C1", 9.0, 0.9, (), ("T1",))
    missed = ScoredPair("c", "d", "E2", "E2", "C2", "C2", float("-inf"), 0.0, (), ("T1",))
    out = category_numbers([found], [missed], 0.0, 4.0, ["T1"], seed=1, resamples=20)
    assert out["category.T1.recall.strict"]["value"] == 0.5
    assert out["category.T1.blocking_recall"]["value"] == 0.5


def test_regression_outcomes_are_published_through_the_named_engine(tmp_path: Path):
    from eval.harness import standin

    result = run(RunConfig(name="fast", seed=3, fast=True, out_dir=tmp_path, regression_match=standin.match,
                           fixture=FixtureConfig(seed=3, entities=120, hard_negative_pairs=12)))
    cells = {k: v for k, v in result.numbers.items() if k.startswith("regression.")}
    assert len(cells) == 10 and sum(v["nickname"] for v in cells.values()) >= 3
    assert all({"value", "raw_score", "pass", "expected"} <= set(v) for v in cells.values())
    assert "Nickname cases" in render(result.numbers, result.manifest)
