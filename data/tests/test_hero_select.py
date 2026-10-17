"""Hero selector: the midpoint candidate wins, the relaxation order holds, failure is reasoned."""
from __future__ import annotations

import hashlib
import json

import pytest

from data import hero_select as hs
from eval.harness import standin
from eval.harness.types import BAND_KEEP_SEPARATE, BAND_REVIEW, MatchResult, Record, band_for

C_LOW, C_HIGH = 0.0, 4.0
MID = 2.0


def _rec(rid: str, pid: str, system: str, **fields) -> Record:
    base = {"record_id": rid, "person_id": pid, "source_system": system, "entity_id": pid, "given_name": "Ana",
            "family_name": "García López", "birth_date": "1985-07-03", "sex": "FEMALE", "phone": "+19205550100",
            "address_line": "100 Oak St", "zip5": "54311", "language": "ES", "categories": [], "donor_person_ids": []}
    base.update(fields)
    return base


class FakeCorpus:
    """Two showcase entities with controllable baseline scores."""

    def __init__(self, records, languages):
        self.records = records
        self.person_language = languages
        self.truth = []

    def record_by_id(self):
        return {r["record_id"]: r for r in self.records}

    def entity_of(self):
        return {r["record_id"]: r["entity_id"] for r in self.records}


class FakeAssignment:
    def __init__(self, partition):
        self._p = partition

    def partition_of_person(self, pid):
        return self._p.get(pid, "development")


def _table_match(scores: dict[str, float], drops: dict[str, float]):
    """A match() whose raw score is a per-entity table, minus a drop per transform (keyed by what changed)."""

    def match(a: Record, b: Record, weights, thresholds) -> MatchResult:
        s = scores[a["person_id"]]  # person == entity in this fake; the intake rendering carries no entity id
        if a.get("address_line") is None:
            s -= drops.get("address", 0.0)
        if a["birth_date"][:4] != "1985":  # a year change; the day/month swap is a named feature and moves nothing
            s -= drops.get("dob", 0.0)
        if a["family_name"] != "García López":
            s -= drops.get("name", 0.0)
        if a["source_system"] == hs.INTAKE_SOURCE:
            s -= drops.get("intake", 0.0)
        return MatchResult(raw_score=s, p=standin.display_p(s, {}),
                           band=band_for(s, thresholds["c_low"], thresholds["c_high"]))

    return match


def _corpus(entities: dict[str, str]) -> tuple[FakeCorpus, FakeAssignment]:
    records = []
    for eid, lang in entities.items():
        records.append(_rec(f"{eid}-er", eid, "ER_FHIR", entity_id=eid, language=lang))
        records.append(_rec(f"{eid}-cl", eid, "CLINIC_CSV", entity_id=eid, language=lang))
    corpus = FakeCorpus(records, dict(entities))
    return corpus, FakeAssignment({eid: "showcase" for eid in entities})


def _select(scores, drops, entities, **kw):
    corpus, assignment = _corpus(entities)
    return hs.select_hero(corpus, assignment, _table_match(scores, drops), {}, C_LOW, C_HIGH, seed=1,
                          scorer_version="test", thresholds_id="t", **kw)


def test_returns_the_qualifier_closest_to_the_review_midpoint():
    # both qualify (band-changers drop below c_low, robustness moves nothing): the midpoint wins
    sel = _select({"E1": 1.0, "E2": 2.2}, {"address": 3.0, "dob": 3.0}, {"E1": "ES", "E2": "ES"})
    assert sel.ok and sel.hero.entity_id == "E2" and sel.relaxation_level == 0
    assert sel.qualifier_count_per_level == {"0": 2}
    assert sel.hero.criteria["baseline_review"] and sel.hero.criteria["intake_rendering_review"]


def test_ties_break_by_sha256_of_entity_id():
    sel = _select({"E1": 2.0, "E2": 2.0}, {"address": 3.0, "dob": 3.0}, {"E1": "ES", "E2": "ES"})
    expected = min(("E1", "E2"), key=lambda e: hashlib.sha256(e.encode()).hexdigest())
    assert sel.hero.entity_id == expected


