"""The scenario loader's two sources, through the real POST /sessions route.

Fixture mode is the default and needs nothing from W1. Corpus mode is tested at the W1 boundary
(``_w1_corpus_drafts``, ``_w1_overlay_drafts``, ``_w1_normalize``): W1's own tests cover its
loaders, and the raw Synthea sample is not in the repo. What this file proves is the glue: the
mode switch, the overlay directory, and that constructed overlay records keep isConstructed=true
all the way into ``source_record``.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend.scenarios import loader
from backend.tests.api.conftest import API

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


@pytest.fixture
def corpus_mode(monkeypatch, tmp_path):
    overlay_seen: list = []
    corpus = [
        Draft("ER_FHIR", "corpus-er-1", {"given": "Ana", "family": "Ruiz"}),
        Draft("CLINIC_CSV", "corpus-clinic-1", {"given": "Ana", "family": "Ruiz"}),
    ]
    overlay = [Draft("ER_FHIR", "overlay-er-hero", {"given": "Hero", "family": "Case"}, is_constructed=True)]

    def overlay_drafts(overlay_dir):
        overlay_seen.append(overlay_dir)
        return overlay

    monkeypatch.setenv("CHECKMATE_HERO_SOURCE", "corpus")
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(tmp_path))
    monkeypatch.setattr(loader, "_w1_corpus_drafts", lambda seed, raw_dir: corpus)
    monkeypatch.setattr(loader, "_w1_overlay_drafts", overlay_drafts)
    monkeypatch.setattr(loader, "_w1_normalize", _normalize)
    loader._corpus_cards.cache_clear()
    yield SimpleNamespace(corpus=corpus, overlay=overlay, overlay_seen=overlay_seen, overlay_dir=tmp_path)
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


def test_corpus_mode_loads_corpus_plus_overlay_and_keeps_is_constructed(client, corpus_mode, db_conn):
    r = client.post(f"{API}/sessions", json={"scenarioId": "hero"})
    assert r.status_code == 201, r.text
    assert corpus_mode.overlay_seen == [corpus_mode.overlay_dir], "the overlay dir comes from the env var"
    by_local_id = {s["record"]["sourceLocalId"]: s for s in r.json()["sources"]}
    assert set(by_local_id) == {"corpus-er-1", "corpus-clinic-1", "overlay-er-hero"}
    assert by_local_id["overlay-er-hero"]["record"]["isConstructed"] is True
    assert by_local_id["corpus-er-1"]["record"]["isConstructed"] is False
    assert by_local_id["corpus-clinic-1"]["displayLabel"] == "Clinic CSV"
    stored = dict(db_conn.execute(text("SELECT source_local_id, is_constructed FROM source_record")).all())
    assert stored == {"corpus-er-1": False, "corpus-clinic-1": False, "overlay-er-hero": True}


def test_corpus_mode_frontdesk_hero_leaves_out_the_er_records(client, corpus_mode):
    r = client.post(f"{API}/sessions", json={"scenarioId": "frontdesk-hero"})
    assert r.status_code == 201, r.text
    assert [s["record"]["sourceLocalId"] for s in r.json()["sources"]] == ["corpus-clinic-1"]


def test_corpus_mode_overlay_dir_defaults_to_data_scenarios_hero(corpus_mode, monkeypatch):
    monkeypatch.delenv("CHECKMATE_HERO_OVERLAY_DIR")
    loader.load_scenario("hero")
    assert corpus_mode.overlay_seen == [loader.HERO_OVERLAY_DIR]
    assert loader.HERO_OVERLAY_DIR.parts[-3:] == ("data", "scenarios", "hero")


def test_corpus_mode_honors_a_changed_overlay_dir(corpus_mode, monkeypatch, tmp_path_factory):
    """The corpus is cached per (seed, raw dir, overlay dir): pointing the env var elsewhere reloads."""
    loader.load_scenario("hero")
    other = tmp_path_factory.mktemp("overlay-b")
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(other))
    loader.load_scenario("hero")
    assert corpus_mode.overlay_seen == [corpus_mode.overlay_dir, other]


def test_corpus_mode_refuses_an_overlay_record_that_collides_with_the_corpus(corpus_mode, monkeypatch):
    """ON CONFLICT DO NOTHING would keep the corpus row and silently drop the overlay's is_constructed."""
    clash = Draft("ER_FHIR", "corpus-er-1", {"given": "Hero", "family": "Case"}, is_constructed=True)
    monkeypatch.setattr(loader, "_w1_overlay_drafts", lambda overlay_dir: [clash])
    with pytest.raises(ValueError, match="corpus-er-1"):
        loader.load_scenario("hero")


W1_FIXTURES = loader.REPO_ROOT / "backend" / "tests" / "ingest" / "fixtures"


@pytest.fixture
def w1_raw_and_overlay(tmp_path, monkeypatch):
    """W1's committed fixtures laid out as a raw sample (fhir/ + csv/) and a one-bundle overlay."""
    import shutil

    pytest.importorskip("backend.ingest.cli")
    raw, overlay = tmp_path / "raw", tmp_path / "overlay"
    (raw / "fhir").mkdir(parents=True)
    (overlay / "fhir").mkdir(parents=True)
    shutil.copytree(W1_FIXTURES / "csv", raw / "csv")
    for name in ("bundle_a.json", "bundle_b.json"):
        shutil.copy(W1_FIXTURES / name, raw / "fhir" / name)
    shutil.copy(W1_FIXTURES / "bundle_a.json", overlay / "fhir" / "hero.json")
    monkeypatch.setenv("CHECKMATE_HERO_SOURCE", "corpus")
    monkeypatch.setenv("CHECKMATE_RAW_DIR", str(raw))
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(overlay))
    loader._corpus_cards.cache_clear()
    yield
    loader._corpus_cards.cache_clear()


def test_corpus_mode_end_to_end_on_real_w1(client, w1_raw_and_overlay, db_conn):
    """Real W1 loaders, corruptor and normalizer; only the input files are small."""
    first = client.post(f"{API}/sessions", json={"scenarioId": "hero"})
    assert first.status_code == 201, first.text
    cards = first.json()["sources"]
    constructed = [c for c in cards if c["record"]["isConstructed"]]
    assert len(constructed) == 1, "exactly the one overlay bundle is constructed"
    assert constructed[0]["record"]["sourceSystem"] == "ER_FHIR"
    assert len(cards) > 1, "the corpus records load beside the overlay"
    stored = dict(db_conn.execute(text("SELECT id::text, is_constructed FROM source_record")).all())
    assert stored == {c["record"]["id"]: c["record"]["isConstructed"] for c in cards}
    assert {c["displayLabel"] for c in cards} <= {"ER FHIR", "Clinic CSV"}
    loader._corpus_cards.cache_clear()
    second = client.post(f"{API}/sessions", json={"scenarioId": "hero"}).json()
    assert sorted(c["record"]["id"] for c in second["sources"]) == sorted(c["record"]["id"] for c in cards), (
        "loading twice gives the same records"
    )
    assert client.post(f"{API}/match-runs").status_code == 201
