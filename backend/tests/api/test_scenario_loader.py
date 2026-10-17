"""The scenario loader's two sources, through the real POST /sessions route.

Fixture mode is the default and needs nothing from W1. Here corpus mode is tested at the W1 boundary
(``_w1_corpus_drafts``, ``_w1_normalize``) with W5's real overlay files: the mode switch, which hero
directory is read, and what the loader refuses. End-to-end corpus tests on W1's real loaders are in
test_sessions_showcase.py.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace

import pytest

from backend.scenarios import loader
from backend.tests.api.conftest import API
from backend.tests.api.hero_corpus import write_hero_dir

KIND = {"ER_FHIR": "FHIR_PATIENT", "CLINIC_CSV": "CSV_ROW"}


@dataclass
class Draft:
    """The shape of W1's ``SourceRecordDraft`` the loader reads."""

    source_system: str
    source_local_id: str
    identity: dict
    is_constructed: bool = False
    raw_payload: dict = field(default_factory=dict)

    @property
    def id(self) -> uuid.UUID:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"{self.source_system}/{self.source_local_id}")

    @property
    def kind(self) -> str:
        return KIND[self.source_system]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.source_local_id.encode()).hexdigest()


def _normalize(identity: dict) -> SimpleNamespace:
    return SimpleNamespace(
        given_name=identity["given"],
        family_name=identity["family"],
        given_name_folded=identity["given"].lower(),
        family_name_folded=identity["family"].lower(),
        birth_date=date(1990, 5, 6),
        sex="FEMALE",
        phone_e164=None,
        address_line=None,
        zip5="53703",
    )


HERO_ER = Draft("ER_FHIR", "corpus-er-1", {"given": "Ana", "family": "Ruiz"}, raw_payload={"patient": {"id": "er-1"}})
HERO_CLINIC = Draft("CLINIC_CSV", "corpus-clinic-1", {"given": "Ana", "family": "Ruiz"}, raw_payload={"patient": {}})
OTHER = Draft("ER_FHIR", "corpus-er-2", {"given": "Bo", "family": "Lee"})


@pytest.fixture
def corpus_mode(monkeypatch, tmp_path):
    """Fake W1 corpus; the hero directory is W5's real overlay plus a hero.json naming the fake hero."""
    hero_dir = write_hero_dir(tmp_path, str(HERO_ER.id), str(HERO_CLINIC.id))
    read: list = []
    real_read = loader._read_hero_dir

    def spy(path):
        read.append(path)
        return real_read(path)

    monkeypatch.setenv("CHECKMATE_HERO_SOURCE", "corpus")
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(hero_dir))
    monkeypatch.setattr(loader, "_w1_corpus_drafts", lambda seed, raw_dir: [HERO_ER, HERO_CLINIC, OTHER])
    monkeypatch.setattr(loader, "_w1_normalize", _normalize)
    monkeypatch.setattr(loader, "_read_hero_dir", spy)
    loader._corpus_cards.cache_clear()
    yield SimpleNamespace(hero_dir=hero_dir, read=read, tmp=tmp_path)
    loader._corpus_cards.cache_clear()


def test_fixture_is_the_default_source(client, monkeypatch):
    monkeypatch.delenv("CHECKMATE_HERO_SOURCE", raising=False)
    fixture_ids = {s["record"]["id"] for s in loader._fixture()["session"]["sources"]}
    r = client.post(f"{API}/sessions", json={"scenarioId": "hero"})
    assert r.status_code == 201, r.text
    assert {s["record"]["id"] for s in r.json()["sources"]} == fixture_ids
    monkeypatch.setenv("CHECKMATE_HERO_SOURCE", "fixture")
    assert {c.record.id for c in loader.load_scenario("hero").sources} == {uuid.UUID(i) for i in fixture_ids}


