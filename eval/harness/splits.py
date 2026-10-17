"""The executable split contract (eval plan section 3, steps 1, 2, 4, 5, 6).

1. Dependency graph first: nodes are source persons, edges are every donor/recipient relation.
2. Assign whole components once, by sha256 of the component's smallest person id: the showcase
   pool first (fixed count), then development/test stratified by language, development
   components to k CV folds in the same pass.
4. Ordinary negatives pair only within a partition (the same fold inside development).
5. Leakage assertions: no person, and no record derived from one, in more than one fold, on both
   sides of the development/test boundary, or in the showcase pool and any other partition.
6. Every fitted object's row ids are checked against its allowed partition.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from eval.harness.types import (
    PARTITION_DEVELOPMENT,
    PARTITION_SHOWCASE,
    PARTITION_TEST,
    Corpus,
    Record,
)


class LeakageError(AssertionError):
    """A split invariant failed; the build is red."""


@dataclass(frozen=True)
class SplitConfig:
    showcase_pool_components: int = 20
    development_fraction: float = 0.70
    folds: int = 5
    stratify_by_language: bool = True


@dataclass
class Assignment:
    """Component id to partition, plus the derived lookups the harness uses everywhere."""

    component_of_person: dict[str, str]
    partition_of_component: dict[str, str]  # showcase | development | test
    fold_of_component: dict[str, int]  # development components only
    components: dict[str, list[str]] = field(default_factory=dict)  # component id -> person ids

    def partition_of_person(self, person_id: str) -> str:
        return self.partition_of_component[self.component_of_person[person_id]]

    def fold_of_person(self, person_id: str) -> int | None:
        return self.fold_of_component.get(self.component_of_person[person_id])

    def unit_of_person(self, person_id: str) -> str:
        """The pairing unit of step 4: showcase, test, or development fold k."""
        partition = self.partition_of_person(person_id)
        if partition == PARTITION_DEVELOPMENT:
            return f"{PARTITION_DEVELOPMENT}:{self.fold_of_person(person_id)}"
        return partition

    def as_json(self) -> dict:
        return {
            "partitionOfComponent": dict(sorted(self.partition_of_component.items())),
            "foldOfComponent": dict(sorted(self.fold_of_component.items())),
            "components": {k: sorted(v) for k, v in sorted(self.components.items())},
        }

    def summary(self, records: Sequence[Record]) -> dict:
        per_partition = {PARTITION_SHOWCASE: 0, PARTITION_DEVELOPMENT: 0, PARTITION_TEST: 0}
        for part in self.partition_of_component.values():
            per_partition[part] += 1
        records_per_component: dict[str, int] = {}
        for rec in records:
            cid = self.component_of_person[rec["person_id"]]
            records_per_component[cid] = records_per_component.get(cid, 0) + 1
        largest = max(self.components, key=lambda c: (len(self.components[c]), c)) if self.components else None
        return {
            "componentCount": len(self.components),
            "componentsPerPartition": per_partition,
            "foldSizes": {str(k): sum(1 for f in self.fold_of_component.values() if f == k)
                          for k in sorted(set(self.fold_of_component.values()))},
            "largestComponent": None if largest is None else {
                "id": largest, "persons": len(self.components[largest]),
                "records": records_per_component.get(largest, 0)},
        }


def _components(persons: Iterable[str], edges: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    parent: dict[str, str] = {p: p for p in persons}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups: dict[str, list[str]] = {}
    for p in parent:
        groups.setdefault(find(p), []).append(p)
    # the component id is its smallest person id (section 3 step 2)
    return {min(members): sorted(members) for members in groups.values()}


def component_hash(component_id: str) -> str:
    return hashlib.sha256(component_id.encode()).hexdigest()


def assign(corpus: Corpus, cfg: SplitConfig | None = None) -> Assignment:
    """Step 1 and step 2. Pure function of the dependency graph and the config: no seed."""
    cfg = cfg or SplitConfig()
    persons ={r["person_id"] for r in corpus.records} | {t.synthea_patient_id for t in corpus.truth}
    for rec in corpus.records:
        persons.update(rec.get("donor_person_ids") or ())
    edges = list(corpus.dependency_edges)
    for rec in corpus.records:  # any record that borrows a field from another person is an edge
        for donor in rec.get("donor_person_ids") or ():
            edges.append((rec["person_id"], donor))
    components = _components(persons, edges)
    component_of_person = {p: cid for cid, members in components.items() for p in members}
    ordered = sorted(components, key=component_hash)
    partition: dict[str, str] = {}
    fold: dict[str, int] = {}
    pool = ordered[: cfg.showcase_pool_components]
    for cid in pool:
        partition[cid] = PARTITION_SHOWCASE
    rest = ordered[cfg.showcase_pool_components:]

    def language_of(cid: str) -> str:
        langs = [corpus.person_language.get(p, "EN") for p in components[cid]]
        return "ES" if langs.count("ES") * 2 >= len(langs) and "ES" in langs else "EN"

    strata: dict[str, list[str]] = {}
    for cid in rest:
        strata.setdefault(language_of(cid) if cfg.stratify_by_language else "ALL", []).append(cid)
    for stratum in sorted(strata):
        members = strata[stratum]  # already in hash order
        n_dev = round(len(members) * cfg.development_fraction)
        for i, cid in enumerate(members):
            if i < n_dev:
                partition[cid] = PARTITION_DEVELOPMENT
                fold[cid] = i % cfg.folds  # round-robin in hash order balances the folds
            else:
                partition[cid] = PARTITION_TEST
    assignment = Assignment(component_of_person=component_of_person, partition_of_component=partition,
                            fold_of_component=fold, components=components)
    assert_no_leakage(corpus, assignment)
    return assignment


def assert_no_leakage(corpus: Corpus, assignment: Assignment) -> None:
    """Step 5. Raises ``LeakageError`` on the first violation."""
    seen_unit: dict[str, str] = {}
    for rec in corpus.records:
        person = rec["person_id"]
        unit = assignment.unit_of_person(person)
        derived = [person, *(rec.get("donor_person_ids") or ())]
        for pid in derived:
            if pid not in assignment.component_of_person:
                raise LeakageError(f"person {pid} (record {rec['record_id']}) is not assigned to any component")
            other = assignment.unit_of_person(pid)
            if other != unit:
                raise LeakageError(
                    f"record {rec['record_id']} derives from {pid} in {other} but sits in {unit}")
            previous = seen_unit.setdefault(pid, unit)
            if previous != unit:
                raise LeakageError(f"person {pid} appears in {previous} and {unit}")
    for cid, part in assignment.partition_of_component.items():
        if part == PARTITION_DEVELOPMENT and cid not in assignment.fold_of_component:
            raise LeakageError(f"development component {cid} has no fold")
        if part != PARTITION_DEVELOPMENT and cid in assignment.fold_of_component:
            raise LeakageError(f"{part} component {cid} carries a CV fold")


def assert_fit_partition(seen_record_ids: Iterable[str], allowed_units: set[str], corpus: Corpus,
                         assignment: Assignment, what: str) -> None:
    """Step 6: a fitted object's row ids must lie inside its allowed partition."""
    by_id = corpus.record_by_id()
    for rid in seen_record_ids:
        unit = assignment.unit_of_person(by_id[rid]["person_id"])
        if unit not in allowed_units:
            raise LeakageError(f"{what} was fitted on record {rid} from {unit}; allowed {sorted(allowed_units)}")


def records_in(corpus: Corpus, assignment: Assignment, units: set[str]) -> list[Record]:
    return [r for r in corpus.records if assignment.unit_of_person(r["person_id"]) in units]


def development_units(assignment: Assignment) -> set[str]:
    return {f"{PARTITION_DEVELOPMENT}:{k}" for k in set(assignment.fold_of_component.values())}


def write_splits(assignment: Assignment) -> Mapping:
    return assignment.as_json()
