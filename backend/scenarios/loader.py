"""Scenario loading seam for ``POST /sessions``.

STAND-IN for lane W1's loader. W1 replaces ``load_scenario`` with the real Synthea/CSV
loader over ``data/scenarios/<id>/`` and keeps the signature:

    load_scenario(scenario_id: str) -> Scenario   (raises ScenarioNotFound)

Until then the known scenarios are read from the frozen fixture shapes in
``contracts/fixtures/scenario.json`` (watermarked placeholders): ``hero`` loads every
source card; ``frontdesk-hero`` loads all but the ER FHIR record, because the intake
plays the ER registration (architecture §9.1).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from contracts.models.records import SourceCard

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "scenario.json"
ER_SOURCE_SYSTEM = "ER_FHIR"


class ScenarioNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    sources: list[SourceCard]
    hero_provisional: bool
    hero_constructed_floor: bool


@cache
def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def load_scenario(scenario_id: str) -> Scenario:
    fx = _fixture()
    cards = [SourceCard.model_validate(s) for s in fx["session"]["sources"]]
    if scenario_id == "hero":
        sources = cards
    elif scenario_id == "frontdesk-hero":
        sources = [c for c in cards if c.record.source_system != ER_SOURCE_SYSTEM]
    else:
        raise ScenarioNotFound(scenario_id)
    hero = fx.get("hero", {})
    return Scenario(
        scenario_id=scenario_id,
        sources=sources,
        hero_provisional=bool(hero.get("provisional", True)),
        hero_constructed_floor=bool(hero.get("constructedFloor", False)),
    )
