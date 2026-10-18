"""REPLAY end to end through the routes with no network and no key: the hero is denied and handed
to a registrar, the new patient is allowed, every response validates as ``IntakeTurn`` with
``agentMode == REPLAY``, and ``/health.agent == REPLAY``.

Network-off: httpx (the SDK's transport) is blocked, ``GEMINI_API_KEY`` is asserted unset, and the
SDK module is asserted never imported. Nothing here reads a real key.

Author: Christian Flores (Q1.4 builder).
"""

from __future__ import annotations

import sys
import uuid

import httpx
import pytest
from sqlalchemy import text

from backend.frontdesk import loop
from backend.frontdesk.replay import build_replay_model, load_transcript, transcript_path, transcript_sha256
from backend.tests.frontdesk.conftest import API, engine
from contracts.models.intake import AgentMode, IntakeTurn, RegistrationState, TurnRequest
from contracts.models.policy import PolicyOutcome, PolicyReason

TRANSCRIPT = load_transcript(transcript_path())
SCRIPTS = {(t.steps[0].model.args["preferredLanguage"], t.steps[0].expect.gate_outcome): t for t in TRANSCRIPT.turns}


def _blocked(*_a, **_k):
    raise AssertionError("network call attempted in REPLAY mode")


@pytest.fixture
def network_off(monkeypatch, real_model_factory):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # The real-network transports, not Client.send: the TestClient is an httpx client over an
    # in-process ASGI transport and must keep working.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _blocked)
    assert "GEMINI_API_KEY" not in __import__("os").environ
    sdk_loaded_before = "google.genai" in sys.modules  # other tests drive the LIVE adapter with a fake client
    yield
    assert ("google.genai" in sys.modules) == sdk_loaded_before, "REPLAY must never import the SDK"


def _start_session(client, intake_sessions, language: str) -> dict:
    r = client.post(
        f"{API}/intake-sessions", json={"language": language, "scenarioContextId": TRANSCRIPT.scenario_context_id}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    intake_sessions.append(body["id"])
    assert body["agentMode"] == AgentMode.REPLAY.value
    return body


def _turn(client, session_id: str, user_text: str) -> IntakeTurn:
    r = client.post(
        f"{API}/intake-sessions/{session_id}/turns",
        json={"text": user_text},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r.status_code == 201, r.text
    assert r.headers["X-Request-Id"]
    return IntakeTurn.model_validate(r.json())  # schema parity: a REPLAY turn is an IntakeTurn


def test_health_agent_is_replay_without_network_or_key(client, network_off):
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    assert r.json()["agent"] == "REPLAY"


@pytest.mark.parametrize("language", ["ES", "EN"])
def test_returning_patient_is_denied_and_handed_to_a_registrar(
    client, network_off, hero_records, intake_sessions, language
):
    script = SCRIPTS[(language, PolicyOutcome.DENY)]
    session = _start_session(client, intake_sessions, language)
    turn = _turn(client, session["id"], script.user_text)

    assert turn.agent_mode == AgentMode.REPLAY
    assert turn.degraded is None
    assert turn.assistant_text == script.steps[1].model.text
    assert turn.assistant_text_source == "MODEL"
    assert len(turn.tool_calls) == 1
    call = turn.tool_calls[0]
    assert call.tool_name == "propose_new_chart"
    assert call.gate.outcome == PolicyOutcome.DENY
    assert call.gate.reason_code == PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER
    assert call.gate.handoff_required is True
    # both hero records, as a demo reset loads them: the recorded ToolResult hash is computed over both
    assert set(hero_records.values()) <= {c.record_id for c in call.candidates}
    assert turn.registration.state == RegistrationState.PENDING_REGISTRAR
    assert turn.registration.handoff_pair_ids, "the handoff pair is what the registrar's board shows"

    with engine.connect() as conn:  # the handoff event is keyed by pair, the agent events by session
        rows = conn.execute(
            text(
                "SELECT event_type, gate_outcome, reason_code FROM event_log "
                "WHERE intake_session_id = :s OR pair_id = ANY(:p) ORDER BY ts"
            ),
            {"s": uuid.UUID(session["id"]), "p": list(turn.registration.handoff_pair_ids)},
        ).fetchall()
    kinds = [r[0] for r in rows]
    assert "INTAKE_STARTED" in kinds
    assert "AGENT_TOOL_CALLED" in kinds
    assert "INTAKE_HANDOFF_CREATED" in kinds
    assert "AGENT_TURN_DEGRADED" not in kinds
    assert ("AGENT_TOOL_CALLED", "DENY", "CANDIDATE_IN_REVIEW_OR_HIGHER") in [tuple(r) for r in rows]

    # reload shows the same turn, still REPLAY
    r = client.get(f"{API}/intake-sessions/{session['id']}")
    assert r.status_code == 200
    assert r.json()["agentMode"] == "REPLAY"
    assert r.json()["registration"]["state"] == "PENDING_REGISTRAR"


@pytest.mark.parametrize("language", ["ES", "EN"])
def test_new_patient_is_allowed_and_the_record_is_started(client, network_off, intake_sessions, language):
    script = SCRIPTS[(language, PolicyOutcome.ALLOW)]
    session = _start_session(client, intake_sessions, language)
    turn = _turn(client, session["id"], script.user_text)

    assert turn.agent_mode == AgentMode.REPLAY
    assert turn.degraded is None
    assert turn.assistant_text == script.steps[1].model.text
    call = turn.tool_calls[0]
    assert call.gate.outcome == PolicyOutcome.ALLOW
    assert call.gate.reason_code is None
    assert call.effect.status == "APPLIED"
    assert turn.registration.state == RegistrationState.NEW_CHART
    assert turn.registration.intake_record_id is not None


def test_off_script_text_degrades_to_the_template_with_no_effects(client, network_off, intake_sessions):
    session = _start_session(client, intake_sessions, "EN")
    turn = _turn(client, session["id"], "Hello, I would like to see a doctor please.")
    assert turn.agent_mode == AgentMode.REPLAY
    assert turn.degraded == "REPLAY_INPUT_MISMATCH"
    assert turn.assistant_text_source == "TEMPLATE"
    assert turn.tool_calls == []
    assert turn.registration.state == RegistrationState.NONE


def test_transcript_sha_is_stamped_on_the_tool_call_event(network_off, intake_sessions):
    """Through the loop directly: the route does not yet pass model.transcript_sha256 (flag for Q1.2)."""
    model = build_replay_model()
    assert model is not None and model.transcript_sha256 == transcript_sha256(transcript_path())
    script = SCRIPTS[("EN", PolicyOutcome.ALLOW)]
    sid = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO intake_session (id, language, agent_mode, prompt_version, tool_schema_version) "
                "VALUES (:id, 'EN', 'REPLAY', :pv, :tsv)"
            ),
            {"id": sid, "pv": TRANSCRIPT.prompt_version, "tsv": TRANSCRIPT.tool_schema_version},
        )
    intake_sessions.append(str(sid))
    status, response = loop.run_turn(
        engine,
        model,
        session_id=sid,
        key=str(uuid.uuid4()),
        body=TurnRequest(text=script.user_text),
        transcript_sha256=model.transcript_sha256,
    )
    assert status == 201
    assert IntakeTurn.model_validate(response).tool_calls  # the sha is stamped whatever the gate decides
    with engine.connect() as conn:
        versions = conn.execute(
            text("SELECT versions FROM event_log WHERE intake_session_id = :s AND event_type = 'AGENT_TOOL_CALLED'"),
            {"s": sid},
        ).scalar_one()
    assert versions["transcriptSha256"] == model.transcript_sha256


