"""The three intake routes through the real gate and chart-store writes, with a scripted model."""

from __future__ import annotations

import uuid

import jsonschema
from sqlalchemy import text

from backend.frontdesk.tools import tool_result_schema
from backend.tests.frontdesk.conftest import API, create_session, error, new_key, tool_call, turn
from backend.tests.policy.seed import CLINIC_DEMOGRAPHICS, ER_DEMOGRAPHICS, insert_record
from backend.tests.policy.test_gate_db import PROPOSE_ARGS, UNRELATED_ARGS, UNRELATED_TEXT, USER_TEXT
from contracts.models.common import SourceKind
from contracts.models.intake import IntakeTurn

ATTACH_ARGS = {"items": [{"kind": "ALLERGY", "text": "penicillin", "evidenceQuote": "alérgica a la penicilina"}]}
ATTACH_TEXT = USER_TEXT + ". Soy alérgica a la penicilina."


def seed_near_duplicates(conn, cleanup) -> tuple[uuid.UUID, uuid.UUID]:
    tag = uuid.uuid4().hex[:8]
    er = insert_record(
        conn, system="ER_FHIR", local_id=f"ER-{tag}", kind=SourceKind.FHIR_PATIENT, demographics=ER_DEMOGRAPHICS
    )
    clinic = insert_record(
        conn, system="CLINIC_CSV", local_id=f"CLINIC-{tag}", kind=SourceKind.CSV_ROW, demographics=CLINIC_DEMOGRAPHICS
    )
    cleanup[1].extend([er, clinic])
    return er, clinic


def events(conn, session_id: str, event_type: str) -> list:
    return conn.execute(
        text("SELECT * FROM event_log WHERE intake_session_id = :s AND event_type = :t ORDER BY ts"),
        {"s": uuid.UUID(session_id), "t": event_type},
    ).all()


def test_near_duplicate_is_held_handed_off_and_audited(client, fake, db_conn, cleanup):
    seed_near_duplicates(db_conn, cleanup)
    session = create_session(client, "ES")
    cleanup[0].append(session["id"])
    assert session["agentMode"] == "REPLAY" and session["promptVersion"] == "fd-prompt/1"
    assert len(events(db_conn, session["id"], "INTAKE_STARTED")) == 1

    fake.steps = [tool_call("propose_new_chart", PROPOSE_ARGS)]
    key = new_key()
    r = turn(client, session["id"], USER_TEXT, key)
    assert r.status_code == 201, r.text
    body = r.json()
    IntakeTurn.model_validate(body)
    call = body["toolCalls"][0]
    assert call["gate"]["outcome"] == "DENY"
    assert call["gate"]["reasonCode"] == "CANDIDATE_IN_REVIEW_OR_HIGHER"
    assert call["gate"]["handoffRequired"] is True
    assert call["gate"]["policyVersion"] == "frontdesk-gate/1"
    assert call["effect"]["status"] == "NONE"
    assert call["candidates"] and call["candidates"][0]["band"] in {"REVIEW", "AUTO_LINK"}
    assert len(call["candidates"]) <= 10
    assert body["registration"]["state"] == "PENDING_REGISTRAR"
    assert body["registration"]["handoffPairIds"]
    assert body["assistantTextSource"] == "MODEL" and body["degraded"] is None

    # What the model saw: the minimal ToolResult, valid against the frozen schema, aliases only.
    seen = fake.requests[-1].messages[-1].tool_result
    jsonschema.validate(seen, tool_result_schema())
    assert seen["status"] == "DENIED" and seen["notice"] == "HANDED_TO_REGISTRAR"
    assert all(c["candidateRef"].startswith("C") for c in seen["candidates"])
    assert fake.requests[-1].last_tool_result_sha256 is not None

    # ADR-016 §6: one AGENT_TOOL_CALLED row with every intake column set.
    rows = events(db_conn, session["id"], "AGENT_TOOL_CALLED")
    assert len(rows) == 1
    ev = rows[0]._mapping
    assert ev["entry_point"] == "AGENT" and ev["actor"] == "agent:frontdesk" and ev["actor_type"] == "AGENT"
    assert ev["band"] in {"REVIEW", "AUTO_LINK"} and ev["outcome"] == "DENIED"
    assert ev["gate_outcome"] == "DENY" and ev["reason_code"] == "CANDIDATE_IN_REVIEW_OR_HIGHER"
    assert ev["tool_name"] == "propose_new_chart" and ev["tool_call_id"] == uuid.UUID(call["id"])
    assert ev["evidence_ids"] and ev["evidence_snapshot"]["candidates"]
    assert ev["client_request_id"] == key and ev["effect_status"] == "NONE"
    assert ev["mode"] == "LIVE"  # where the model step came from: the fake says LIVE
    versions = ev["versions"]
    for k in ("scorerVersion", "thresholdSetId", "policyVersion", "promptVersion", "toolSchemaVersion"):
        assert versions.get(k), k
    assert ev["payload"]["givenName"] == "Maria Jose"  # validated args, never free text
    assert ev["pair_id"] is not None
    handoffs = db_conn.execute(
        text("SELECT count(*) FROM event_log WHERE event_type = 'INTAKE_HANDOFF_CREATED' AND pair_id = ANY(:p)"),
        {"p": [uuid.UUID(p) for p in body["registration"]["handoffPairIds"]]},
    ).scalar_one()
    assert handoffs == len(body["registration"]["handoffPairIds"])

    tiles = client.get(f"{API}/metrics/tiles?window_minutes=60").json()["tiles"]
    gate_tile = next(t for t in tiles if t["id"] == "AGENT_GATE")
    assert gate_tile["total"] >= 1
    assert any(b["series"] == "DENY" and b["count"] >= 1 for b in gate_tile["buckets"])

    # Reload equals the turn response.
    got = client.get(f"{API}/intake-sessions/{session['id']}").json()
    assert got["turns"] == [body]
    assert got["registration"] == body["registration"]


