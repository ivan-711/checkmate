"""INTAKE_HANDOFF_CREATED rows carry intake_session_id and gate_outcome, and ``GET /events`` returns
``intakeSessionId`` on them. Commits through the app's own engine (the route reads with its pool),
so the test cleans up after itself on the q1_1 test database."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.tests.conftest import TEST_DATABASE_URL

if "test" not in TEST_DATABASE_URL.rsplit("/", 1)[-1]:
    raise SystemExit("refusing to run route tests against a non-test database")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("FRONTDESK_AGENT_MODE", "REPLAY")

from backend.app.main import app, engine
from backend.chart_store import writes
from backend.policy.decide import handoff_token
from backend.policy.gate import evaluate
from backend.tests.conftest import purge
from backend.tests.policy.seed import insert_session, near_duplicates
from backend.tests.policy.test_gate_db import FACTS, PROPOSE_ARGS, USER_TEXT
from contracts.models.common import EventType


@pytest.fixture
def handoff():
    """Commit a near-duplicate pair, a session and its handoff; yield (session id, pair ids, since)."""
    since = datetime.now(UTC)
    with engine.begin() as conn:
        er, clinic = near_duplicates(conn)
        sid = insert_session(conn)
        ev = evaluate(
            conn,
            session_id=sid,
            tool_name="propose_new_chart",
            raw_args=PROPOSE_ARGS,
            user_texts=(USER_TEXT,),
            session=FACTS,
        )
        token = handoff_token(ev.decision)
        rid = writes.create_intake_record(
            conn,
            token,
            session_id=sid,
            args=ev.action.args,
            args_sha256=ev.action.args_sha256,
            scenario_context_id=None,
        )
        pair_ids = writes.create_handoff_pairs(
            conn,
            token,
            session_id=sid,
            intake_record_id=rid,
            candidates=ev.candidates,
            evidence_snapshot=ev.evidence_snapshot,
            thresholds_id=ev.thresholds_id,
            scorer_version=ev.scorer_version,
        )
    try:
        yield sid, pair_ids, since
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM event_log WHERE intake_session_id = :sid"), {"sid": sid})
            conn.execute(text("UPDATE intake_session SET intake_record_id = NULL WHERE id = :sid"), {"sid": sid})
        purge(engine, [rid, er, clinic])  # pairs, decisions and records
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM intake_session WHERE id = :sid"), {"sid": sid})


def test_handoff_events_carry_the_session_and_gate_outcome(handoff):
    sid, pair_ids, since = handoff
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT intake_session_id, gate_outcome, pair_id FROM event_log "
                "WHERE event_type = :t AND pair_id = ANY(:ids)"
            ),
            {"t": EventType.INTAKE_HANDOFF_CREATED.value, "ids": pair_ids},
        ).all()
    assert len(rows) == len(pair_ids)
    assert all(r.intake_session_id == sid and r.gate_outcome == "DENY" for r in rows)

    with TestClient(app) as client:
        response = client.get("/api/v1/events", params={"since": since.isoformat(), "limit": 200})
    assert response.status_code == 200, response.text
    items = [e for e in response.json()["items"] if e["eventType"] == EventType.INTAKE_HANDOFF_CREATED.value]
    ours = [e for e in items if e["pairId"] in {str(p) for p in pair_ids}]
    assert len(ours) == len(pair_ids)
    assert all(e["intakeSessionId"] == str(sid) and e["gateOutcome"] == "DENY" for e in ours)