@pytest.mark.xfail(strict=False, reason="Flag for Q1.2: create_intake_turn does not pass model.transcript_sha256")
def test_route_stamps_transcript_sha_on_the_tool_call_event(client, network_off, intake_sessions):
    script = SCRIPTS[("EN", PolicyOutcome.ALLOW)]
    session = _start_session(client, intake_sessions, "EN")
    _turn(client, session["id"], script.user_text)
    with engine.connect() as conn:
        versions = conn.execute(
            text("SELECT versions FROM event_log WHERE intake_session_id = :s AND event_type = 'AGENT_TOOL_CALLED'"),
            {"s": uuid.UUID(session["id"])},
        ).scalar_one()
    assert versions["transcriptSha256"] == transcript_sha256(transcript_path())


# --- UI parity (ADR-016 section 7): a REPLAY turn and a LIVE turn are the same IntakeTurn shape and differ only
# in agentMode, latencyMs, ids and timestamps. The LIVE adapter is a fake that plays the transcript's first step.

_VOLATILE_KEYS = frozenset(
    {
        "id",
        "latencyMs",
        "turnIndex",
        "pairId",
        "intakeRecordId",
        "handoffPairIds",
        "evidenceIds",
        "recordId",
        "entityId",
        "createdAt",
        "decidedAt",
        "ts",
    }
)


def _shape(obj):
    """Drop volatile values and keep only the first candidate (session 1's intake record is itself a candidate
    for session 2 under the same demographics), so the two turns compare on structure and gate result."""
    if isinstance(obj, dict):
        return {k: _shape(v) for k, v in obj.items() if k not in _VOLATILE_KEYS and k != "agentMode"}
    if isinstance(obj, list):
        kept = [v for v in obj if not (isinstance(v, dict) and v.get("sourceSystem") == "FRONTDESK_INTAKE")]
        return [_shape(v) for v in kept[:1]]
    return obj


def test_replay_and_live_turns_differ_only_in_mode_latency_ids_and_timestamps(
    client, network_off, hero_clinic_record, intake_sessions, model_factory_override, monkeypatch
):
    from backend.app.main import app
    from backend.tests.frontdesk.conftest import FakeAgentModel, tool_call

    script = SCRIPTS[("EN", PolicyOutcome.DENY)]  # a DENY leaves no chart effect, so two sessions do not collide
    replay_session = _start_session(client, intake_sessions, "EN")
    replay_turn = _turn(client, replay_session["id"], script.user_text).model_dump(mode="json", by_alias=True)

    step = script.steps[0].model
    fake = FakeAgentModel(steps=[tool_call(step.tool_name, step.args)], final_text=script.steps[1].model.text)
    model_factory_override(lambda _mode, _settings: fake)
    import dataclasses

    live_settings = dataclasses.replace(app.state.settings, frontdesk_agent_mode="LIVE", gemini_model_id="fake-model")
    monkeypatch.setattr(app.state, "settings", live_settings)
    r = client.post(
        f"{API}/intake-sessions", json={"language": "EN", "scenarioContextId": TRANSCRIPT.scenario_context_id}
    )
    assert r.status_code == 201, r.text
    intake_sessions.append(r.json()["id"])
    assert r.json()["agentMode"] == AgentMode.LIVE.value
    live_turn = _turn(client, r.json()["id"], script.user_text).model_dump(mode="json", by_alias=True)

    assert replay_turn["agentMode"] == "REPLAY" and live_turn["agentMode"] == "LIVE"
    assert _shape(replay_turn) == _shape(live_turn)