def test_new_patient_is_allowed_once_and_replayed_after(client, fake, db_conn, cleanup):
    session = create_session(client, "EN")
    cleanup[0].append(session["id"])
    fake.steps = [tool_call("propose_new_chart", UNRELATED_ARGS)]
    first = turn(client, session["id"], UNRELATED_TEXT).json()
    call = first["toolCalls"][0]
    assert call["gate"]["outcome"] == "ALLOW" and call["effect"]["status"] == "APPLIED"
    assert first["registration"]["state"] == "NEW_CHART"
    assert fake.requests[-1].messages[-1].tool_result["notice"] == "NEW_CHART_CREATED"

    fake.steps = [tool_call("propose_new_chart", UNRELATED_ARGS)]
    second = turn(client, session["id"], UNRELATED_TEXT).json()
    assert second["toolCalls"][0]["effect"]["status"] == "REPLAYED"
    assert second["registration"]["intakeRecordId"] == first["registration"]["intakeRecordId"]
    n = db_conn.execute(
        text("SELECT count(*) FROM source_record WHERE source_local_id = :l"), {"l": f"intake:{session['id']}"}
    ).scalar_one()
    assert n == 1
    keys = (
        db_conn.execute(
            text("SELECT effect_key FROM agent_tool_call WHERE session_id = :s ORDER BY turn_index"),
            {"s": uuid.UUID(session["id"])},
        )
        .scalars()
        .all()
    )
    assert keys == [f"chart:v1:{session['id']}", None]


def test_attach_history_before_intake_is_denied(client, fake, cleanup):
    session = create_session(client)
    cleanup[0].append(session["id"])
    fake.steps = [tool_call("attach_history", ATTACH_ARGS)]
    body = turn(client, session["id"], ATTACH_TEXT).json()
    gate = body["toolCalls"][0]["gate"]
    assert (gate["outcome"], gate["reasonCode"]) == ("DENY", "NO_INTAKE_RECORD")
    assert body["registration"]["state"] == "NONE"


def test_attach_history_after_intake_is_recorded_once(client, fake, db_conn, cleanup):
    session = create_session(client, "EN")
    cleanup[0].append(session["id"])
    fake.steps = [tool_call("propose_new_chart", UNRELATED_ARGS)]
    turn(client, session["id"], UNRELATED_TEXT)
    attach = {"items": [{"kind": "ALLERGY", "text": "penicillin", "evidenceQuote": "allergic to penicillin"}]}
    fake.steps = [tool_call("attach_history", attach), tool_call("attach_history", attach)]
    body = turn(client, session["id"], "I am allergic to penicillin").json()
    statuses = [c["effect"]["status"] for c in body["toolCalls"]]
    assert statuses == ["APPLIED", "REPLAYED"]
    n = db_conn.execute(
        text("SELECT count(*) FROM intake_history_item WHERE intake_record_id = :r"),
        {"r": uuid.UUID(body["registration"]["intakeRecordId"])},
    ).scalar_one()
    assert n == 1


def test_unknown_tool_is_audited_not_raised(client, fake, db_conn, cleanup):
    session = create_session(client)
    cleanup[0].append(session["id"])
    fake.steps = [tool_call("approve_link", {"pairId": "x"})]
    r = turn(client, session["id"], USER_TEXT)
    assert r.status_code == 201
    call = r.json()["toolCalls"][0]
    assert call["gate"]["reasonCode"] == "UNKNOWN_TOOL" and call["args"] is None
    assert events(db_conn, session["id"], "AGENT_TOOL_CALLED")[0]._mapping["reason_code"] == "UNKNOWN_TOOL"


def test_invalid_arguments_extra_property_and_bad_postal_code(client, fake, cleanup):
    session = create_session(client)
    cleanup[0].append(session["id"])
    fake.steps = [
        tool_call("propose_new_chart", {**PROPOSE_ARGS, "overrideGate": True}),
        tool_call("propose_new_chart", {**PROPOSE_ARGS, "postalCode": "54311 WI"}),
    ]
    body = turn(client, session["id"], USER_TEXT).json()
    assert [c["gate"]["reasonCode"] for c in body["toolCalls"]] == ["INVALID_ARGUMENTS", "INVALID_ARGUMENTS"]
    assert body["registration"]["state"] == "NONE"


