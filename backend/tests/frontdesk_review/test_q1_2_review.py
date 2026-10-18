"""Q1.2 paired-reviewer tests: the three intake routes, the loop and the executor driven by the
reviewer's own scripted adapter (not the builder's fakes). Author: Christian Flores (Q1.2 paired reviewer).

Every test commits through the app's pool and cleans up its own session, records and events.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema
import pytest
from sqlalchemy import text

from backend.frontdesk.model import ErrorStep, ModelRequest, ModelStep, TextStep, ToolCallStep
from backend.tests.conftest import purge
from backend.tests.policy.seed import (
    UNRELATED_DEMOGRAPHICS,
    insert_record,
    near_duplicates,
)
from contracts.models.common import SourceKind
from contracts.models.intake import AgentMode

ROOT = Path(__file__).resolve().parents[3]
TOOL_RESULT_SCHEMA = json.loads((ROOT / "contracts" / "tools" / "tool_result.schema.json").read_text())

HERO_TEXT = (
    "Soy María José González Rivera, nací el 3 de julio de 1985, mujer, mi teléfono es 555 010 0100, "
    "vivo en 100 Main St, código postal 54311"
)
HERO_ARGS = {
    "givenName": "Maria Jose",
    "familyName": "Gonzalez Rivera",
    "birthDate": "1985-07-03",
    "sex": "FEMALE",
    "phone": "5550100100",
    "addressLine": "100 Main St",
    "postalCode": "54311",
    "preferredLanguage": "ES",
    "evidence": {
        "givenName": "María José",
        "familyName": "González Rivera",
        "birthDate": "3 de julio de 1985",
        "sex": "mujer",
        "phone": "555 010 0100",
        "addressLine": "100 Main St",
        "postalCode": "54311",
    },
}
NEW_TEXT = "I am Priscilla Oyelaran-Whitcombe, born 1992-11-28, female, phone 555 123 4567"
NEW_ARGS = {
    "givenName": "Priscilla",
    "familyName": "Oyelaran-Whitcombe",
    "birthDate": "1992-11-28",
    "sex": "FEMALE",
    "phone": "5551234567",
    "preferredLanguage": "EN",
    "evidence": {
        "givenName": "Priscilla",
        "familyName": "Oyelaran-Whitcombe",
        "birthDate": "1992-11-28",
        "sex": "female",
        "phone": "555 123 4567",
    },
}


def call(tool: str, args: dict, mode=AgentMode.REPLAY) -> ToolCallStep:
    return ToolCallStep(tool_name=tool, args=args, model_call_id=None, latency_ms=1, mode=mode)


def say(text_: str, mode=AgentMode.REPLAY) -> TextStep:
    return TextStep(text=text_, latency_ms=1, mode=mode)


def err(kind: str, retryable: bool, mode=AgentMode.REPLAY) -> ErrorStep:
    return ErrorStep(kind=kind, retryable=retryable, mode=mode)


@dataclass
class ScriptedModel:
    """The reviewer's adapter: pops steps in order; asserts no pooled connection is checked out
    while it runs (ADR-016 §8 pool starvation)."""

    steps: list[ModelStep]
    engine: object
    mode: AgentMode = AgentMode.REPLAY
    calls: int = 0
    requests: list[ModelRequest] = field(default_factory=list)
    raise_exc: Exception | None = None

    def next_step(self, req: ModelRequest) -> ModelStep:
        self.calls += 1
        self.requests.append(req)
        assert self.engine.pool.checkedout() == 0, "a DB connection is held across the model call"
        if self.raise_exc is not None:
            raise self.raise_exc
        if not self.steps:
            return say("Gracias.", self.mode)
        return self.steps.pop(0)


@pytest.fixture
def api(engine, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api import intake
    from backend.app import main

    monkeypatch.setattr(main.app.state, "engine", engine)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    holder: dict = {"model": None}

    def factory(mode, settings):
        model = holder["model"]
        assert model is not None, "test did not script a model"
        return model

    main.app.dependency_overrides[intake.get_model_factory] = lambda: factory
    client = TestClient(main.app, raise_server_exceptions=False)
    sessions: list[str] = []
    records: list[uuid.UUID] = []

    def use(model):
        holder["model"] = model

    def start(language="ES", **extra):
        r = client.post("/api/v1/intake-sessions", json={"language": language, **extra})
        assert r.status_code == 201, r.text
        sessions.append(r.json()["id"])
        return r.json()

    def turn(sid, text_, key=None):
        key = key or str(uuid.uuid4())
        return client.post(
            f"/api/v1/intake-sessions/{sid}/turns", json={"text": text_}, headers={"Idempotency-Key": key}
        )

    yield client, use, start, turn, records
    main.app.dependency_overrides.pop(intake.get_model_factory, None)
    with engine.begin() as c:
        for sid in sessions:
            intake_ids = [
                r[0]
                for r in c.execute(
                    text("SELECT intake_record_id FROM intake_session WHERE id = :s AND intake_record_id IS NOT NULL"),
                    {"s": sid},
                )
            ]
            records.extend(intake_ids)
            c.execute(text("DELETE FROM event_log WHERE intake_session_id = :s"), {"s": sid})
            c.execute(text("UPDATE intake_session SET intake_record_id = NULL WHERE id = :s"), {"s": sid})
    purge(engine, records)
    with engine.begin() as c:
        for sid in sessions:
            c.execute(text("DELETE FROM intake_session WHERE id = :s"), {"s": sid})


@pytest.fixture
def seeded(engine):
    with engine.begin() as c:
        er, clinic = near_duplicates(c)
        unrelated = insert_record(
            c, system="CLINIC_CSV", local_id="CLINIC-X", kind=SourceKind.CSV_ROW, demographics=UNRELATED_DEMOGRAPHICS
        )
    yield er, clinic, unrelated
    purge(engine, [er, clinic, unrelated])


def events(engine, sid, event_type=None):
    with engine.connect() as c:
        sql = "SELECT * FROM event_log WHERE intake_session_id = :s"
        params = {"s": sid}
        if event_type:
            sql += " AND event_type = :t"
            params["t"] = event_type
        return [dict(r._mapping) for r in c.execute(text(sql + " ORDER BY ts"), params)]


def handoff_events(engine, pair_ids):
    """Q1.1's writer keys INTAKE_HANDOFF_CREATED by pair_id (intake_session_id column is left null)."""
    with engine.connect() as c:
        return list(
            c.execute(
                text("SELECT pair_id FROM event_log WHERE event_type = 'INTAKE_HANDOFF_CREATED' AND pair_id = ANY(:p)"),
                {"p": list(pair_ids)},
            )
        )


