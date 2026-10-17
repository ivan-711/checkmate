"""``run(config)``: the harness core (eval plan sections 3, 5, 9; architecture sections 6, 12).

Takes a corpus loader (W1's loader, or the in-repo synthetic fixture), a ``match`` callable with
W2's signature, a ``fit`` hook and a ``block`` callable, then: assigns the split contract,
scores development pairs out of fold, chooses ``c_low``/``c_high`` false-merge first, computes the
published numbers with n, measures ``match()`` latency in process and writes
``eval/runs/<run_id>/{manifest,numbers,metrics,thresholds,run,splits}.json``.

``--fast`` is the per-merge config: P0 families, one seed, development components only. The test
partition is scored only with ``include_test_pass=True`` (the single 20:00 pass), never per merge.

    uv run python -m eval.harness.run --fast --seed 20261017
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from eval.harness import latency as latency_mod
from eval.harness import standin
from eval.harness.fixture import P0_FAMILIES, FixtureConfig, build_fixture, corpus_hashes
from eval.harness.metrics import (
    ScoredPair,
    band_metrics,
    blocking_metrics,
    check_band_agreement,
    check_monotone,
    rate,
)
from eval.harness.splits import (
    Assignment,
    LeakageError,
    SplitConfig,
    assert_fit_partition,
    assign,
    development_units,
    records_in,
)
from eval.harness.thresholds import ThresholdConfig, ThresholdSelection, select_thresholds
from eval.harness.types import (
    PARTITION_TEST,
    BlockFn,
    Corpus,
    FitFn,
    MatchFn,
    Record,
    pair_key,
)
from eval.harness.whatifs import BUTTON_CATEGORIES, BUTTON_KIND, BUTTONS

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTATIONS_DIR = REPO_ROOT / "eval" / "expectations"
RUNS_DIR = REPO_ROOT / "eval" / "runs"
FAST_LATENCY = (20, 200)   # warm-up, timed: per merge
FULL_LATENCY = (latency_mod.WARMUP_CALLS, latency_mod.TIMED_CALLS)
FAST_BOOTSTRAP = 200
EXPORT_DECIMALS = 6


@dataclass
class RunConfig:
    name: str = "fast"
    seed: int = 20261017
    fast: bool = True
    families: tuple[str, ...] = P0_FAMILIES
    include_test_pass: bool = False
    out_dir: Path = RUNS_DIR
    expectations_dir: Path = EXPECTATIONS_DIR
    corpus_loader: Callable[[], Corpus] | None = None
    match: MatchFn = standin.match
    fit: FitFn = standin.fit
    block: BlockFn = standin.block
    scorer_version: str = standin.SCORER_VERSION
    fixture: FixtureConfig | None = None
    bootstrap_resamples: int | None = None
    latency_calls: tuple[int, int] | None = None
    extra_manifest: dict = field(default_factory=dict)


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    numbers: dict
    metrics: dict
    thresholds: ThresholdSelection
    manifest: dict
    assignment: Assignment
    corpus: Corpus
    weights: Mapping[str, float]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def expectations_config(expectations_dir: Path) -> tuple[ThresholdConfig, SplitConfig, dict]:
    cfg = load_json(expectations_dir / "config.json")
    thresholds = ThresholdConfig(alpha=cfg["alpha"], beta=cfg["beta"], min_components=cfg["minComponents"],
                                 review_burden_max=cfg["reviewBurdenMax"])
    s = load_json(expectations_dir / "splits.json")
    splits = SplitConfig(showcase_pool_components=s["showcasePoolComponents"],
                         development_fraction=s["developmentFraction"], folds=s["folds"],
                         stratify_by_language=s["stratifyByLanguage"])
    return thresholds, splits, cfg


def expectations_hashes(expectations_dir: Path) -> dict[str, str]:
    """sha256 of every protected expectation file (eval plan section 9, protected expectations)."""
    out: dict[str, str] = {}
    for path in sorted(expectations_dir.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            out[path.relative_to(expectations_dir).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def git_sha() -> str | None:
    if os.environ.get("GIT_SHA"):
        return os.environ["GIT_SHA"]
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
                              cwd=REPO_ROOT).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def true_pairs_within(records: Sequence[Record], entity_of: Mapping[str, str]) -> set[tuple[str, str]]:
    by_entity: dict[str, list[str]] = {}
    for r in records:
        by_entity.setdefault(entity_of[r["record_id"]], []).append(r["record_id"])
    pairs: set[tuple[str, str]] = set()
    for members in by_entity.values():
        members = sorted(members)
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                pairs.add(pair_key(a, b))
    return pairs


def _score_pairs(pairs: set[tuple[str, str]], by_id: Mapping[str, Record], entity_of: Mapping[str, str],
                 assignment: Assignment, match: MatchFn, weights: Mapping[str, float]) -> list[ScoredPair]:
    placeholder = {"c_low": 0.0, "c_high": 0.0}  # bands are recomputed from the raw score after selection
    out: list[ScoredPair] = []
    for a_id, b_id in sorted(pairs):
        a, b = by_id[a_id], by_id[b_id]
        res = match(a, b, weights, placeholder)
        out.append(ScoredPair(
            record_a=a_id, record_b=b_id, entity_a=entity_of[a_id], entity_b=entity_of[b_id],
            component_a=assignment.component_of_person[a["person_id"]],
            component_b=assignment.component_of_person[b["person_id"]],
            raw_score=round(res.raw_score, 12), p=res.p, negative_rules_fired=tuple(res.negative_rules_fired),
            categories=tuple(sorted(set(a.get("categories") or ()) | set(b.get("categories") or ()))),
        ))
    return out


def out_of_fold(corpus: Corpus, assignment: Assignment, cfg: RunConfig) -> tuple[list[ScoredPair], dict]:
    """Grouped 5-fold out-of-fold scoring over development components (split steps 4 and 6)."""
    by_id = corpus.record_by_id()
    entity_of = corpus.entity_of()
    units = development_units(assignment)
    scored: list[ScoredPair] = []
    truth_total: set[tuple[str, str]] = set()
    blocked_total: set[tuple[str, str]] = set()
    all_pairs_n = 0
    for unit in sorted(units):
        fold_records = records_in(corpus, assignment, {unit})
        train_records = records_in(corpus, assignment, units - {unit})
        train_ids = {r["record_id"] for r in train_records}
        train_truth = [t for t in corpus.truth if t.record_id in train_ids]
        weights = cfg.fit(train_records, train_truth)
        assert_fit_partition(train_ids, units - {unit}, corpus, assignment, f"scorer for {unit}")
        blocked = cfg.block(fold_records)
        truth_total |= true_pairs_within(fold_records, entity_of)
        blocked_total |= blocked
        n = len(fold_records)
        all_pairs_n += n * (n - 1) // 2
        scored.extend(_score_pairs(blocked, by_id, entity_of, assignment, cfg.match, weights))
    meta = {"truePairs": truth_total, "blockedPairs": blocked_total, "allPairsN": all_pairs_n,
            "records": sum(1 for r in corpus.records if assignment.unit_of_person(r["person_id"]) in units)}
    return scored, meta


def category_numbers(pairs: Sequence[ScoredPair], c_low: float, c_high: float, families: Sequence[str],
                     seed: int, resamples: int) -> dict[str, dict]:
    """Per-category recall over true pairs carrying the category (T2) and per-button recall (T15)."""
    out: dict[str, dict] = {}
    true_pairs = [p for p in pairs if p.is_match]
    for fam in families:
        members = [p for p in true_pairs if fam in p.categories]
        strict = [p for p in members if p.band(c_low, c_high) == "AUTO_LINK"]
        lenient = [p for p in members if p.band(c_low, c_high) != "KEEP_SEPARATE"]
        if fam.startswith("N"):
            negatives = [p for p in pairs if not p.is_match and fam in p.categories]
            out[f"hard_negative.{fam}.auto_linked_wrongly"] = rate(
                [p for p in negatives if p.band(c_low, c_high) == "AUTO_LINK"], negatives, seed, resamples)
            out[f"hard_negative.{fam}.sent_to_review"] = rate(
                [p for p in negatives if p.band(c_low, c_high) == "REVIEW"], negatives, seed, resamples)
            continue
        out[f"category.{fam}.recall.strict"] = rate(strict, members, seed, resamples)
        out[f"category.{fam}.recall.lenient"] = rate(lenient, members, seed, resamples)
    for button in BUTTONS:
        cats = BUTTON_CATEGORIES[button]
        members = [p for p in true_pairs if any(c in p.categories for c in cats)]
        strict = [p for p in members if p.band(c_low, c_high) == "AUTO_LINK"]
        lenient = [p for p in members if p.band(c_low, c_high) != "KEEP_SEPARATE"]
        out[f"button.{button}.recall.strict"] = rate(strict, members, seed, resamples)
        out[f"button.{button}.recall.lenient"] = rate(lenient, members, seed, resamples)
        out[f"button.{button}.kind"] = {"value": BUTTON_KIND[button], "category_ids": list(cats)}
    return out


def _round(obj):
    if isinstance(obj, float):
        return None if math.isnan(obj) else round(obj, EXPORT_DECIMALS)
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round(v) for v in obj]
    return obj


def thresholds_id_for(selection: ThresholdSelection, scorer_version: str, fixture_hashes: Mapping[str, str]) -> str:
    digest = hashlib.sha256(json.dumps({"c_low": selection.c_low, "c_high": selection.c_high,
                                        "scorer": scorer_version, "fixture": dict(fixture_hashes)},
                                       sort_keys=True).encode()).hexdigest()
    return f"oof-{digest[:12]}"


def errors_by_band(pairs: Sequence[ScoredPair], c_low: float, c_high: float) -> str:
    """T16: every false auto-link and every true pair kept separate; a development listing is descriptive."""
    lines = ["pair_a,pair_b,band,raw_score,is_match,categories,negative_rules"]
    for p in sorted(pairs, key=lambda p: (p.record_a, p.record_b)):
        band = p.band(c_low, c_high)
        if (band == "AUTO_LINK" and not p.is_match) or (band == "KEEP_SEPARATE" and p.is_match):
            lines.append(f"{p.record_a},{p.record_b},{band},{p.raw_score:.6f},{int(p.is_match)},"
                         f"{'|'.join(p.categories)},{'|'.join(p.negative_rules_fired)}")
    return "\n".join(lines) + "\n"


def run(cfg: RunConfig) -> RunResult:
    threshold_cfg, split_cfg, expectations = expectations_config(cfg.expectations_dir)
    resamples = cfg.bootstrap_resamples or (FAST_BOOTSTRAP if cfg.fast else expectations["bootstrapResamples"])
    warmup, timed = cfg.latency_calls or (FAST_LATENCY if cfg.fast else FULL_LATENCY)
    bootstrap_seed = int(expectations["bootstrapSeed"]) ^ cfg.seed

    def load() -> Corpus:
        if cfg.corpus_loader is not None:
            return cfg.corpus_loader()
        return build_fixture(cfg.fixture or FixtureConfig(seed=cfg.seed, families=cfg.families))

    corpus = load()
    fixture_hashes = corpus_hashes(corpus)
    # invariant: idempotent ingest (loading twice gives the same records, truth and candidate-pair set)
    second = load()
    second_hashes = corpus_hashes(second)

    def pair_hash(c: Corpus) -> str:
        return hashlib.sha256(json.dumps(sorted(cfg.block(c.records))).encode()).hexdigest()

    idempotent = (fixture_hashes == second_hashes and pair_hash(corpus) == pair_hash(second)
                  and len(corpus.records) == len(second.records))

    assignment = assign(corpus, split_cfg)  # raises LeakageError on any hit
    scored, meta = out_of_fold(corpus, assignment, cfg)
    selection = select_thresholds(scored, threshold_cfg)
    c_low, c_high = selection.c_low, selection.c_high
    thresholds_id = thresholds_id_for(selection, cfg.scorer_version, fixture_hashes)

    numbers: dict[str, dict] = {}
    numbers.update(band_metrics(scored, len(meta["truePairs"]), c_low, c_high, bootstrap_seed, resamples))
    numbers.update(blocking_metrics(meta["truePairs"], meta["blockedPairs"], meta["allPairsN"]))
    numbers.update(category_numbers(scored, c_low, c_high, cfg.families, bootstrap_seed, resamples))
    numbers["thresholds.c_low"] = {"value": c_low}
    numbers["thresholds.c_high"] = {"value": c_high}
    numbers["thresholds.alpha_target_reachable"] = {"value": selection.c_high_reachable,
                                                    "fallback_used": selection.c_high_fallback_used}
    numbers["thresholds.envelope_at_c_high"] = {"value": selection.envelope_at_c_high,
                                                "n_components": selection.components_at_c_high,
                                                "n_pairs": selection.auto_links_at_c_high,
                                                "note": "development, descriptive"}
    numbers["corpus.records.development"] = {"value": meta["records"]}
    numbers["corpus.components"] = {"value": assignment.summary(corpus.records)["componentCount"]}

    # final fit on all development components (split step 6, development-wide fit only for the final fit)
    dev_units = development_units(assignment)
    dev_records = records_in(corpus, assignment, dev_units)
    dev_ids = {r["record_id"] for r in dev_records}
    weights = cfg.fit(dev_records, [t for t in corpus.truth if t.record_id in dev_ids])
    assert_fit_partition(dev_ids, dev_units, corpus, assignment, "final scorer")
    frozen = {"c_low": c_low, "c_high": c_high}

    def g(s: float) -> float:
        return standin.display_p(s, frozen)

    invariants = {
        "leakage_assertions": True,
        "monotone_display_map": check_monotone(g, [p.raw_score for p in scored]),
        "band_agreement_p_vs_raw": check_band_agreement(scored, c_low, c_high, g),
        "idempotent_ingest": idempotent,
        "fit_partition_assertions": True,
    }
    t_low, t_high = g(c_low), g(c_high)

    by_id = corpus.record_by_id()
    lat_pairs = [(by_id[p.record_a], by_id[p.record_b]) for p in scored[: max(timed, 1)]]
    latency = latency_mod.measure_match(cfg.match, lat_pairs, weights, frozen, warmup=warmup, timed=timed)

    test_numbers: dict[str, dict] = {}
    if cfg.include_test_pass:
        test_numbers = _test_pass(corpus, assignment, cfg, weights, c_low, c_high, bootstrap_seed, resamples)
        numbers.update(test_numbers)

    metrics = _round({"numbers": numbers, "thresholds": selection.as_json(), "invariants": invariants,
                      "split": assignment.summary(corpus.records), "seed": cfg.seed,
                      "scorerVersion": cfg.scorer_version, "fixtureHashes": fixture_hashes})
    run_id = str(uuid.uuid4())
    run_dir = cfg.out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "runId": run_id, "createdAt": datetime.now(UTC).isoformat(), "config": cfg.name, "fast": cfg.fast,
        "regime": "development" + (" + single test pass" if cfg.include_test_pass else ""),
        "seed": cfg.seed, "families": list(cfg.families), "fixtureHashes": fixture_hashes,
        "benchmarkCommit": None, "split": assignment.summary(corpus.records), "scorerVersion": cfg.scorer_version,
        "thresholdSetId": thresholds_id, "thresholds": {"cLow": c_low, "cHigh": c_high},
        "gitSha": git_sha(), "shards": 1, "bootstrapResamples": resamples, "bootstrapSeed": bootstrap_seed,
        "expectations": expectations_hashes(cfg.expectations_dir), **cfg.extra_manifest,
    }
    thresholds_doc = {
        "thresholdsId": thresholds_id, "cLow": c_low, "cHigh": c_high, "tLowDisplay": t_low, "tHighDisplay": t_high,
        "autoLinkEnabled": False, "isCalibrated": False, "sourceRunId": run_id,
        "selection": selection.as_json(), "scorerVersion": cfg.scorer_version,
        "wording": ("demo cutoffs chosen on development data against a 1% auto-link error target on synthetic data; "
                    "configuration, not clinical thresholds"),
    }
    numbers_doc = _round({**numbers, "latency.match.p50_ms": {"value": latency["p50_ms"], "n": latency["n"],
                                                               "method": latency["method"]},
                          "latency.match.p95_ms": {"value": latency["p95_ms"], "n": latency["n"],
                                                   "method": latency["method"]},
                          "latency.match.p99_ms": {"value": latency["p99_ms"], "n": latency["n"],
                                                   "method": latency["method"], "note": latency.get("note")},
                          "latency.machine": {"value": latency["machine"]}})
    run_doc = {"runId": run_id, "seed": cfg.seed, "commit": manifest["gitSha"], "syntheaSourceHash": None,
               "counts": {"records": len(corpus.records), "entities": len({t.entity_id for t in corpus.truth}),
                          "truePairsDevelopment": len(meta["truePairs"]), "blockedPairsDevelopment": len(meta["blockedPairs"]),
                          "allPairsDevelopment": meta["allPairsN"]},
               "graph": assignment.summary(corpus.records), "expectations": manifest["expectations"],
               "testRuns": 1 if cfg.include_test_pass else 0}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (run_dir / "numbers.json").write_text(json.dumps(numbers_doc, indent=2, sort_keys=True) + "\n")
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    (run_dir / "thresholds.json").write_text(json.dumps(_round(thresholds_doc), indent=2) + "\n")
    (run_dir / "run.json").write_text(json.dumps(run_doc, indent=2) + "\n")
    (run_dir / "splits.json").write_text(json.dumps(assignment.as_json(), indent=2) + "\n")
    (run_dir / "errors_by_band.csv").write_text(errors_by_band(scored, c_low, c_high))
    manifest_sha = hashlib.sha256((run_dir / "manifest.json").read_bytes()).hexdigest()
    (run_dir / "manifest.sha256").write_text(manifest_sha + "\n")
    return RunResult(run_id=run_id, run_dir=run_dir, numbers=numbers_doc, metrics=metrics, thresholds=selection,
                     manifest=manifest, assignment=assignment, corpus=corpus, weights=weights)


def _test_pass(corpus: Corpus, assignment: Assignment, cfg: RunConfig, weights: Mapping[str, float],
               c_low: float, c_high: float, seed: int, resamples: int) -> dict[str, dict]:
    """The single test pass: frozen scorer and thresholds, held-out components, scored once."""
    by_id = corpus.record_by_id()
    entity_of = corpus.entity_of()
    test_records = records_in(corpus, assignment, {PARTITION_TEST})
    blocked = cfg.block(test_records)
    truth = true_pairs_within(test_records, entity_of)
    scored = _score_pairs(blocked, by_id, entity_of, assignment, cfg.match, weights)
    n = len(test_records)
    out = {f"test.{k}": v for k, v in band_metrics(scored, len(truth), c_low, c_high, seed, resamples).items()}
    out.update({f"test.{k}": v for k, v in blocking_metrics(truth, blocked, n * (n - 1) // 2).items()})
    out.update({f"test.{k}": v for k, v in category_numbers(scored, c_low, c_high, cfg.families, seed, resamples).items()})
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fast", action="store_true", help="per-merge config: P0 families, one seed, development only")
    parser.add_argument("--seed", type=int, default=20261017)
    parser.add_argument("--test-pass", action="store_true", help="the single 20:00 test pass (never per merge)")
    parser.add_argument("--out", type=Path, default=RUNS_DIR)
    args = parser.parse_args(argv)
    cfg = RunConfig(name="fast" if args.fast else "development", seed=args.seed, fast=args.fast,
                    include_test_pass=args.test_pass, out_dir=args.out)
    try:
        result = run(cfg)
    except LeakageError as exc:
        print(f"LEAKAGE: {exc}", file=sys.stderr)
        return 2
    print(f"run {result.run_id} written to {result.run_dir}")
    print(json.dumps({k: v for k, v in result.metrics["invariants"].items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
