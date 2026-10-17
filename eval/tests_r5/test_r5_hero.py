"""R5: hero selector (architecture 9.1; eval plan 3): midpoint tie-break, relaxation, reasoned failure,
exported scenario validity and caption honesty."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from contracts.models.alerts import CARD_FOOTER, SafetyAlert
from contracts.models.entities import Entity, TimelineEvent
from contracts.models.pairs import CandidatePairDetail
from contracts.models.sessions import SessionResponse
from contracts.models.thresholds import ThresholdSet
from contracts.models.tiles import TilesResponse
from contracts.models.whatifs import WhatIfResponse
from data import hero_select as hs
from eval.harness import standin
from eval.harness.types import BAND_KEEP_SEPARATE, MatchResult, Record, band_for

HERO_DIR = Path(__file__).resolve().parents[2] / "data" / "scenarios" / "hero"
C_LOW, C_HIGH = 0.0, 4.0
MID = 2.0


def _rec(rid, pid, system, **fields) -> Record:
    base = {"record_id": rid, "person_id": pid, "source_system": system, "entity_id": pid, "given_name": "Ana",
            "family_name": "García López", "birth_date": "1985-07-03", "sex": "FEMALE", "phone": "+19205550100",
            "address_line": "100 Oak St", "zip5": "54311", "language": "ES", "categories": [], "donor_person_ids": []}
    base.update(fields)
    return base


class FakeCorpus:
    def __init__(self, records, languages):
        self.records, self.person_language, self.truth = records, languages, []

    def record_by_id(self):
        return {r["record_id"]: r for r in self.records}

    def entity_of(self):
        return {r["record_id"]: r["entity_id"] for r in self.records}


class FakeAssignment:
    def __init__(self, partition):
        self._p = partition

    def partition_of_person(self, pid):
        return self._p.get(pid, "development")


def _match(scores):
    def match(a, b, weights, thresholds) -> MatchResult:
        s = scores[a["person_id"]]
        if a.get("address_line") is None or a["birth_date"][:4] != "1985":
            s -= 3.0
        return MatchResult(raw_score=s, p=standin.display_p(s, {}), band=band_for(s, thresholds["c_low"], thresholds["c_high"]))
    return match


def _corpus(entities):
    records = []
    for eid, lang in entities.items():
        records += [_rec(f"{eid}-er", eid, "ER_FHIR", language=lang), _rec(f"{eid}-cl", eid, "CLINIC_CSV", language=lang)]
    return FakeCorpus(records, dict(entities)), FakeAssignment({e: "showcase" for e in entities})


def test_equidistant_candidates_on_either_side_of_the_midpoint_tie_and_sha256_decides():
    corpus, assignment = _corpus({"E7": "ES", "E8": "ES", "E9": "ES"})
    sel = hs.select_hero(corpus, assignment, _match({"E7": MID - 0.5, "E8": MID + 0.5, "E9": MID + 0.8}), {},
                         C_LOW, C_HIGH, 1, "t", "t")
    assert sel.ok and sel.relaxation_level == 0 and sel.qualifier_count_per_level["0"] == 3
    expected = min(("E7", "E8"), key=lambda e: hashlib.sha256(e.encode()).hexdigest())
    assert sel.hero.entity_id == expected
    assert [c.entity_id for c in sel.candidates][:2] == sorted(("E7", "E8"), key=lambda e: hashlib.sha256(e.encode()).hexdigest())


def test_relaxation_stops_at_the_first_level_with_a_qualifier_and_failure_is_reasoned():
    corpus, assignment = _corpus({"E1": "EN"})
    sel = hs.select_hero(corpus, assignment, _match({"E1": MID}), {}, C_LOW, C_HIGH, 1, "t", "t")
    assert sel.ok and sel.relaxation_level == 1 and list(sel.qualifier_count_per_level) == ["0", "1"]
    corpus, assignment = _corpus({"E1": "ES"})
    sel = hs.select_hero(corpus, assignment, _match({"E1": 9.0}), {}, C_LOW, C_HIGH, 1, "t", "t")
    assert not sel.ok and sel.hero is None and sel.best_partial is not None
    assert "no hero qualifies" in sel.reason and "baseline_review" in sel.best_partial.unmet()
    assert sel.qualifier_count_per_level == {"0": 0, "1": 0, "2": 0, "3": 0}


def test_exported_scenario_validates_against_the_contract_models_and_is_provisional():
    s = json.loads((HERO_DIR / "scenario.json").read_text())
    assert s["hero"]["provisional"] is True and s["session"]["heroProvisional"] is True
    assert s["placeholder"] is False
    SessionResponse.model_validate(s["session"])
    CandidatePairDetail.model_validate(s["pair"])
    Entity.model_validate(s["entityIfApproved"])
    for ev in s["timelineIfApproved"]:
        TimelineEvent.model_validate(ev)
    alert = SafetyAlert.model_validate(s["alertIfApproved"])
    assert alert.card_footer == CARD_FOOTER and alert.constructed_scenario and alert.tier == "A"
    ThresholdSet.model_validate(s["thresholds"])
    TilesResponse.model_validate(s["tiles"])
    for wi in s["whatIfs"].values():
        WhatIfResponse.model_validate(wi)
    assert set(s["whatIfs"]) == {"REMOVE_ADDRESS", "CHANGE_BIRTH_YEAR", "SWAP_DOB_DAY_MONTH", "ACCENT_HYPHEN_SURNAME"}
    assert s["pair"]["pair"]["decision"]["band"] == "REVIEW"


def test_every_exported_what_if_caption_matches_the_band_it_ships_with():
    """Architecture 9.1: 'the pitch narrates the band changes that actually occur and does not claim any
    others'. A caption that says 'not enough to link' must ship with a KEEP_SEPARATE band."""
    s = json.loads((HERO_DIR / "scenario.json").read_text())
    wrong = {}
    for button, wi in s["whatIfs"].items():
        caption = wi["caption"].lower()
        band = wi["whatIf"]["band"]
        if "not enough to link" in caption and band != BAND_KEEP_SEPARATE:
            wrong[button] = (caption, band, wi["alertWouldBeHidden"])
        if band == BAND_KEEP_SEPARATE:
            assert wi["alertWouldBeHidden"] is True, button
    assert wrong == {}, f"caption claims a band change that the export's own band denies: {wrong}"


def test_hero_criteria_report_is_evaluated_at_the_level_it_claims():
    """scenario.json.hero.criteria must not read 'spanish_name: true' for an EN hero. The report is evaluated at
    the most relaxed level, which silently flips the Spanish criterion to true."""
    s = json.loads((HERO_DIR / "scenario.json").read_text())
    hero = json.loads((HERO_DIR / "hero.json").read_text())
    lang = hero["records"]["ER_FHIR"]["language"]
    if lang != "ES":
        assert s["hero"]["criteria"]["spanish_name"] is False, "EN hero reported as satisfying the Spanish-name criterion"