def test_relaxation_order_drops_spanish_then_widens_tolerance():
    # only an EN entity qualifies: level 1
    sel = _select({"E1": 2.0}, {"address": 3.0, "dob": 3.0}, {"E1": "EN"})
    assert sel.ok and sel.relaxation_level == 1 and sel.qualifier_count_per_level == {"0": 0, "1": 1}
    # the accent/hyphen edit moves p by about 0.08: fails at 0.05, passes at 0.10 (level 2)
    sel = _select({"E1": 2.0}, {"address": 3.0, "dob": 3.0, "name": 0.6}, {"E1": "ES"})
    assert sel.ok and sel.relaxation_level == 2
    # only one birth-year direction drops: level 3 (either direction)
    corpus, assignment = _corpus({"E1": "ES"})

    def one_sided(a, b, weights, thresholds):
        s = 2.0
        if a.get("address_line") is None:
            s -= 3.0
        if a["birth_date"] == "1986-07-03":
            s -= 3.0
        from eval.harness.types import band_for

        return MatchResult(raw_score=s, p=standin.display_p(s, {}), band=band_for(s, C_LOW, C_HIGH))

    sel = hs.select_hero(corpus, assignment, one_sided, {}, C_LOW, C_HIGH, 1, "test", "t")
    assert sel.ok and sel.relaxation_level == 3


def test_baseline_review_is_never_relaxed_and_failure_is_reasoned():
    sel = _select({"E1": 5.0, "E2": -1.0}, {"address": 3.0, "dob": 3.0}, {"E1": "ES", "E2": "ES"})
    assert not sel.ok and sel.hero is None and sel.relaxation_level is None
    assert "no hero qualifies" in sel.reason and "best partial" in sel.reason
    assert sel.best_partial is not None and "baseline_review" in sel.best_partial.unmet()
    assert sel.qualifier_count_per_level == {"0": 0, "1": 0, "2": 0, "3": 0}
    as_json = json.dumps(sel.as_json())
    assert "published criteria" in as_json


def test_test_split_fallback_is_explicit():
    corpus, assignment = _corpus({"E1": "ES"})
    assignment._p["E1"] = "test"
    match = _table_match({"E1": 2.0}, {"address": 3.0, "dob": 3.0})
    sel = hs.select_hero(corpus, assignment, match, {}, C_LOW, C_HIGH, 1, "test", "t")
    assert not sel.ok and "fallback not enabled" in sel.reason
    sel = hs.select_hero(corpus, assignment, match, {}, C_LOW, C_HIGH, 1, "test", "t", allow_test_fallback=True)
    assert sel.ok and sel.drawn_from_test and "DRAWN FROM THE TEST SPLIT" in sel.reason


def test_intake_rendering_keeps_only_typed_fields():
    er = _rec("r", "p", "ER_FHIR", categories=["T1"], donor_person_ids=["x"])
    intake = hs.intake_rendering(er)
    assert intake["source_system"] == hs.INTAKE_SOURCE
    assert set(hs.INTAKE_FIELDS) <= set(intake) and intake["categories"] == [] and intake["donor_person_ids"] == []


def test_bounds_fail_when_a_what_if_raises_p():
    # the dob what-if raises the score (negative drop): fixture_check_bounds must fail
    sel = _select({"E1": 2.0}, {"address": 3.0, "dob": -1.0}, {"E1": "ES"})
    assert not sel.ok
    assert "fixture_check_bounds" in sel.best_partial.unmet()


@pytest.mark.parametrize("band", [BAND_REVIEW, BAND_KEEP_SEPARATE])
def test_bands_are_read_from_raw_cutoffs(band):
    from eval.harness.types import band_for

    s = MID if band == BAND_REVIEW else C_LOW - 1
    assert band_for(s, C_LOW, C_HIGH) == band
