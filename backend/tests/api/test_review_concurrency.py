"""Codex finding 8: concurrent duplicates, conflicting reviews and rollback after a link failure.
Exactly one effect per pair; nothing half-written. Two threads each drive their own TestClient."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.api import reviews
from backend.app.main import app
from backend.tests.api.conftest import API, approve_body, count_events, new_key, reject_body


def _post(pair_id: str, body: dict, key: str):
    with TestClient(app) as c:
        return c.post(f"{API}/candidate-pairs/{pair_id}/reviews", json=body, headers={"Idempotency-Key": key})


def _versions(conn, pair_id: str) -> list[str]:
    return [
        r.status
        for r in conn.execute(
            text("SELECT status FROM match_decision WHERE pair_id = :p ORDER BY version"), {"p": pair_id}
        )
    ]


def test_concurrent_same_key_same_body_gives_one_effect_and_identical_bodies(pair_id, db_conn):
    key = new_key()
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda _: _post(pair_id, approve_body(), key), range(2)))
    assert {a.status_code, b.status_code} == {201}
    assert a.json() == b.json()
    assert _versions(db_conn, pair_id) == ["PROPOSED", "LINKED"]
    assert count_events(db_conn, "LINK_APPROVED", pair_id=pair_id) == 1
    assert db_conn.execute(text("SELECT count(*) FROM idempotency_record WHERE key = :k"), {"k": key}).scalar_one() == 1


def test_concurrent_conflicting_reviews_with_different_keys_yield_one_winner(pair_id, db_conn):
    bodies = [approve_body("Registrar A"), reject_body("DIFFERENT_PERSON", actor="Registrar B")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda body: _post(pair_id, body, new_key()), bodies))
    codes = sorted(r.status_code for r in results)
    versions = _versions(db_conn, pair_id)
    effects = count_events(db_conn, "LINK_APPROVED", pair_id=pair_id) + count_events(
        db_conn, "LINK_REJECTED", pair_id=pair_id
    )
    if codes == [201, 409]:  # approve won the lock; the reject found LINKED
        assert versions == ["PROPOSED", "LINKED"]
    else:  # reject won the lock; the approve superseded it (history keeps both)
        assert codes == [201, 201], codes
        assert versions == ["PROPOSED", "REJECTED", "LINKED"]
    assert effects == len(versions) - 1, "one event per effect, none for the loser"


def test_link_failure_rolls_back_decision_event_and_claim(client, pair_id, db_conn, monkeypatch):
    def broken(conn, pair_id, decision_id):
        raise RuntimeError("link seam failed")

    monkeypatch.setattr(reviews.link, "apply_approve", broken)
    key = new_key()
    r = client.post(f"{API}/candidate-pairs/{pair_id}/reviews", json=approve_body(), headers={"Idempotency-Key": key})
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL"
    assert _versions(db_conn, pair_id) == ["PROPOSED"]
    assert count_events(db_conn, "LINK_APPROVED", pair_id=pair_id) == 0
    assert db_conn.execute(text("SELECT count(*) FROM idempotency_record WHERE key = :k"), {"k": key}).scalar_one() == 0
    monkeypatch.undo()
    assert (
        client.post(
            f"{API}/candidate-pairs/{pair_id}/reviews", json=approve_body(), headers={"Idempotency-Key": key}
        ).status_code
        == 201
    ), "the same key works once the seam is healthy"