# ---------------------------------------------------------------- routes and envelope


def test_session_create_pins_mode_server_side_and_rejects_a_mode_field(api, engine):
    client, _use, start, _turn, _ = api
    body = start("EN")
    assert body["agentMode"] == "REPLAY" and body["promptVersion"] == "fd-prompt/1"
    assert body["toolSchemaVersion"] == "fd-tools/1" and body["registration"]["state"] == "NONE"
    r = client.post("/api/v1/intake-sessions", json={"language": "EN", "agentMode": "LIVE"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert r.headers.get("X-Request-Id")
    assert events(engine, body["id"], "INTAKE_STARTED")


def test_turn_envelope_404_422_idempotency(api, engine):
    client, use, start, turn, _ = api
    use(ScriptedModel([say("Hello.")], engine))
    sid = start("EN")["id"]
    r = client.post(f"/api/v1/intake-sessions/{sid}/turns", json={"text": "hi"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR", "missing Idempotency-Key"
    r = turn(uuid.uuid4(), "hi")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    r = turn(sid, "x" * 501)
    assert r.status_code == 422
    key = str(uuid.uuid4())
    first = turn(sid, "hi", key)
    assert first.status_code == 201 and first.headers.get("X-Request-Id")
    again = turn(sid, "hi", key)
    assert again.status_code == 201 and again.json() == first.json(), "same key+body replays the stored response"
    mismatch = turn(sid, "hi there", key)
    assert mismatch.status_code == 422 and mismatch.json()["error"]["code"] == "IDEMPOTENCY_MISMATCH"
    got = client.get(f"/api/v1/intake-sessions/{sid}").json()
    assert got["turns"] == [first.json()]
    assert got["turns"][0]["assistantTextSource"] == "MODEL" and got["turns"][0]["assistantText"] == "Hello."


def test_in_flight_same_key_is_409_and_closed_session_is_409(api, engine):
    _client, use, start, turn, _ = api
    use(ScriptedModel([say("x")], engine))
    sid = start("EN")["id"]
    key = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO intake_turn (session_id, turn_index, client_request_id, request_sha256, status, user_text) "
                "VALUES (:s, 0, :k, :sha, 'IN_PROGRESS', 'hi')"
            ),
            {
                "s": sid,
                "k": key,
                "sha": __import__("backend.frontdesk.loop", fromlist=["x"]).request_sha256(
                    __import__("contracts.models.intake", fromlist=["x"]).TurnRequest(text="hi")
                ),
            },
        )
    r = turn(sid, "hi", key)
    assert r.status_code == 409 and r.json()["error"]["code"] == "TURN_IN_PROGRESS"
    with engine.begin() as c:
        c.execute(text("UPDATE intake_session SET closed_at = now() WHERE id = :s"), {"s": sid})
    r = turn(sid, "hi")
    assert r.status_code == 409 and r.json()["error"]["code"] == "SESSION_CLOSED"


def test_stale_lease_is_failed_at_next_claim_and_reclaimable(api, engine):
    _client, use, start, turn, _ = api
    use(ScriptedModel([say("x"), say("y")], engine))
    sid = start("EN")["id"]
    key = str(uuid.uuid4())
    from backend.frontdesk.loop import request_sha256
    from contracts.models.intake import TurnRequest

    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO intake_turn (session_id, turn_index, client_request_id, request_sha256, status, user_text, "
                "claimed_at) VALUES (:s, 0, :k, :sha, 'IN_PROGRESS', 'hi', now() - interval '41 seconds')"
            ),
            {"s": sid, "k": key, "sha": request_sha256(TurnRequest(text="hi"))},
        )
    r = turn(sid, "hi", key)
    assert r.status_code == 201, r.text
    with engine.connect() as c:
        st = c.execute(text("SELECT status FROM intake_turn WHERE session_id=:s AND turn_index=0"), {"s": sid}).scalar()
    assert st == "COMPLETED"


def test_served_openapi_matches_frozen_for_intake_paths(api):
    client, *_ = api
    served = client.get("/openapi.json").json()["paths"]
    frozen = json.loads((ROOT / "contracts" / "openapi.json").read_text())["paths"]
    for p in (
        "/api/v1/intake-sessions",
        "/api/v1/intake-sessions/{session_id}/turns",
        "/api/v1/intake-sessions/{session_id}",
    ):
        assert served[p] == frozen[p], p


# ---------------------------------------------------------------- the hero deny


def test_propose_on_near_duplicate_is_denied_audited_and_handed_off(api, engine, seeded):
    er, clinic, _unrelated = seeded
    client, use, start, turn, _ = api
    model = ScriptedModel(
        [call("propose_new_chart", HERO_ARGS), say("Gracias, una persona de registro le ayudará.")], engine
    )
    use(model)
    sid = start("ES")["id"]
    r = turn(sid, HERO_TEXT)
    assert r.status_code == 201, r.text
    body = r.json()
    tc = body["toolCalls"]
    assert len(tc) == 1
    gate = tc[0]["gate"]
    assert (
        gate["outcome"] == "DENY" and gate["reasonCode"] == "CANDIDATE_IN_REVIEW_OR_HIGHER" and gate["handoffRequired"]
    )
    assert gate["policyVersion"] == "frontdesk-gate/1"
    assert body["registration"]["state"] == "PENDING_REGISTRAR"
    assert body["registration"]["handoffPairIds"]
    assert tc[0]["effect"]["status"] == "NONE"
    cands = tc[0]["candidates"]
    assert 1 <= len(cands) <= 10
    ranks = {"AUTO_LINK": 0, "REVIEW": 1, "KEEP_SEPARATE": 2}
    assert [ranks[c["band"]] for c in cands] == sorted(ranks[c["band"]] for c in cands), "highest band first"
    # the model never sees UUIDs, p or clinical data (check the function message the loop built)
    func_msgs = [m for req in model.requests for m in req.messages if m.role == "function"]
    assert func_msgs, "the second model call carries the ToolResult"
    tool_result = func_msgs[-1].tool_result
    jsonschema.validate(tool_result, TOOL_RESULT_SCHEMA)
    assert tool_result["status"] == "DENIED" and tool_result["notice"] == "HANDED_TO_REGISTRAR"
    dumped = json.dumps(tool_result)
    for rid in (er, clinic):
        assert str(rid) not in dumped
    assert '"p"' not in dumped and "contributions" not in dumped
    # audit: exactly one AGENT_TOOL_CALLED with ADR-016 §6 columns
    ev = events(engine, sid, "AGENT_TOOL_CALLED")
    assert len(ev) == 1
    e = ev[0]
    assert e["tool_call_id"] == uuid.UUID(tc[0]["id"]) and e["tool_name"] == "propose_new_chart"
    assert e["gate_outcome"] == "DENY" and e["reason_code"] == "CANDIDATE_IN_REVIEW_OR_HIGHER"
    assert e["evidence_ids"] and e["evidence_snapshot"] and e["client_request_id"] and e["effect_status"] == "NONE"
    assert e["actor"] == "agent:frontdesk" and e["actor_type"] == "AGENT" and e["entry_point"] == "AGENT"
    assert e["band"] in ("REVIEW", "AUTO_LINK") and e["outcome"] == "DENIED" and e["mode"] == "REPLAY"
    assert e["pair_id"] is not None, "the row rests on a handoff pair"
    for k in ("promptVersion", "toolSchemaVersion", "policyVersion", "scorerVersion", "thresholdSetId"):
        assert e["versions"].get(k), k
    assert e["versions"]["promptVersion"] == "fd-prompt/1"
    # one INTAKE_HANDOFF_CREATED per pair
    with engine.connect() as c:
        pairs = list(
            c.execute(
                text("SELECT id, origin, intake_session_id FROM candidate_pair WHERE intake_session_id = :s"),
                {"s": sid},
            )
        )
    assert pairs and all(p.origin == "FRONTDESK_HANDOFF" for p in pairs)
    handoffs = handoff_events(engine, [p.id for p in pairs])
    assert len(handoffs) == len(pairs) == len(body["registration"]["handoffPairIds"])
    # tile
    tiles = client.get("/api/v1/metrics/tiles").json()
    gate_tile = next(t for t in tiles["tiles"] if t["id"] == "AGENT_GATE")
    assert sum(b["count"] for b in gate_tile["buckets"] if b["series"] == "DENY") >= 1, gate_tile
    # no chart created
    with engine.connect() as c:
        n = c.execute(
            text("SELECT count(*) FROM agent_tool_call WHERE effect_key LIKE 'chart:v1:%' AND session_id=:s"),
            {"s": sid},
        ).scalar()
    assert n == 0


def test_denied_twice_does_not_duplicate_handoff_pairs(api, engine, seeded):
    _client, use, start, turn, _ = api
    use(
        ScriptedModel(
            [call("propose_new_chart", HERO_ARGS), say("a"), call("propose_new_chart", HERO_ARGS), say("b")], engine
        )
    )
    sid = start("ES")["id"]
    assert turn(sid, HERO_TEXT).status_code == 201
    assert turn(sid, "sí, es correcto").status_code == 201
    with engine.connect() as c:
        pairs = c.execute(text("SELECT count(*) FROM candidate_pair WHERE intake_session_id = :s"), {"s": sid}).scalar()
        intakes = c.execute(
            text(
                "SELECT count(*) FROM source_record WHERE kind='FRONTDESK_INTAKE' AND id IN (SELECT intake_record_id FROM intake_session WHERE id=:s)"
            ),
            {"s": sid},
        ).scalar()
    with engine.connect() as c:
        pair_ids = [
            r[0] for r in c.execute(text("SELECT id FROM candidate_pair WHERE intake_session_id = :s"), {"s": sid})
        ]
    handoffs = handoff_events(engine, pair_ids)
    assert intakes == 1
    assert len(handoffs) == pairs, "one INTAKE_HANDOFF_CREATED per pair, not per call"


# ---------------------------------------------------------------- new patient, replay of the effect


def test_new_patient_is_allowed_once_then_replayed(api, engine, seeded):
    _client, use, start, turn, _ = api
    use(
        ScriptedModel(
            [
                call("propose_new_chart", NEW_ARGS),
                say("Done."),
                call("propose_new_chart", NEW_ARGS),
                say("Done again."),
            ],
            engine,
        )
    )
    sid = start("EN")["id"]
    r1 = turn(sid, NEW_TEXT).json()
    tc = r1["toolCalls"][0]
    assert tc["gate"]["outcome"] == "ALLOW" and tc["effect"]["status"] == "APPLIED"
    assert r1["registration"]["state"] == "NEW_CHART"
    r2 = turn(sid, "thanks").json()
    assert r2["toolCalls"][0]["effect"]["status"] == "REPLAYED"
    with engine.connect() as c:
        n = c.execute(
            text(
                "SELECT count(*) FROM source_record WHERE id = (SELECT intake_record_id FROM intake_session WHERE id=:s)"
            ),
            {"s": sid},
        ).scalar()
        keys = c.execute(
            text("SELECT count(*) FROM agent_tool_call WHERE session_id=:s AND effect_key IS NOT NULL"), {"s": sid}
        ).scalar()
    assert n == 1 and keys == 1


def test_model_claiming_a_chart_without_the_effect_is_swapped_for_the_template(api, engine, seeded):
    _client, use, start, turn, _ = api
    use(ScriptedModel([say("Great news, I created your chart.")], engine))
    sid = start("EN")["id"]
    body = turn(sid, NEW_TEXT).json()
    assert body["assistantTextSource"] == "TEMPLATE"
    assert body["assistantText"] == "One moment, a registrar will help you."
    use(ScriptedModel([call("propose_new_chart", NEW_ARGS), say("I created your chart.")], engine))
    sid2 = start("EN")["id"]
    body = turn(sid2, NEW_TEXT).json()
    assert body["assistantTextSource"] == "MODEL", "the claim is true after NEW_CHART_CREATED"
    sid3 = start("ES")["id"]
    use(ScriptedModel([say("Un momento. Esto es un chatbot certificado.")], engine))
    body = turn(sid3, "hola").json()
    assert body["assistantText"] == "Un momento, una persona de registro le va a ayudar."


# ---------------------------------------------------------------- compromised model


def test_unknown_tool_extra_property_bad_postal_are_audited_denies_not_500(api, engine, seeded):
    _client, use, start, turn, _ = api
    bad_postal = {**NEW_ARGS, "postalCode": "ABCDE", "evidence": {**NEW_ARGS["evidence"], "postalCode": "ABCDE"}}
    use(
        ScriptedModel(
            [
                call("approve_link", {"pairId": "x"}),
                call("propose_new_chart", {**NEW_ARGS, "recordId": "11111111-1111-1111-1111-111111111111"}),
                call("propose_new_chart", bad_postal),
                call(
                    "attach_history",
                    {"items": [{"kind": "OTHER", "text": "phone 555 123 4567", "evidenceQuote": "phone 555 123 4567"}]},
                ),
                say("ok"),
            ],
            engine,
        )
    )
    sid = start("EN")["id"]
    r = turn(sid, NEW_TEXT)
    assert r.status_code == 201, r.text
    reasons = [t["gate"]["reasonCode"] for t in r.json()["toolCalls"]]
    assert reasons == ["UNKNOWN_TOOL", "INVALID_ARGUMENTS", "INVALID_ARGUMENTS", "NO_INTAKE_RECORD"], reasons
    assert all(t["gate"]["outcome"] == "DENY" for t in r.json()["toolCalls"])
    assert len(events(engine, sid, "AGENT_TOOL_CALLED")) == 4
    assert r.json()["registration"]["state"] == "NONE"


def test_seven_tool_calls_trip_the_loop_guard_and_the_template(api, engine, seeded):
    _client, use, start, turn, _ = api
    model = ScriptedModel(
        [
            call(
                "search_patients",
                {
                    "givenName": "Priscilla",
                    "familyName": "Oyelaran-Whitcombe",
                    "evidence": {"givenName": "Priscilla", "familyName": "Oyelaran-Whitcombe"},
                },
            )
        ]
        * 8,
        engine,
    )
    use(model)
    sid = start("EN")["id"]
    body = turn(sid, NEW_TEXT).json()
    assert body["degraded"] == "LOOP_GUARD" and body["assistantTextSource"] == "TEMPLATE"
    assert len(body["toolCalls"]) == 7 and body["toolCalls"][-1]["gate"]["reasonCode"] == "LOOP_GUARD"
    assert len(events(engine, sid, "AGENT_TURN_DEGRADED")) == 1
    assert model.calls == 7


def test_timeout_retries_once_then_degrades_and_two_degraded_turns_stop_calling_the_model(api, engine, seeded):
    _client, use, start, turn, _ = api
    sid = start("EN")["id"]
    m1 = ScriptedModel([err("TIMEOUT", True), err("TIMEOUT", True), say("never")], engine)
    use(m1)
    from backend.frontdesk import loop as loop_mod

    loop_mod.RETRY_DELAY_S = 0.01  # keep the test fast; the count is what matters
    body = turn(sid, "hello").json()
    assert m1.calls == 2, "exactly one retry"
    assert body["degraded"] == "TIMEOUT" and body["assistantTextSource"] == "TEMPLATE"
    assert body["assistantText"] == "One moment, a registrar will help you."
    assert len(events(engine, sid, "AGENT_TURN_DEGRADED")) == 1
    m2 = ScriptedModel([err("UNAVAILABLE", False)], engine)
    use(m2)
    body = turn(sid, "hello?").json()
    assert m2.calls == 1 and body["degraded"] == "UNAVAILABLE"
    m3 = ScriptedModel([say("I am back")], engine)
    use(m3)
    body = turn(sid, "anyone?").json()
    assert m3.calls == 0, "after two degraded turns the model is not called"
    assert body["assistantTextSource"] == "TEMPLATE"
    assert "MALFORMED" not in str(events(engine, sid))


def test_replay_mode_without_the_player_degrades_honestly(api, engine, monkeypatch):
    """Default adapter factory in REPLAY: the template through the loop, labelled REPLAY, never LIVE."""
    from backend.api import intake
    from backend.app import main

    main.app.dependency_overrides.pop(intake.get_model_factory, None)
    _client, _use, start, turn, _ = api
    monkeypatch.setenv("FRONTDESK_AGENT_MODE", "REPLAY")
    sid = start("EN")["id"]
    body = turn(sid, "hi").json()
    assert body["agentMode"] == "REPLAY" and body["assistantTextSource"] == "TEMPLATE" and body["degraded"]


# ---------------------------------------------------------------- audit hygiene


def test_user_free_text_does_not_land_in_event_payload(api, engine, seeded):
    """ADR-016 §6: payload is validated args, never free text. A model that quotes the whole typed
    line as evidence puts the whole typed line in event_log.payload."""
    _client, use, start, turn, _ = api
    typed = "I am Priscilla Oyelaran-Whitcombe, born 1992-11-28, female, phone 555 123 4567, and I hate hospitals"
    args = {**NEW_ARGS, "evidence": {**NEW_ARGS["evidence"], "givenName": typed}}
    use(ScriptedModel([call("propose_new_chart", args), say("ok")], engine))
    sid = start("EN")["id"]
    turn(sid, typed)
    for e in events(engine, sid):
        assert typed not in json.dumps(e["payload"]), (e["event_type"], e["payload"])


def test_registration_reads_new_chart_after_a_release_and_an_allowed_propose(api, engine, seeded):
    """ADR-016 §3: REJECT DIFFERENT_PERSON releases; the next propose is ALLOWED and creates the chart.
    The derived state must then be NEW_CHART, not RELEASED."""
    client, use, start, turn, _ = api
    use(
        ScriptedModel(
            [call("propose_new_chart", HERO_ARGS), say("a"), call("propose_new_chart", HERO_ARGS), say("b")], engine
        )
    )
    sid = start("ES")["id"]
    body = turn(sid, HERO_TEXT).json()
    for pid in body["registration"]["handoffPairIds"]:
        r = client.post(
            f"/api/v1/candidate-pairs/{pid}/reviews",
            json={"action": "REJECT", "actor": "registrar:Registrar A", "reasonCode": "DIFFERENT_PERSON"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert r.status_code in (200, 201), r.text
    body = turn(sid, "sí").json()
    tc = body["toolCalls"][0]
    assert tc["gate"]["outcome"] == "ALLOW" and tc["effect"]["status"] == "APPLIED"
    assert body["registration"]["state"] == "NEW_CHART", body["registration"]


def test_adapter_exception_does_not_leave_the_turn_in_progress(api, engine):
    """Adapters must not raise, but if one does the turn must not sit IN_PROGRESS behind a 500."""
    _client, use, start, turn, _ = api
    m = ScriptedModel([], engine)
    m.raise_exc = RuntimeError("boom")
    use(m)
    sid = start("EN")["id"]
    key = str(uuid.uuid4())
    r = turn(sid, "hi", key)
    assert r.status_code != 201
    with engine.connect() as c:
        st = c.execute(text("SELECT status FROM intake_turn WHERE session_id=:s"), {"s": sid}).scalar()
    assert st == "FAILED", f"turn left {st}; a retry with the same key gets 409 until the 40 s lease expires"


def test_gemini_module_imports_without_network_and_names_real_sdk_enums():
    import importlib
    import sys

    mod = importlib.import_module("backend.frontdesk.gemini")
    assert "google.genai" in sys.modules
    assert mod.SDK_ATTEMPTS == 1 and mod.FUNCTION_RESPONSE_ROLE == "user"
    assert mod._BLOCKED_FINISH  # FinishReason members resolved at import
    assert "gemini-" not in Path(mod.__file__).read_text()
