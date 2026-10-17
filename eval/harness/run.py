"""``run(config)``: the harness core (eval plan sections 3, 5, 9; architecture sections 6, 12).

Takes a corpus loader (W1's loader, or the in-repo synthetic fixture), a ``match`` callable with
W2's signature, a ``fit`` hook and a ``block`` callable, then: assigns the split contract,
scores development pairs out of fold, chooses ``c_low``/``c_high`` false-merge first, computes the
published numbers with n, measures ``match()`` latency in process and writes
``eval/runs/<run_id>/{manifest,numbers,metrics,thresholds,run,splits}.json``.

The command line measures the product: W1's corpus and W2's engine (``eval.harness.product``);
it exits non-zero when either is absent and never falls back. ``RunConfig``'s defaults (the in-repo
fixture and ``eval.harness.standin``) exist for the harness's own unit tests only.

``--fast`` is the per-merge config: P0 families, one seed, development components only. The test
partition is scored only with ``include_test_pass=True`` (the single 20:00 pass), never per merge.

    uv run python -m eval.harness.run --fast --seed 20261017 [--raw data/raw]
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
    assert_no_leakage,
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
ACCEPTANCE_DIR = REPO_ROOT / "eval" / "acceptance"
ACCEPTANCE_SKIP_DIRS = frozenset({"node_modules", "test-results", "playwright-report", "__pycache__"})
RUNS_DIR = REPO_ROOT / "eval" / "runs"
FAST_LATENCY = (20, 200)   # warm-up, timed: per merge
FULL_LATENCY = (latency_mod.WARMUP_CALLS, latency_mod.TIMED_CALLS)
EXPORT_DECIMALS = 6
EXIT_PRODUCT_UNAVAILABLE = 4


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
    provenance: dict = field(default_factory=dict)  # engine and corpus versions and hashes, into run.json


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


def acceptance_hashes(acceptance_dir: Path = ACCEPTANCE_DIR) -> dict[str, str]:
    """sha256 of every protected acceptance file (eval plan section 9), installed packages and reports excluded."""
    out: dict[str, str] = {}
    if not acceptance_dir.exists():
        return out
    for path in sorted(acceptance_dir.rglob("*")):
        rel = path.relative_to(acceptance_dir)
        if path.is_file() and not ACCEPTANCE_SKIP_DIRS & set(rel.parts):
            out[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def held_out_families(expectations: Mapping) -> frozenset[str]:
    """The seeded held-out families (config.json heldOutFamilies.drawn): never trained, tuned or run per merge."""
    return frozenset((expectations.get("heldOutFamilies") or {}).get("drawn") or ())


def without_held_out(records: Sequence[Record], held_out: frozenset[str]) -> list[Record]:
    """Development view: a record carrying a held-out corruption family is out of training, thresholds and
    per-merge metrics; it is scored once, in the test pass."""
    if not held_out:
        return list(records)
    return [r for r in records if not held_out & set(r.get("categories") or ())]


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


def _truth_pair(a_id: str, b_id: str, by_id: Mapping[str, Record], entity_of: Mapping[str, str],
                assignment: Assignment) -> ScoredPair:
    """A true pair blocking never proposed: its own entity and components, score -inf (never counted as found)."""
    a, b = by_id[a_id], by_id[b_id]
    return ScoredPair(record_a=a_id, record_b=b_id, entity_a=entity_of[a_id], entity_b=entity_of[b_id],
                      component_a=assignment.component_of_person[a["person_id"]],
                      component_b=assignment.component_of_person[b["person_id"]],
                      raw_score=float("-inf"), p=0.0, negative_rules_fired=(),
                      categories=tuple(sorted(set(a.get("categories") or ()) | set(b.get("categories") or ()))))


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


def out_of_fold(corpus: Corpus, assignment: Assignment, cfg: RunConfig,
                held_out: frozenset[str] = frozenset()) -> tuple[list[ScoredPair], dict]:
    """Grouped 5-fold out-of-fold scoring over development components (split steps 4 and 6).
    Only development records reach ``fit``, ``block`` and ``match``; held-out families are excluded."""
    by_id = corpus.record_by_id()
    entity_of = corpus.entity_of()
    units = development_units(assignment)
    scored: list[ScoredPair] = []
    true_keys: set[tuple[str, str]] = set()
    blocked_total: set[tuple[str, str]] = set()
    all_pairs_n = 0
    records_n = 0
    for unit in sorted(units):
        fold_records = without_held_out(records_in(corpus, assignment, {unit}), held_out)
        train_records = without_held_out(records_in(corpus, assignment, units - {unit}), held_out)
        train_ids = {r["record_id"] for r in train_records}
        train_truth = [t for t in corpus.truth if t.record_id in train_ids]
        weights = cfg.fit(train_records, train_truth)
        assert_fit_partition(train_ids, units - {unit}, corpus, assignment, f"scorer for {unit}")
        blocked = cfg.block(fold_records)
        true_keys |= true_pairs_within(fold_records, entity_of)
        blocked_total |= blocked
        n = len(fold_records)
        records_n += n
        all_pairs_n += n * (n - 1) // 2
        scored.extend(_score_pairs(blocked, by_id, entity_of, assignment, cfg.match, weights))
    true_objs = [_truth_pair(a, b, by_id, entity_of, assignment) for a, b in sorted(true_keys)]
    missed = [p for p in true_objs if (p.record_a, p.record_b) not in blocked_total]
    meta = {"truePairs": true_objs, "missedTrue": missed, "blockedPairs": blocked_total, "allPairsN": all_pairs_n,
            "records": records_n}
    return scored, meta


def candidate_pair_hash(corpus: Corpus, assignment: Assignment, cfg: RunConfig, held_out: frozenset[str]) -> str:
    """The idempotent-ingest pair-set hash, blocked fold by fold over development records only
    (section 9: the per-merge run never hands a test or showcase record to ``block``)."""
    pairs: set[tuple[str, str]] = set()
    for unit in sorted(development_units(assignment)):
        pairs |= cfg.block(without_held_out(records_in(corpus, assignment, {unit}), held_out))
    return hashlib.sha256(json.dumps(sorted(pairs)).encode()).hexdigest()


def category_numbers(pairs: Sequence[ScoredPair], missed_true: Sequence[ScoredPair], c_low: float, c_high: float,
                     families: Sequence[str], seed: int, resamples: int) -> dict[str, dict]:
    """Per-category (T2) and per-button (T15) recall over every eligible true pair, blocking misses included
    (end to end), plus the share blocking proposed. A pair blocking never proposed counts as missed."""
    out: dict[str, dict] = {}
    true_pairs = [p for p in pairs if p.is_match] + list(missed_true)
    blocked_ids = {(p.record_a, p.record_b) for p in pairs}

    def recall_cells(prefix: str, members: list[ScoredPair]) -> None:
        strict = [p for p in members if p.band(c_low, c_high) == "AUTO_LINK"]
        lenient = [p for p in members if p.band(c_low, c_high) != "KEEP_SEPARATE"]
        found = [p for p in members if (p.record_a, p.record_b) in blocked_ids]
        out[f"{prefix}.recall.strict"] = rate(strict, members, seed, resamples)
        out[f"{prefix}.recall.lenient"] = rate(lenient, members, seed, resamples)
        out[f"{prefix}.blocking_recall"] = rate(found, members, seed, resamples)

    for fam in families:
        if fam.startswith("N"):
            negatives = [p for p in pairs if not p.is_match and fam in p.categories]
            out[f"hard_negative.{fam}.auto_linked_wrongly"] = rate(
                [p for p in negatives if p.band(c_low, c_high) == "AUTO_LINK"], negatives, seed, resamples)
            out[f"hard_negative.{fam}.sent_to_review"] = rate(
                [p for p in negatives if p.band(c_low, c_high) == "REVIEW"], negatives, seed, resamples)
            continue
        recall_cells(f"category.{fam}", [p for p in true_pairs if fam in p.categories])
    for button in BUTTONS:
        cats = BUTTON_CATEGORIES[button]
        recall_cells(f"button.{button}", [p for p in true_pairs if any(c in p.categories for c in cats)])
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
    # one interval method everywhere: the configured resample count (1,000), per merge and at 20:00
    resamples = cfg.bootstrap_resamples or int(expectations["bootstrapResamples"])
    held_out = held_out_families(expectations)
    families = tuple(f for f in cfg.families if f not in held_out)
    warmup, timed = cfg.latency_calls or (FAST_LATENCY if cfg.fast else FULL_LATENCY)
    bootstrap_seed = int(expectations["bootstrapSeed"]) ^ cfg.seed

    def load() -> Corpus:
        if cfg.corpus_loader is not None:
            return cfg.corpus_loader()
        return build_fixture(cfg.fixture or FixtureConfig(seed=cfg.seed, families=cfg.families))

    def split_of(c: Corpus) -> Assignment:
        if c.assignment is None:
            return assign(c, split_cfg)  # raises LeakageError on any hit
        assert_no_leakage(c, c.assignment)  # the generator's own split, checked the same way
        return c.assignment

    corpus = load()
    fixture_hashes = corpus_hashes(corpus)
    assignment = split_of(corpus)
    # invariant: idempotent ingest. Loading twice gives the same records, truth, split and candidate-pair set
    second = load()
    second_assignment = split_of(second)
    idempotent = (fixture_hashes == corpus_hashes(second) and len(corpus.records) == len(second.records)
                  and assignment.as_json() == second_assignment.as_json()
                  and candidate_pair_hash(corpus, assignment, cfg, held_out)
                  == candidate_pair_hash(second, second_assignment, cfg, held_out))
    scored, meta = out_of_fold(corpus, assignment, cfg, held_out)
    selection = select_thresholds(scored, threshold_cfg)
    c_low, c_high = selection.c_low, selection.c_high
    thresholds_id = thresholds_id_for(selection, cfg.scorer_version, fixture_hashes)

    numbers: dict[str, dict] = {}
    numbers.update(band_metrics(scored, meta["missedTrue"], c_low, c_high, bootstrap_seed, resamples))
    numbers.update(blocking_metrics(meta["truePairs"], meta["blockedPairs"], meta["allPairsN"], bootstrap_seed,
                                    resamples))
    numbers.update(category_numbers(scored, meta["missedTrue"], c_low, c_high, families, bootstrap_seed, resamples))
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
    dev_records = without_held_out(records_in(corpus, assignment, dev_units), held_out)
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
        "seed": cfg.seed, "families": list(families), "heldOutFamilies": sorted(held_out),
        "fixtureHashes": fixture_hashes,
        "benchmarkCommit": None, "split": assignment.summary(corpus.records), "scorerVersion": cfg.scorer_version,
        "thresholdSetId": thresholds_id, "thresholds": {"cLow": c_low, "cHigh": c_high},
        "gitSha": git_sha(), "shards": 1, "bootstrapResamples": resamples, "bootstrapSeed": bootstrap_seed,
        "expectations": expectations_hashes(cfg.expectations_dir), "acceptance": acceptance_hashes(),
        "provenance": cfg.provenance or {"engine": "eval.harness.standin", "corpus": "eval.harness.fixture",
                                         "note": "harness self-test inputs; not a product measurement"},
        "heldOutNote": ("no held-out families drawn (config.json heldOutFamilies.drawn is empty): no held-out-family "
                        "figure is published" if not held_out else "held-out families excluded per merge"),
        **cfg.extra_manifest,
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
               "acceptance": manifest["acceptance"], "heldOutFamilies": sorted(held_out),
               "provenance": manifest["provenance"], "heldOutNote": manifest["heldOutNote"],
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
    true_objs = [_truth_pair(a, b, by_id, entity_of, assignment)
                 for a, b in sorted(true_pairs_within(test_records, entity_of))]
    missed = [p for p in true_objs if (p.record_a, p.record_b) not in blocked]
    scored = _score_pairs(blocked, by_id, entity_of, assignment, cfg.match, weights)
    n = len(test_records)
    out = {f"test.{k}": v for k, v in band_metrics(scored, missed, c_low, c_high, seed, resamples).items()}
    out.update({f"test.{k}": v for k, v in blocking_metrics(true_objs, blocked, n * (n - 1) // 2, seed,
                                                              resamples).items()})
    out.update({f"test.{k}": v for k, v in category_numbers(scored, missed, c_low, c_high, cfg.families, seed,
                                                              resamples).items()})
    return out


def product_config(args: argparse.Namespace) -> RunConfig:
    """The production command's inputs: W1's corpus and W2's engine, or ``ProductUnavailable``."""
    from eval.harness import product

    engine = product.load_engine()
    corpus_provenance: dict = {}

    def loader() -> Corpus:
        corpus, prov = product.load_corpus(args.seed, args.raw)
        corpus_provenance.update(prov)
        return corpus

    loader()  # fail before the run starts if the corpus is absent; also fills the provenance
    return RunConfig(name="fast" if args.fast else "development", seed=args.seed, fast=args.fast,
                     include_test_pass=args.test_pass, out_dir=args.out, corpus_loader=loader,
                     match=engine.match, fit=engine.fit, block=engine.block, scorer_version=engine.scorer_version,
                     provenance={"engine": engine.provenance, "corpus": corpus_provenance})


def main(argv: Sequence[str] | None = None) -> int:
    from eval.harness.product import DEFAULT_RAW_DIR, ProductUnavailable

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fast", action="store_true", help="per-merge config: P0 families, one seed, development only")
    parser.add_argument("--seed", type=int, default=20261017)
    parser.add_argument("--test-pass", action="store_true", help="the single 20:00 test pass (never per merge)")
    parser.add_argument("--out", type=Path, default=RUNS_DIR)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW_DIR, help="extracted Synthea sample (data/download.py)")
    args = parser.parse_args(argv)
    try:
        cfg = product_config(args)
    except ProductUnavailable as exc:
        print(f"PRODUCT UNAVAILABLE: {exc}", file=sys.stderr)
        return EXIT_PRODUCT_UNAVAILABLE
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
