"""The review state machine, idempotency and the events it writes (architecture §5, §7)."""
from __future__ import annotations

import uuid

from sqlalchemy import text

from backend.api.reviews import Transition, transition
from backend.tests.api.conftest import API, approve_body, count_events, new_key, reject_body, review
from contracts.models.common import DecisionStatus, ReasonCode, ReviewAction
from contracts.models.reviews import ReviewResponse


def _versions(conn, pair_id: str) -> list[tuple[int, str]]:
    rows = conn.execute(text("SELECT version, status FROM match_decision WHERE pair_id = :p ORDER BY version"),
                        {"p": pair_id}).all()
    return [(r.version, r.status) for r in rows]


def _not_a_match_rows(conn, pair_id: str) -> int:
    return conn.execute(text(
        "SELECT count(*) FROM not_a_match n JOIN candidate_pair cp ON cp.record_a_id = n.record_a_id "
        "AND cp.record_b_id = n.record_b_id WHERE cp.id = :p"), {"p": pair_id}).scalar_one()


def test_approve_moves_proposed_to_linked_and_writes_link_approved(client, pair_id, db_conn):
    r = review(client, pair_id, approve_body("Registrar A"))
    assert r.status_code == 201, r.text
    body = ReviewResponse.model_validate(r.json())
    assert body.decision.status == DecisionStatus.LINKED
    assert body.decision.version == 2
    assert body.decision.actor == "registrar:Registrar A"
    assert body.decision.actor_type == "REGISTRAR"
    assert body.entity is not None
    assert _versions(db_conn, pair_id) == [(1, "PROPOSED"), (2, "LINKED")]
    assert count_events(db_conn, "LINK_APPROVED", pair_id=pair_id) == 1
    row = db_conn.execute(text("SELECT request_id, outcome, latency_ms, actor_type, payload FROM event_log "
                               "WHERE event_type = 'LINK_APPROVED' AND pair_id = :p"), {"p": pair_id}).one()
    assert row.request_id == r.headers["X-Request-Id"]
    assert row.outcome == "APPROVED"
    assert row.latency_ms is not None
    assert row.actor_type == "REGISTRAR"


def test_reject_moves_proposed_to_rejected_with_reason_and_note(client, pair_id, db_conn):
    r = review(client, pair_id, reject_body("INSUFFICIENT_EVIDENCE", note="needs the phone number"))
    assert r.status_code == 201, r.text
    body = ReviewResponse.model_validate(r.json())
    assert body.decision.status == DecisionStatus.REJECTED
    assert body.decision.reason_code == ReasonCode.INSUFFICIENT_EVIDENCE
    assert body.decision.note == "needs the phone number"
    assert body.entity is None
    assert count_events(db_conn, "LINK_REJECTED", pair_id=pair_id) == 1
    payload = db_conn.execute(text("SELECT payload::text FROM event_log WHERE event_type = 'LINK_REJECTED' "
                                   "AND pair_id = :p"), {"p": pair_id}).scalar_one()
    assert "needs the phone number" not in payload, "note text never reaches the event log"


def test_different_person_writes_not_a_match(client, pair_id, db_conn):
    review(client, pair_id, reject_body("DIFFERENT_PERSON"))
    assert _not_a_match_rows(db_conn, pair_id) == 1


def test_insufficient_evidence_does_not_write_not_a_match(client, pair_id, db_conn):
    review(client, pair_id, reject_body("INSUFFICIENT_EVIDENCE"))
    assert _not_a_match_rows(db_conn, pair_id) == 0


def test_reject_then_approve_supersedes(client, pair_id, db_conn):
    assert review(client, pair_id, reject_body("DIFFERENT_PERSON")).status_code == 201
    r = review(client, pair_id, approve_body())
    assert r.status_code == 201, r.text
    assert r.json()["decision"]["status"] == "LINKED"
    assert _versions(db_conn, pair_id) == [(1, "PROPOSED"), (2, "REJECTED"), (3, "LINKED")]
    assert _not_a_match_rows(db_conn, pair_id) == 0, "the superseded rejection's suppression is lifted"


