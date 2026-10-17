"""Leakage assertions (eval plan section 3, step 5): the build fails on any hit."""
from __future__ import annotations

import pytest

from eval.harness.fixture import FixtureConfig, build_fixture
from eval.harness.splits import LeakageError, SplitConfig, assert_fit_partition, assert_no_leakage, assign
from eval.harness.types import PARTITION_DEVELOPMENT, PARTITION_SHOWCASE, PARTITION_TEST


def _corpus():
    return build_fixture(FixtureConfig(seed=20261017, entities=120, hard_negative_pairs=16))


def test_every_partition_is_populated_and_disjoint():
    corpus = _corpus()
    assignment = assign(corpus, SplitConfig())
    parts = set(assignment.partition_of_component.values())
    assert parts == {PARTITION_SHOWCASE, PARTITION_DEVELOPMENT, PARTITION_TEST}
    assert sum(1 for p in assignment.partition_of_component.values() if p == PARTITION_SHOWCASE) == 20
    for cid, part in assignment.partition_of_component.items():
        assert (cid in assignment.fold_of_component) == (part == PARTITION_DEVELOPMENT)


def test_graft_recipient_inherits_donor_partition():
    corpus = _corpus()
    assignment = assign(corpus)
    for rec in corpus.records:
        for donor in rec["donor_person_ids"]:
            assert assignment.unit_of_person(donor) == assignment.unit_of_person(rec["person_id"])


def test_planted_leak_trips_the_assertion():
    corpus = _corpus()
    assignment = assign(corpus)
    victim = next(r for r in corpus.records if not r["donor_person_ids"])
    unit = assignment.unit_of_person(victim["person_id"])
    other = next(p for p in assignment.component_of_person if assignment.unit_of_person(p) != unit)
    victim["donor_person_ids"] = [other]  # a record that borrows a field across the boundary
    with pytest.raises(LeakageError):
        assert_no_leakage(corpus, assignment)


def test_fit_on_the_wrong_partition_trips_the_assertion():
    corpus = _corpus()
    assignment = assign(corpus)
    test_record = next(r for r in corpus.records if assignment.partition_of_person(r["person_id"]) == PARTITION_TEST)
    with pytest.raises(LeakageError):
        assert_fit_partition({test_record["record_id"]}, {"development:0"}, corpus, assignment, "scorer")
