"""R3a reviewer tests for lane W3a (architecture §5 Idempotency, §7, §11, §16).

Written against the builder's branch without the builder's reasoning. Each test names the
checklist item it covers. Tests marked "expected to FAIL on lane/w3a" document a finding; the
rest cover gaps the builder's suite leaves (concurrency on one pair, claim rollback on an
unhandled exception, payload hygiene, a locked pair row).
"""
from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import text

from backend.events.writer import PayloadNotStructured, write_event
from backend.tests.api.conftest import API, approve_body, count_events, engine, new_key, reject_body, review
from contracts.models.common import ActorType, EventType

NOTE_MARKER = "R3A-NOTE-MARKER-must-never-be-logged"


def _versions(conn, pair_id: str) -> list[tuple[int, str]]:
    rows = conn.execute(text("SELECT version, status FROM match_decision WHERE pair_id = :p ORDER BY version"),
                        {"p": pair_id}).all()
    return [(r.version, r.status) for r in rows]


def _key_rows(conn, key: str) -> list[int]:
    return [r.status_code for r in
            conn.execute(text("SELECT status_code FROM idempotency_record WHERE key = :k"), {"k": key})]


def _not_a_match_rows(conn, pair_id: str) -> int:
    return conn.execute(text(
        "SELECT count(*) FROM not_a_match n JOIN candidate_pair cp ON cp.record_a_id = n.record_a_id "
        "AND cp.record_b_id = n.record_b_id WHERE cp.id = :p"), {"p": pair_id}).scalar_one()


# --- concurrency on one pair (checklist 9: decisions append-only; §5 explicit state behind the key) ---

def test_concurrent_approves_with_different_keys_produce_one_version_and_one_event(client, pair_id, db_conn):
    """Eight registrars click Approve at once (eight keys). Exactly one effect; the rest see the
    same-state 200 with the same decision id; one LINK_APPROVED event."""
    results: list = [None] * 8

    def go(i: int) -> None:
        results[i] = review(client, pair_id, approve_body(f"Registrar {i}"))

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200] * 7 + [201], statuses
    assert len({r.json()["decision"]["id"] for r in results}) == 1
    assert _versions(db_conn, pair_id) == [(1, "PROPOSED"), (2, "LINKED")]
    assert count_events(db_conn, "LINK_APPROVED", pair_id=pair_id) == 1


def test_concurrent_identical_requests_with_one_key_replay_one_effect(client, pair_id, db_conn):
    """The claim race: six identical requests with the same key. One effect, one stored row,
    every response carries the same decision."""
    key = new_key()
    results: list = [None] * 6

    def go(i: int) -> None:
        results[i] = review(client, pair_id, approve_body(), key=key)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [r.status_code for r in results] == [201] * 6
    assert len({r.json()["decision"]["id"] for r in results}) == 1
    assert _versions(db_conn, pair_id) == [(1, "PROPOSED"), (2, "LINKED")]
    assert count_events(db_conn, "LINK_APPROVED", pair_id=pair_id) == 1
    assert _key_rows(db_conn, key) == [201]


# --- claim rollback (§5: claim inserted in the same transaction as the effect) ---

def test_unhandled_exception_inside_the_review_transaction_rolls_back_the_claim(client, pair_id, db_conn, monkeypatch):
    """The link seam blows up after the decision row is written: 500 INTERNAL in the envelope,
    no decision, no event, no idempotency row, and the same key succeeds on retry."""
    def boom(conn, pair_id, decision_id):
        raise RuntimeError("seam failure injected by R3a")

    monkeypatch.setattr("backend.link.service.apply_approve", boom)
    key = new_key()
    r = review(client, pair_id, approve_body(), key=key)
    assert r.status_code == 500, r.text
    assert r.json() == {"error": {"code": "INTERNAL", "message": "internal error", "details": None}}
    assert r.headers["X-Request-Id"]
    assert _versions(db_conn, pair_id) == [(1, "PROPOSED")]
    assert count_events(db_conn, "LINK_APPROVED", pair_id=pair_id) == 0
    assert _key_rows(db_conn, key) == [], "a failed effect must not leave a claimed key behind"

    monkeypatch.undo()
    r = review(client, pair_id, approve_body(), key=key)
    assert r.status_code == 201, r.text
    assert _versions(db_conn, pair_id) == [(1, "PROPOSED"), (2, "LINKED")]


def test_review_while_the_pair_row_is_locked_is_a_clean_503_and_the_claim_is_released(client, pair_id, db_conn):
    """Another transaction holds the pair FOR UPDATE past statement_timeout: 503 UPSTREAM_UNAVAILABLE
    in the envelope, the claim is gone, and the same key works once the lock is released."""
    key = new_key()
    locker = engine.connect()
    tx = locker.begin()
    locker.execute(text("SELECT id FROM candidate_pair WHERE id = :p FOR UPDATE"), {"p": pair_id})
    try:
        r = review(client, pair_id, approve_body(), key=key)
        assert r.status_code == 503, r.text
        assert r.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
        assert r.headers["X-Request-Id"]
        assert _key_rows(db_conn, key) == []
    finally:
        tx.rollback()
        locker.close()
    r = review(client, pair_id, approve_body(), key=key)
    assert r.status_code == 201, r.text


# --- payload and log hygiene (checklist 16; §16 "note text is never logged") ---

