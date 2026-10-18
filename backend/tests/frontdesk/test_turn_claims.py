"""Turn idempotency and the lease (ADR-016 §5): in-flight duplicate, stale lease, session limit, parity."""

from __future__ import annotations

import threading
import uuid

from sqlalchemy import text

from backend.app.config import Settings
from backend.app.deps import get_settings
from backend.app.main import app
from backend.frontdesk.model import TextStep
from backend.tests.frontdesk.conftest import (
    API,
    FakeAgentModel,
    create_session,
    new_key,
    purge_session,
    tool_call,
    turn,
)
from backend.tests.policy.test_gate_db import UNRELATED_ARGS, UNRELATED_TEXT
from contracts.models.intake import AgentMode, IntakeTurn
from contracts.version import MAX_TURNS_PER_SESSION, TURN_LEASE_S


class HangingModel(FakeAgentModel):
    """Blocks inside next_step until released, so a second request with the same key sees IN_PROGRESS."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def next_step(self, req):
        self.entered.set()
        self.release.wait(timeout=10)
        return TextStep(text="Gracias.", latency_ms=1, mode=self.mode)


def test_same_key_while_in_progress_is_409(client, fake, cleanup):
    from backend.tests.frontdesk import conftest

    session = create_session(client)
    cleanup[0].append(session["id"])
    hanging = HangingModel()
    conftest.HOLDER.model = hanging
    key = new_key()
    results = {}

    def first():
        results["first"] = turn(client, session["id"], "Hola", key)

    t = threading.Thread(target=first)
    t.start()
    assert hanging.entered.wait(timeout=5)
    dup = turn(client, session["id"], "Hola", key)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "TURN_IN_PROGRESS"
    hanging.release.set()
    t.join(timeout=10)
    assert results["first"].status_code == 201
    assert turn(client, session["id"], "Hola", key).json() == results["first"].json()


def test_stale_lease_is_marked_failed_and_the_same_key_reclaims(client, fake, db_conn, cleanup):
    session = create_session(client)
    cleanup[0].append(session["id"])
    sid = uuid.UUID(session["id"])
    key = new_key()
    sha = "0" * 64
    db_conn.execute(
        text(
            "INSERT INTO intake_turn (session_id, turn_index, client_request_id, request_sha256, status, claimed_at, "
            "user_text) VALUES (:s, 0, :k, :sha, 'IN_PROGRESS', now() - make_interval(secs => :age), 'Hola')"
        ),
        {"s": sid, "k": key, "sha": sha, "age": TURN_LEASE_S + 5},
    )
    # Any claim on the session expires the stale lease first.
    other = turn(client, session["id"], "Otra cosa")
    assert other.status_code == 201 and other.json()["turnIndex"] == 1
    status = db_conn.execute(
        text("SELECT status FROM intake_turn WHERE session_id = :s AND turn_index = 0"), {"s": sid}
    ).scalar_one()
    assert status == "FAILED"
    # The same key with the same body re-claims the failed turn (its sha differs here, so the API answers 422;
    # re-insert with the real sha to show the reclaim path).
    db_conn.execute(
        text("UPDATE intake_turn SET request_sha256 = :sha WHERE session_id = :s AND turn_index = 0"),
        {"s": sid, "sha": _sha({"text": "Hola"})},
    )
    reclaimed = turn(client, session["id"], "Hola", key)
    assert reclaimed.status_code == 201 and reclaimed.json()["turnIndex"] == 0
    assert reclaimed.json()["assistantTextSource"] == "MODEL"


def _sha(body: dict) -> str:
    from backend.frontdesk.loop import request_sha256
    from contracts.models.intake import TurnRequest

    return request_sha256(TurnRequest.model_validate(body))


def test_session_closes_after_the_turn_limit(client, fake, cleanup):
    session = create_session(client)
    cleanup[0].append(session["id"])
    for i in range(MAX_TURNS_PER_SESSION):
        assert turn(client, session["id"], f"turno {i}").status_code == 201
    closed = turn(client, session["id"], "uno más")
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "SESSION_CLOSED"
    assert client.get(f"{API}/intake-sessions/{session['id']}").json()["closed"] is True


def _strip(body: dict) -> dict:
    """Drop the fields the parity test allows to differ: agentMode, latencyMs, ids and timestamps."""
    out = dict(body)
    out.pop("agentMode")
    out["toolCalls"] = [{k: v for k, v in c.items() if k not in {"id", "latencyMs"}} for c in out["toolCalls"]]
    for c in out["toolCalls"]:
        c["gate"] = {**c["gate"], "evidenceIds": len(c["gate"]["evidenceIds"])}
        c["candidates"] = [
            {k: v for k, v in cand.items() if k not in {"recordId", "pairId"}} for cand in c["candidates"]
        ]
        c["effect"] = {**c["effect"], "ref": c["effect"]["ref"] is not None}
    out["registration"] = {**out["registration"], "intakeRecordId": out["registration"]["intakeRecordId"] is not None}
    return out


def test_replay_and_live_turn_responses_share_one_shape(client, fake, db_conn, cleanup):
    """ADR-016 §7: a REPLAY turn and a LIVE turn validate as IntakeTurn and differ only in agentMode,
    latencyMs, ids and timestamps. The LIVE session is pinned through a settings override; the model is
    the same scripted fake in both, once labeled REPLAY and once LIVE."""
    from backend.tests.frontdesk import conftest

    replay_session = create_session(client, "EN")
    cleanup[0].append(replay_session["id"])
    live_settings = Settings(
        database_url="unused",
        cors_origins=(),
        frontdesk_agent_mode="LIVE",
        gemini_model_id="fixture-model",
        gemini_api_key_present=False,
        capture_dir=None,
        git_sha=None,
    )
    app.dependency_overrides[get_settings] = lambda: live_settings
    try:
        live_session = create_session(client, "EN")
    finally:
        app.dependency_overrides.pop(get_settings)
    cleanup[0].append(live_session["id"])
    assert (replay_session["agentMode"], live_session["agentMode"]) == ("REPLAY", "LIVE")

    bodies = {}
    for session, mode in ((replay_session, AgentMode.REPLAY), (live_session, AgentMode.LIVE)):
        conftest.HOLDER.model = FakeAgentModel(
            steps=[tool_call("propose_new_chart", UNRELATED_ARGS, mode)], mode=mode, final_text="Thank you."
        )
        r = turn(client, session["id"], UNRELATED_TEXT)
        assert r.status_code == 201, r.text
        bodies[mode] = IntakeTurn.model_validate(r.json()).model_dump(by_alias=True, mode="json")
        # The first intake record would be the second session's exact-match candidate: remove it between runs.
        purge_session(db_conn, session["id"])
    assert bodies[AgentMode.REPLAY]["agentMode"] == "REPLAY" and bodies[AgentMode.LIVE]["agentMode"] == "LIVE"
    assert _strip(bodies[AgentMode.REPLAY]) == _strip(bodies[AgentMode.LIVE])