def test_ungrounded_field_is_denied(client, fake, cleanup):
    session = create_session(client)
    cleanup[0].append(session["id"])
    args = {**PROPOSE_ARGS, "phone": "5551234567", "evidence": {**PROPOSE_ARGS["evidence"], "phone": "555 123 4567"}}
    fake.steps = [tool_call("propose_new_chart", args)]
    body = turn(client, session["id"], USER_TEXT).json()
    assert body["toolCalls"][0]["gate"]["reasonCode"] == "UNGROUNDED_FIELD"


def test_idempotency_same_key_replays_different_body_422_missing_key_422(client, fake, cleanup):
    session = create_session(client)
    cleanup[0].append(session["id"])
    key = new_key()
    first = turn(client, session["id"], "Hola", key)
    again = turn(client, session["id"], "Hola", key)
    assert first.status_code == 201 and again.status_code == 201
    assert again.json() == first.json()
    assert len(fake.requests) == 1  # the replay never called the model
    mismatch = turn(client, session["id"], "Hola!", key)
    assert mismatch.status_code == 422 and mismatch.json()["error"]["code"] == "IDEMPOTENCY_MISMATCH"
    missing = client.post(f"{API}/intake-sessions/{session['id']}/turns", json={"text": "Hola"})
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "VALIDATION_ERROR"


def test_timeout_retries_once_then_degrades_to_the_template(client, fake, db_conn, cleanup):
    session = create_session(client, "ES")
    cleanup[0].append(session["id"])
    fake.steps = [error("TIMEOUT", True), error("TIMEOUT", True)]
    body = turn(client, session["id"], USER_TEXT).json()
    assert body["degraded"] == "TIMEOUT"
    assert body["assistantTextSource"] == "TEMPLATE"
    assert body["assistantText"] == "Un momento, una persona de registro le va a ayudar."
    assert len(fake.requests) == 2  # one retry, no third attempt
    degraded = events(db_conn, session["id"], "AGENT_TURN_DEGRADED")
    assert len(degraded) == 1 and degraded[0]._mapping["outcome"] == "TIMEOUT"
    stored = db_conn.execute(
        text("SELECT degraded, status FROM intake_turn WHERE session_id = :s"), {"s": uuid.UUID(session["id"])}
    ).one()
    assert (stored.degraded, stored.status) == ("TIMEOUT", "COMPLETED")


def test_non_retryable_error_is_not_retried(client, fake, cleanup):
    session = create_session(client, "EN")
    cleanup[0].append(session["id"])
    fake.steps = [error("UNAVAILABLE", False)]
    body = turn(client, session["id"], "Hello").json()
    assert body["degraded"] == "UNAVAILABLE" and body["assistantText"] == "One moment, a registrar will help you."
    assert len(fake.requests) == 1


def test_two_degraded_turns_switch_the_session_to_the_template(client, fake, cleanup):
    session = create_session(client)
    cleanup[0].append(session["id"])
    fake.steps = [error("UNAVAILABLE", False), error("UNAVAILABLE", False)]
    turn(client, session["id"], "uno")
    turn(client, session["id"], "dos")
    calls_before = len(fake.requests)
    third = turn(client, session["id"], "tres").json()
    assert third["degraded"] == "UNAVAILABLE" and third["assistantTextSource"] == "TEMPLATE"
    assert len(fake.requests) == calls_before  # the model was not called


def test_banned_phrase_is_swapped_for_the_template(client, fake, cleanup):
    session = create_session(client, "ES")
    cleanup[0].append(session["id"])
    fake.final_text = "Listo, creé su expediente. Puede sentarse."
    body = turn(client, session["id"], "Hola").json()
    assert body["assistantTextSource"] == "TEMPLATE"
    assert body["assistantText"] == "Un momento, una persona de registro le va a ayudar."
    assert body["degraded"] is None


def test_loop_guard_denies_the_seventh_call_and_ends_with_the_template(client, fake, cleanup):
    session = create_session(client)
    cleanup[0].append(session["id"])
    search = {"givenName": "Maria Jose", "familyName": "Gonzalez Rivera", "evidence": PROPOSE_ARGS["evidence"]}
    fake.steps = [tool_call("search_patients", search) for _ in range(8)]
    body = turn(client, session["id"], USER_TEXT).json()
    assert body["degraded"] == "LOOP_GUARD" and body["assistantTextSource"] == "TEMPLATE"
    reasons = [c["gate"]["reasonCode"] for c in body["toolCalls"]]
    assert reasons[-1] == "LOOP_GUARD" and len(body["toolCalls"]) <= 7
    assert "LOOP_GUARD" in reasons


def test_get_unknown_session_is_404(client):
    r = client.get(f"{API}/intake-sessions/{uuid.uuid4()}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