def test_approve_on_linked_returns_200_with_no_new_version_and_no_event(client, pair_id, db_conn):
    first = review(client, pair_id, approve_body())
    events = count_events(db_conn, "LINK_APPROVED", pair_id=pair_id)
    r = review(client, pair_id, approve_body("Registrar B"))  # a different key, a different registrar
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["id"] == first.json()["decision"]["id"]
    assert _versions(db_conn, pair_id) == [(1, "PROPOSED"), (2, "LINKED")]
    assert count_events(db_conn, "LINK_APPROVED", pair_id=pair_id) == events


def test_reject_same_reason_on_rejected_is_200_same_decision(client, pair_id, db_conn):
    first = review(client, pair_id, reject_body("INSUFFICIENT_EVIDENCE"))
    r = review(client, pair_id, reject_body("INSUFFICIENT_EVIDENCE"))
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["id"] == first.json()["decision"]["id"]
    assert count_events(db_conn, "LINK_REJECTED", pair_id=pair_id) == 1


def test_reject_on_linked_is_409_decision_not_pending(client, pair_id, db_conn):
    review(client, pair_id, approve_body())
    r = review(client, pair_id, reject_body("DIFFERENT_PERSON"))
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "DECISION_NOT_PENDING"
    assert _versions(db_conn, pair_id) == [(1, "PROPOSED"), (2, "LINKED")]


def test_reject_other_reason_on_rejected_is_409(client, pair_id):
    review(client, pair_id, reject_body("INSUFFICIENT_EVIDENCE"))
    r = review(client, pair_id, reject_body("DIFFERENT_PERSON"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "DECISION_NOT_PENDING"


def test_missing_idempotency_key_is_422_validation_error(client, pair_id):
    r = client.post(f"{API}/candidate-pairs/{pair_id}/reviews", json=approve_body())
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_same_key_same_body_replays_the_stored_response(client, pair_id, db_conn):
    key = new_key()
    first = review(client, pair_id, approve_body(), key=key)
    second = review(client, pair_id, approve_body(), key=key)
    assert first.status_code == 201
    assert second.status_code == 201, "the replay carries the stored status, not the same-state 200"
    assert second.json() == first.json()
    assert count_events(db_conn, "LINK_APPROVED", pair_id=pair_id) == 1
    stored = db_conn.execute(text("SELECT count(*) FROM idempotency_record WHERE key = :k"), {"k": key}).scalar_one()
    assert stored == 1


def test_same_key_different_body_is_422_idempotency_mismatch(client, pair_id, db_conn):
    key = new_key()
    assert review(client, pair_id, approve_body(), key=key).status_code == 201
    r = review(client, pair_id, reject_body("DIFFERENT_PERSON"), key=key)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "IDEMPOTENCY_MISMATCH"
    assert _versions(db_conn, pair_id) == [(1, "PROPOSED"), (2, "LINKED")]


def test_reject_without_reason_is_422(client, pair_id):
    r = review(client, pair_id, {"action": "REJECT", "actor": "Registrar A"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_review_unknown_pair_is_404_and_claims_nothing(client, session, db_conn):
    key = new_key()
    r = review(client, str(uuid.uuid4()), approve_body(), key=key)
    assert r.status_code == 404
    assert db_conn.execute(text("SELECT count(*) FROM idempotency_record WHERE key = :k"), {"k": key}).scalar_one() == 0


def test_transition_table():
    A, R = ReviewAction.APPROVE, ReviewAction.REJECT
    DP, IE = ReasonCode.DIFFERENT_PERSON, ReasonCode.INSUFFICIENT_EVIDENCE
    assert transition(DecisionStatus.PROPOSED, None, A, None) == Transition.EFFECT
    assert transition(DecisionStatus.PROPOSED, None, R, DP) == Transition.EFFECT
    assert transition(DecisionStatus.LINKED, None, A, None) == Transition.SAME_STATE
    assert transition(DecisionStatus.LINKED, None, R, DP) == Transition.NOT_PENDING
    assert transition(DecisionStatus.REJECTED, DP, R, DP) == Transition.SAME_STATE
    assert transition(DecisionStatus.REJECTED, DP, R, IE) == Transition.NOT_PENDING
    assert transition(DecisionStatus.REJECTED, IE, A, None) == Transition.EFFECT
    assert transition(DecisionStatus.REVOKED, DP, A, None) == Transition.NOT_PENDING
    assert transition(DecisionStatus.REVOKED, DP, R, DP) == Transition.NOT_PENDING
