"""SessionResponse.sources is the scenario's showcase (the hero pair's cards), never the whole loaded
corpus; GET /sessions/current answers with the same response the reset gave, so a reload rebinds the
hero without a reset (G16 step 1). 404 before the first reset.

Corpus mode (evaluation doc §5): W5's constructed overlay is applied to the hero's own two records
named in hero.json; clinical content only, ids and identity exactly as selected; no overlay record is
inserted, so the hero exists once, as two records. Fixtures: see hero_corpus.py.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from backend.tests.api.conftest import API, engine
from backend.tests.api.hero_corpus import OVERLAY_PATIENT_IDS, W5_OVERLAY, write_hero_dir

CONSTRUCTED_TAG = {"system": "urn:chartguard:provenance", "code": "constructed-scenario"}


def _payload(conn, record_id: str) -> dict:
    return conn.execute(text("SELECT raw_payload FROM source_record WHERE id = :id"), {"id": record_id}).scalar_one()


def _reset(client) -> dict:
    r = client.post(f"{API}/sessions", json={"scenarioId": "hero"})
    assert r.status_code == 201, r.text
    return r.json()


def test_corpus_sources_are_the_hero_json_records_marked_constructed(client, hero_corpus, db_conn):
    body = _reset(client)
    assert [c["record"]["id"] for c in body["sources"]] == [hero_corpus.er_id, hero_corpus.clinic_id]
    assert all(c["record"]["isConstructed"] for c in body["sources"])
    stored = db_conn.execute(text("SELECT count(*) FROM source_record")).scalar_one()
    assert stored == hero_corpus.corpus_size, "no overlay record is inserted"
    overlay_rows = db_conn.execute(
        text("SELECT count(*) FROM source_record WHERE source_local_id = ANY(:ids)"), {"ids": list(OVERLAY_PATIENT_IDS)}
    ).scalar_one()
    assert overlay_rows == 0
    assert len(client.post(f"{API}/sessions", json={"scenarioId": "hero"}).content) < 20_000


def test_overlay_items_land_in_the_hero_payloads_with_ids_and_identity_kept(client, hero_corpus, db_conn):
    body = _reset(client)
    er = _payload(db_conn, hero_corpus.er_id)
    orders = er["medicationRequests"]
    constructed = [o for o in orders if CONSTRUCTED_TAG in (o.get("meta") or {}).get("tag", [])]
    assert [o["medicationCodeableConcept"]["coding"][0]["code"] for o in constructed] == ["308192"]
    assert er["allergyIntolerances"] == [], "the ER registration carries no allergy history"
    patient_ref = f"urn:uuid:{er['patient']['id']}"
    assert constructed[0]["subject"]["reference"] == patient_ref, "the order names the hero's own ER record"
    assert not any(pid in str(er) for pid in OVERLAY_PATIENT_IDS)
    clinic = _payload(db_conn, hero_corpus.clinic_id)
    rows = [a for a in clinic["allergies"] if a.get("CONSTRUCTED") == "true"]
    assert [(a["CODE"], a["SEVERITY1"]) for a in rows] == [("7984", "SEVERE")]
    assert (
        rows[0]["PATIENT"]
        == next(c for c in body["sources"] if c["record"]["id"] == hero_corpus.clinic_id)["record"]["sourceLocalId"]
    )
    names = {c["normalized"]["givenName"] for c in body["sources"]}
    assert names == {hero_corpus.hero_given}, "identity exactly as selected"


def test_the_hero_exists_once_and_approving_raises_bl_amox_01_tier_a(client, hero_corpus, db_conn):
    _reset(client)
    same_person = (
        db_conn.execute(
            text("SELECT record_id::text FROM normalized_record WHERE given_name = :g AND birth_date = :d"),
            {"g": hero_corpus.hero_given, "d": hero_corpus.hero_birth_date},
        )
        .scalars()
        .all()
    )
    assert sorted(same_person) == sorted([hero_corpus.er_id, hero_corpus.clinic_id]), (
        "no record with the hero's identity outside the two"
    )
    assert client.post(f"{API}/match-runs").status_code == 201
    pairs = client.get(f"{API}/candidate-pairs", params={"recordId": hero_corpus.er_id, "limit": 200}).json()["items"]
    hero_pairs = [p for p in pairs if {p["recordAId"], p["recordBId"]} == {hero_corpus.er_id, hero_corpus.clinic_id}]
    assert len(hero_pairs) == 1, "exactly one pair for the hero"
    approve = client.post(
        f"{API}/candidate-pairs/{hero_pairs[0]['id']}/reviews",
        json={"action": "APPROVE", "actor": "Registrar A"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert approve.status_code == 201, approve.text
    alerts = approve.json()["alerts"]
    assert [(a["ruleId"], a["tier"]) for a in alerts] == [("BL-AMOX-01", "A")]
    assert alerts[0]["revealedByMerge"] is True
    assert alerts[0]["constructedScenario"] is True


def test_without_overlay_files_the_hero_records_are_served_as_loaded(client, hero_corpus, monkeypatch):
    bare = write_hero_dir(hero_corpus.hero_dir.parent / "bare", hero_corpus.er_id, hero_corpus.clinic_id, overlay=False)
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(bare))
    cards = _reset(client)["sources"]
    assert [c["record"]["id"] for c in cards] == [hero_corpus.er_id, hero_corpus.clinic_id]
    assert not any(c["record"]["isConstructed"] for c in cards)


def test_frontdesk_hero_showcase_leaves_out_the_er_card(client, hero_corpus):
    cards = client.post(f"{API}/sessions", json={"scenarioId": "frontdesk-hero"}).json()["sources"]
    assert [c["record"]["id"] for c in cards] == [hero_corpus.clinic_id]


def test_current_session_equals_the_reset_response(client, monkeypatch):
    monkeypatch.delenv("CHECKMATE_HERO_SOURCE", raising=False)
    reset = _reset(client)
    assert len(reset["sources"]) == 2
    current = client.get(f"{API}/sessions/current")
    assert current.status_code == 200, current.text
    assert current.json() == reset


def test_current_session_in_corpus_mode_equals_the_reset_response(client, hero_corpus):
    reset = _reset(client)
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


def test_hero_pair_is_bound_by_record_id_in_corpus_mode(client, hero_corpus):
    """The UI's one request: GET /candidate-pairs?recordId=<first hero card>, then the pair whose other
    record is the second hero card. Found wherever the pair sits in the whole queue."""
    first, second = (c["record"]["id"] for c in _reset(client)["sources"])
    assert client.post(f"{API}/match-runs").status_code == 201
    items = client.get(f"{API}/candidate-pairs", params={"recordId": first}).json()["items"]
    assert len([p for p in items if {p["recordAId"], p["recordBId"]} == {first, second}]) == 1, items
    assert all(first in (p["recordAId"], p["recordBId"]) for p in items)


def test_corpus_reset_without_a_hero_fails_loudly_and_changes_nothing(
    client, hero_corpus, monkeypatch, db_conn, caplog
):
    """R3a: a reset that cannot find the hero is a 404 envelope naming the missing hero scenario (no file
    paths), one log line naming the directory it looked in, and no state change."""
    import logging

    _reset(client)  # a good session to compare against
    before = db_conn.execute(text("SELECT count(*) FROM source_record")).scalar_one()
    sessions = db_conn.execute(text("SELECT count(*) FROM demo_session")).scalar_one()
    empty = hero_corpus.hero_dir.parent / "no-hero"
    empty.mkdir()
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(empty))
    with caplog.at_level(logging.WARNING, logger="checkmate.scenarios"):
        r = client.post(f"{API}/sessions", json={"scenarioId": "hero"})
    assert r.status_code == 404, r.text
    error = r.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert "hero scenario" in error["message"]
    assert str(empty) not in r.text and "/" not in error["message"], "no file paths in the response"
    lines = [rec.getMessage() for rec in caplog.records if rec.name == "checkmate.scenarios"]
    assert len(lines) == 1 and str(empty) in lines[0]
    assert db_conn.execute(text("SELECT count(*) FROM source_record")).scalar_one() == before
    assert db_conn.execute(text("SELECT count(*) FROM demo_session")).scalar_one() == sessions


def test_sources_are_exactly_the_hero_json_pair_however_many_overlay_records(client, hero_corpus, db_conn):
    """R3a: an overlay holding many records (extra bundles, extra patient rows) still yields exactly the
    hero.json pair, and none of its records is inserted."""
    import shutil

    for n in range(3):
        shutil.copy(W5_OVERLAY / "fhir" / "hero_er.json", hero_corpus.hero_dir / "fhir" / f"extra_{n}.json")
    patients = hero_corpus.hero_dir / "csv" / "patients.csv"
    rows = patients.read_text().splitlines()
    patients.write_text(
        "\n".join([*rows, *[rows[1].replace(rows[1].split(",")[0], f"extra-{n}") for n in range(2)]]) + "\n"
    )
    body = _reset(client)
    assert [c["record"]["id"] for c in body["sources"]] == [hero_corpus.er_id, hero_corpus.clinic_id]
    assert db_conn.execute(text("SELECT count(*) FROM source_record")).scalar_one() == hero_corpus.corpus_size


def _refused_without_state_change(client, db_conn, caplog, hero_dir, problem: str):
    """The R3a guard: 404 envelope naming the missing hero scenario (no paths), one log line naming the
    directory and the problem, and no state change."""
    import logging

    before = db_conn.execute(text("SELECT count(*) FROM source_record")).scalar_one()
    sessions = db_conn.execute(text("SELECT count(*) FROM demo_session")).scalar_one()
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="checkmate.scenarios"):
        r = client.post(f"{API}/sessions", json={"scenarioId": "hero"})
    assert r.status_code == 404, r.text
    error = r.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert "hero scenario" in error["message"]
    assert str(hero_dir) not in r.text and "/" not in error["message"]
    lines = [rec.getMessage() for rec in caplog.records if rec.name == "checkmate.scenarios"]
    assert len(lines) == 1, lines
    assert str(hero_dir) in lines[0] and problem in lines[0], lines[0]
    assert db_conn.execute(text("SELECT count(*) FROM source_record")).scalar_one() == before
    assert db_conn.execute(text("SELECT count(*) FROM demo_session")).scalar_one() == sessions


MALFORMED_HERO_JSON = {
    "not JSON": ("{records: ", "not valid JSON"),
    "a list": ("[]", "no records object"),
    "records is a list": ('{"records": []}', "no records object"),
    "bad record id": (
        '{"records": {"ER_FHIR": {"record_id": "not-a-uuid"}, "CLINIC_CSV": {"record_id": "CLINIC"}}}',
        "not a uuid",
    ),
}


@pytest.mark.parametrize("case", sorted(MALFORMED_HERO_JSON))
def test_a_malformed_hero_json_is_refused_like_a_missing_hero(client, hero_corpus, db_conn, caplog, case):
    _reset(client)
    content, problem = MALFORMED_HERO_JSON[case]
    (hero_corpus.hero_dir / "hero.json").write_text(content.replace("CLINIC", hero_corpus.clinic_id))
    _refused_without_state_change(client, db_conn, caplog, hero_corpus.hero_dir, problem)


@pytest.mark.parametrize("only", ["ER_FHIR", "CLINIC_CSV"])
def test_a_hero_json_naming_one_record_is_refused(client, hero_corpus, db_conn, caplog, only):
    _reset(client)
    record_id = hero_corpus.er_id if only == "ER_FHIR" else hero_corpus.clinic_id
    (hero_corpus.hero_dir / "hero.json").write_text(json.dumps({"records": {only: {"record_id": record_id}}}))
    _refused_without_state_change(client, db_conn, caplog, hero_corpus.hero_dir, "both")


def test_a_malformed_overlay_bundle_is_refused_like_a_missing_hero(client, hero_corpus, db_conn, caplog):
    _reset(client)
    (hero_corpus.hero_dir / "fhir" / "hero_er.json").write_text("{not json")
    _refused_without_state_change(client, db_conn, caplog, hero_corpus.hero_dir, "not valid JSON")


def test_a_hero_export_rewritten_in_place_is_used_by_the_next_reset(client, hero_corpus):
    """The hero is re-exported into the same directory (the 20:00 selection) while the API runs: the next
    reset must use the new export, not a cached copy of the old one."""
    assert all(c["record"]["isConstructed"] for c in _reset(client)["sources"])
    for path in (hero_corpus.hero_dir / "fhir").glob("*.json"):
        path.unlink()
    (hero_corpus.hero_dir / "csv" / "allergies.csv").unlink()
    cards = _reset(client)["sources"]
    assert [c["record"]["id"] for c in cards] == [hero_corpus.er_id, hero_corpus.clinic_id]
    assert not any(c["record"]["isConstructed"] for c in cards), "the overlay removed in place is no longer applied"
