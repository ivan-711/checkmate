"""R5: attacks on the split contract (eval plan section 3; section 9 fast config)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from eval.harness import standin
from eval.harness.fixture import FixtureConfig, build_fixture
from eval.harness.run import EXPECTATIONS_DIR, RunConfig, run
from eval.harness.splits import LeakageError, assert_no_leakage, assign
from eval.harness.types import PARTITION_DEVELOPMENT, PARTITION_SHOWCASE, PARTITION_TEST

FIX = FixtureConfig(seed=20261017, entities=120, hard_negative_pairs=16)


def _corpus():
    return build_fixture(FIX)


def test_fast_config_never_passes_a_test_or_showcase_record_to_block_or_match(tmp_path: Path):
    """Section 9: the per-merge config never touches the test partition or the showcase pool.
    A sentinel block()/match() raises the moment a non-development record reaches it."""
    reference = assign(_corpus())
    seen: list[str] = []

    def guard(records):
        for r in records:
            part = reference.partition_of_person(r["person_id"])
            if part != PARTITION_DEVELOPMENT:
                seen.append(f"{r['record_id']} ({part})")

    def block(records):
        guard(records)
        return standin.block(records)

    def match(a, b, weights, thresholds):
        guard([a, b])
        return standin.match(a, b, weights, thresholds)

    run(RunConfig(name="fast", seed=FIX.seed, fast=True, out_dir=tmp_path, fixture=FIX, block=block, match=match))
    assert seen == [], f"--fast handed non-development records to block()/match(): {seen[:5]} (+{max(len(seen) - 5, 0)})"


def test_entity_split_across_partitions_trips_the_leakage_assertion():
    """Step 5: no record derived from a source person appears on both sides of the dev/test boundary.
    Two fragments of ONE entity that carry different person ids in different partitions are such a leak."""
    corpus = _corpus()
    assignment = assign(corpus)
    by_entity: dict[str, list] = {}
    for r in corpus.records:
        by_entity.setdefault(r["entity_id"], []).append(r)
    victim = next(recs for recs in by_entity.values() if len(recs) >= 2 and not recs[1]["donor_person_ids"])
    unit = assignment.unit_of_person(victim[0]["person_id"])
    other = next(p for p in assignment.component_of_person if assignment.unit_of_person(p) != unit)
    victim[1]["person_id"] = other  # the second fragment now sits in another partition
    with pytest.raises(LeakageError):
        assert_no_leakage(corpus, assignment)


def test_showcase_component_carrying_a_fold_trips():
    corpus = _corpus()
    assignment = assign(corpus)
    cid = next(c for c, p in assignment.partition_of_component.items() if p == PARTITION_SHOWCASE)
    assignment.fold_of_component[cid] = 0
    with pytest.raises(LeakageError):
        assert_no_leakage(corpus, assignment)


def test_component_moved_to_test_while_keeping_its_fold_trips():
    corpus = _corpus()
    assignment = assign(corpus)
    cid = next(c for c, p in assignment.partition_of_component.items() if p == PARTITION_DEVELOPMENT)
    assignment.partition_of_component[cid] = PARTITION_TEST
    with pytest.raises(LeakageError):
        assert_no_leakage(corpus, assignment)


def test_unassigned_person_trips():
    corpus = _corpus()
    assignment = assign(corpus)
    corpus.records[0]["person_id"] = "P9999"
    with pytest.raises(LeakageError):
        assert_no_leakage(corpus, assignment)


def test_showcase_pool_is_fixed_first_and_disjoint():
    """Step 2: the 20 lowest component hashes are the pool, whatever the dev/test split does."""
    from eval.harness.splits import component_hash

    corpus = _corpus()
    a = assign(corpus)
    pool = sorted(c for c, p in a.partition_of_component.items() if p == PARTITION_SHOWCASE)
    assert pool == sorted(sorted(a.components, key=component_hash)[:20])
    units = {a.unit_of_person(p) for p in a.component_of_person}
    assert "showcase" in units and "test" in units and len([u for u in units if u.startswith("development:")]) == 5


def test_held_out_families_are_excluded_from_the_fast_run(tmp_path: Path):
    """Section 3/9: held-out families are excluded from training, Platt fitting and threshold choice and
    never run per merge. When config.json names a drawn family, the fast run must not score it."""
    exp = tmp_path / "expectations"
    shutil.copytree(EXPECTATIONS_DIR, exp, ignore=shutil.ignore_patterns("__pycache__"))
    cfg = json.loads((exp / "config.json").read_text())
    cfg["heldOutFamilies"]["drawn"] = ["T1"]
    (exp / "config.json").write_text(json.dumps(cfg))
    result = run(RunConfig(name="fast", seed=FIX.seed, fast=True, out_dir=tmp_path / "runs", fixture=FIX,
                           expectations_dir=exp))
    assert "T1" not in result.manifest["families"], "a held-out family was run per merge"
    assert not any(k.startswith("category.T1.") for k in result.numbers)
