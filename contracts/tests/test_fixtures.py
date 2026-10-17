"""scenario.json and hard_negative.json validate against the models."""
import json
from pathlib import Path

from contracts.models.alerts import CARD_FOOTER, SafetyAlert
from contracts.models.entities import Entity, TimelineEvent
from contracts.models.pairs import CandidatePairDetail
from contracts.models.records import SourceCard
from contracts.models.sessions import SessionResponse
from contracts.models.thresholds import ThresholdSet
from contracts.models.tiles import TilesResponse
from contracts.models.whatifs import WhatIfResponse

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _scenario() -> dict:
    return json.loads((FIXTURES / "scenario.json").read_text())


def test_scenario_sections_validate():
    s = _scenario()
    assert s["placeholder"] is True and s["hero"]["provisional"] is True
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


def test_scenario_pair_is_review_and_never_says_banned_words():
    s = _scenario()
    assert s["pair"]["pair"]["decision"]["band"] == "REVIEW"
    text = json.dumps(s).lower()
    for banned in ("prevented", "would have died", "the ai caught", "contraindicated for this patient", "fatal"):
        assert banned not in text, banned


def test_hard_negative_validates_and_is_keep_separate():
    h = json.loads((FIXTURES / "hard_negative.json").read_text())
    CandidatePairDetail.model_validate(h["pair"])
    assert h["pair"]["pair"]["decision"]["band"] == "KEEP_SEPARATE"
    assert "TWIN" in h["pair"]["pair"]["decision"]["negativeRulesFired"]
    SourceCard.model_validate(h["pair"]["recordA"])
