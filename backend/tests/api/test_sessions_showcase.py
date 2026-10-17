"""SessionResponse.sources is the scenario's showcase (the hero pair's cards), never the whole loaded
corpus; GET /sessions/current answers with the same response the reset gave, so a reload rebinds the
hero without a reset (G16 step 1). 404 before the first reset.

Corpus mode runs on W1's real loaders over its committed fixtures, laid out like W5's hero export: a
raw sample (fhir/ + csv/) and an overlay holding one ER registration and one Clinic patient row.
"""

from __future__ import annotations

import json
import shutil

import pytest
from sqlalchemy import text

from backend.scenarios import loader
from backend.tests.api.conftest import API, engine

W1_FIXTURES = loader.REPO_ROOT / "backend" / "tests" / "ingest" / "fixtures"
OVERLAY_PATIENT = "aaaaaaaa-0000-4000-8000-000000000001"  # bundle_a's person, as W5's overlay copies the hero


def _raw_sample(root):
    raw = root / "raw"
    (raw / "fhir").mkdir(parents=True)
    shutil.copytree(W1_FIXTURES / "csv", raw / "csv")
    for name in ("bundle_a.json", "bundle_b.json"):
        shutil.copy(W1_FIXTURES / name, raw / "fhir" / name)
    return raw


def _overlay(root):
    overlay = root / "overlay"
    (overlay / "fhir").mkdir(parents=True)
    (overlay / "csv").mkdir()
    shutil.copy(W1_FIXTURES / "bundle_a.json", overlay / "fhir" / "hero_er.json")
    rows = (W1_FIXTURES / "csv" / "patients.csv").read_text().splitlines()
    (overlay / "csv" / "patients.csv").write_text(
        "\n".join([rows[0], *[r for r in rows if r.startswith(OVERLAY_PATIENT)]]) + "\n"
    )
    return overlay


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    pytest.importorskip("backend.ingest.cli")
    raw = _raw_sample(tmp_path)
    monkeypatch.setenv("CHECKMATE_HERO_SOURCE", "corpus")
    monkeypatch.setenv("CHECKMATE_RAW_DIR", str(raw))
    loader._corpus_cards.cache_clear()
    yield tmp_path
    loader._corpus_cards.cache_clear()


def _stored_record_count(conn) -> int:
    return conn.execute(text("SELECT count(*) FROM source_record")).scalar_one()


def test_corpus_reset_returns_only_the_hero_overlay_cards(client, corpus, monkeypatch, db_conn):
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(_overlay(corpus)))
    r = client.post(f"{API}/sessions", json={"scenarioId": "hero"})
    assert r.status_code == 201, r.text
    cards = r.json()["sources"]
    assert sorted(c["record"]["sourceSystem"] for c in cards) == ["CLINIC_CSV", "ER_FHIR"]
    assert all(c["record"]["isConstructed"] for c in cards), "the showcase is the constructed scenario"
    assert all(c["record"]["sourceLocalId"] == OVERLAY_PATIENT for c in cards)
    assert _stored_record_count(db_conn) > len(cards), "the whole corpus is loaded for matching"
    run = client.post(f"{API}/match-runs").json()
    assert run["records"] == _stored_record_count(db_conn), "candidate pairs come from the whole corpus"
    assert len(r.content) < 20_000, "the reset response no longer carries the corpus"


def test_without_an_overlay_the_hero_json_records_are_the_showcase(client, corpus, monkeypatch):
    drafts = loader._w1_corpus_drafts(20261017, corpus / "raw")
    er = next(d for d in drafts if d.source_system == "ER_FHIR")
    clinic = next(d for d in drafts if d.source_system == "CLINIC_CSV")
    hero_dir = corpus / "hero-only"
    hero_dir.mkdir()
    (hero_dir / "hero.json").write_text(
        json.dumps({"records": {"ER_FHIR": {"record_id": str(er.id)}, "CLINIC_CSV": {"record_id": str(clinic.id)}}})
    )
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(hero_dir))
    cards = client.post(f"{API}/sessions", json={"scenarioId": "hero"}).json()["sources"]
    assert [c["record"]["id"] for c in cards] == [str(er.id), str(clinic.id)]


def test_frontdesk_hero_showcase_leaves_out_the_er_card(client, corpus, monkeypatch):
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(_overlay(corpus)))
    cards = client.post(f"{API}/sessions", json={"scenarioId": "frontdesk-hero"}).json()["sources"]
    assert [c["record"]["sourceSystem"] for c in cards] == ["CLINIC_CSV"]


def test_current_session_equals_the_reset_response(client, monkeypatch):
    monkeypatch.delenv("CHECKMATE_HERO_SOURCE", raising=False)
    reset = client.post(f"{API}/sessions", json={"scenarioId": "hero"})
    assert reset.status_code == 201, reset.text
    assert len(reset.json()["sources"]) == 2
    current = client.get(f"{API}/sessions/current")
    assert current.status_code == 200, current.text
    assert current.json() == reset.json()


def test_current_session_in_corpus_mode_equals_the_reset_response(client, corpus, monkeypatch):
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(_overlay(corpus)))
    reset = client.post(f"{API}/sessions", json={"scenarioId": "hero"}).json()
    assert client.get(f"{API}/sessions/current").json() == reset


def test_current_session_is_404_before_the_first_reset(client):
    with engine.begin() as conn:  # this lane's own test database only (conftest refuses any other)
        conn.execute(text("DELETE FROM demo_session"))
    r = client.get(f"{API}/sessions/current")
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert r.headers["X-Request-Id"]
    assert client.post(f"{API}/sessions", json={"scenarioId": "hero"}).status_code == 201
    assert client.get(f"{API}/sessions/current").status_code == 200