def test_event_log_carries_no_note_text_no_record_fields_and_no_long_strings(client, pair_id, db_conn):
    actor = "Registrar R3A-ACTOR-MARKER"
    review(client, pair_id, reject_body("INSUFFICIENT_EVIDENCE", actor=actor, note=NOTE_MARKER))
    review(client, pair_id, approve_body(actor, note=NOTE_MARKER + " again"))
    rows = db_conn.execute(text("SELECT event_type, payload, versions, outcome FROM event_log")).all()
    assert rows
    for row in rows:
        blob = f"{row.payload}{row.versions}{row.outcome}"
        assert NOTE_MARKER not in blob, row.event_type
        for forbidden in ("given", "family", "birth", "phone", "address", "zip", "raw_payload", "api_key", "token"):
            assert forbidden not in blob.lower(), (row.event_type, forbidden)

        _assert_short_strings(row.payload, row.event_type)


def _assert_short_strings(value, event_type: str) -> None:
    if isinstance(value, str):
        assert len(value) <= 64, (event_type, value[:80])
    elif isinstance(value, dict):
        for v in value.values():
            _assert_short_strings(v, event_type)
    elif isinstance(value, list):
        for v in value:
            _assert_short_strings(v, event_type)


def test_event_writer_refuses_free_text_in_the_payload():
    with engine.begin() as conn, pytest.raises(PayloadNotStructured):
        write_event(conn, event_type=EventType.LINK_REJECTED, actor="registrar:R3a", actor_type=ActorType.REGISTRAR,
                    payload={"note": "x" * 65})


def test_nul_byte_in_note_is_rejected_at_the_boundary_not_a_500(client, pair_id):
    """Expected to FAIL on lane/w3a (finding: 500 INTERNAL). JSON allows \\u0000; Postgres text does
    not. Checklist 13 says validate at the boundary: a 422 VALIDATION_ERROR, never a DB error."""
    r = review(client, pair_id, reject_body("INSUFFICIENT_EVIDENCE", note="hello\x00world"))
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_a_failing_review_never_writes_the_note_or_actor_to_the_log(client, pair_id, caplog):
    """Expected to FAIL on lane/w3a (finding: the unhandled-exception path logs the SQL statement with
    its bound parameters, so the note and actor land in the process log; §16, checklist 16)."""
    import logging

    caplog.set_level(logging.DEBUG)
    review(client, pair_id, reject_body("INSUFFICIENT_EVIDENCE", actor="Registrar R3A-ACTOR-MARKER",
                                        note=NOTE_MARKER + "\x00"))
    assert NOTE_MARKER not in caplog.text, "note text reached the log"
    assert "R3A-ACTOR-MARKER" not in caplog.text, "actor text reached the log"


# --- §7: DIFFERENT_PERSON suppression vs a later approve ---

def test_approve_after_different_person_reject_is_refused_and_keeps_not_a_match(client, pair_id, db_conn):
    """Expected to FAIL on lane/w3a (finding). §7: INSUFFICIENT_EVIDENCE rejects do not block a later
    approve; DIFFERENT_PERSON writes not_a_match and APPROVE checks against not_a_match
    (CANNOT_LINK_CONFLICT). The branch deletes the not_a_match row and links (201)."""
    assert review(client, pair_id, reject_body("DIFFERENT_PERSON")).status_code == 201
    r = review(client, pair_id, approve_body())
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] in ("CANNOT_LINK_CONFLICT", "DECISION_NOT_PENDING")
    assert _not_a_match_rows(db_conn, pair_id) == 1, "a steward's different-person decision was erased"
    assert _versions(db_conn, pair_id) == [(1, "PROPOSED"), (2, "REJECTED")]


def test_approve_after_insufficient_evidence_reject_supersedes(client, pair_id, db_conn):
    """§7: the INSUFFICIENT_EVIDENCE path does supersede."""
    assert review(client, pair_id, reject_body("INSUFFICIENT_EVIDENCE")).status_code == 201
    r = review(client, pair_id, approve_body())
    assert r.status_code == 201, r.text
    assert _versions(db_conn, pair_id) == [(1, "PROPOSED"), (2, "REJECTED"), (3, "LINKED")]
    assert _not_a_match_rows(db_conn, pair_id) == 0


# --- request id hygiene (checklist 13: never trust the client; §16 structured logs) ---

def test_client_supplied_request_id_is_bounded(client):
    """Expected to FAIL on lane/w3a (nit-level finding). A 5 KB or log-shaped X-Request-Id is echoed
    verbatim into the response, the log line and event_log.request_id. The server should mint its own
    when the client's is not a short opaque token."""
    r = client.get(f"{API}/health", headers={"X-Request-Id": "R" * 5000})
    assert len(r.headers["X-Request-Id"]) <= 128
    r = client.get(f"{API}/health", headers={"X-Request-Id": "abc status=500 path=/pwned request_id=fake"})
    assert " " not in r.headers["X-Request-Id"]


# --- §5 bounded lists: a forged cursor never widens the page ---

def test_forged_cursor_values_never_error_or_widen_the_page(client, match_run):
    import base64
    import json

    def cur(d, i="00000000-0000-4000-8000-000000000000") -> str:
        return base64.urlsafe_b64encode(json.dumps({"d": d, "id": i}).encode()).decode().rstrip("=")

    for d in ("nan", "inf", -1, 1e308, True):
        r = client.get(f"{API}/candidate-pairs", params={"cursor": cur(d), "limit": 1})
        assert r.status_code in (200, 422), (d, r.text)
        if r.status_code == 200:
            assert len(r.json()["items"]) <= 1
    assert uuid.UUID(match_run["queuedPairIds"][0])