def test_unknown_hero_source_is_refused(monkeypatch):
    monkeypatch.setenv("CHECKMATE_HERO_SOURCE", "bogus")
    with pytest.raises(ValueError, match="CHECKMATE_HERO_SOURCE"):
        loader.load_scenario("hero")


def test_corpus_mode_showcase_is_hero_json_er_first(corpus_mode):
    scenario = loader.load_scenario("hero")
    assert [c.record.id for c in scenario.showcase] == [HERO_ER.id, HERO_CLINIC.id]
    assert {c.record.id for c in scenario.sources} == {HERO_ER.id, HERO_CLINIC.id, OTHER.id}
    assert next(c for c in scenario.sources if c.record.id == OTHER.id).record.is_constructed is False


def test_corpus_mode_reads_the_hero_dir_from_the_env_var(corpus_mode):
    loader.load_scenario("hero")
    assert corpus_mode.read == [corpus_mode.hero_dir]


def test_corpus_mode_hero_dir_defaults_to_data_scenarios_hero(corpus_mode, monkeypatch, caplog):
    import logging

    monkeypatch.delenv("CHECKMATE_HERO_OVERLAY_DIR")
    monkeypatch.setattr(loader, "HERO_OVERLAY_DIR", corpus_mode.tmp / "data" / "scenarios" / "hero")
    with caplog.at_level(logging.WARNING, logger="checkmate.scenarios"), pytest.raises(loader.HeroNotFound):
        loader.load_scenario("hero")  # nothing exported there: refused, and the log names where it looked
    assert str(loader.HERO_OVERLAY_DIR) in caplog.text
    assert loader.HERO_OVERLAY_DIR.parts[-3:] == ("data", "scenarios", "hero")


def test_corpus_mode_honors_a_changed_hero_dir(corpus_mode, monkeypatch):
    """The corpus is cached per (seed, raw dir, hero dir): pointing the env var elsewhere reloads."""
    loader.load_scenario("hero")
    other = write_hero_dir(corpus_mode.tmp / "b", str(HERO_ER.id), str(HERO_CLINIC.id))
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(other))
    loader.load_scenario("hero")
    assert corpus_mode.read == [corpus_mode.hero_dir, other]


def test_hero_json_naming_a_record_outside_the_corpus_is_refused(corpus_mode, monkeypatch):
    stale = write_hero_dir(corpus_mode.tmp / "stale", str(uuid.uuid4()), str(HERO_CLINIC.id))
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(stale))
    with pytest.raises(loader.HeroNotFound, match="hero.json names records the loaded corpus lacks"):
        loader.load_scenario("hero")


def test_a_constructed_allergy_in_the_er_overlay_is_refused(corpus_mode):
    import json

    bundle_path = corpus_mode.hero_dir / "fhir" / "hero_er.json"
    bundle = json.loads(bundle_path.read_text())
    tag = {"system": loader.CONSTRUCTED_TAG_SYSTEM, "code": loader.CONSTRUCTED_TAG_CODE}
    bundle["entry"].append({"resource": {"resourceType": "AllergyIntolerance", "id": "x", "meta": {"tag": [tag]}}})
    bundle_path.write_text(json.dumps(bundle))
    with pytest.raises(loader.HeroNotFound):  # an unusable hero export is refused like a missing one
        loader.load_scenario("hero")


def test_the_hero_er_record_loses_any_natural_allergy_history(corpus_mode, monkeypatch):
    with_history = Draft(
        "ER_FHIR",
        "corpus-er-1",
        {"given": "Ana", "family": "Ruiz"},
        raw_payload={"patient": {"id": "er-1"}, "allergyIntolerances": [{"resourceType": "AllergyIntolerance"}]},
    )
    monkeypatch.setattr(loader, "_w1_corpus_drafts", lambda seed, raw_dir: [with_history, HERO_CLINIC, OTHER])
    er = next(c for c in loader.load_scenario("hero").sources if c.record.id == HERO_ER.id)
    assert er.record.raw_payload["allergyIntolerances"] == []
    assert er.record.is_constructed is True
