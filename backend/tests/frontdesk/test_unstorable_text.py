"""Text Postgres cannot hold never makes an intake route answer 500.

Two causes. (1) JSON and the frozen schema allow U+0000 in ``scenarioContextId`` and turn ``text``, but
Postgres text and jsonb cannot hold it: the insert raised DataError, the 500 CI's schemathesis job found
on POST /intake-sessions. The request is schema-compliant, so a 422 would be a rejected valid request
(positive_data_acceptance): the routes drop U+0000 at the boundary and proceed. (2) Pydantic rejects an
unpaired surrogate (``\\ud800``) as a 422, but the validation envelope echoed it back and could not be
encoded to UTF-8 (UnicodeEncodeError); it stays a 422 with the echo escaped.
The bodies are sent as raw bytes so the JSON escape reaches the server as written (the test client's
encoder would refuse the surrogate itself).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.tests.frontdesk.conftest import API, create_session, new_key

NUL = "\\u0000"  # the JSON escape, as it travels on the wire
LONE_SURROGATE = "\\ud800"
JSON_HEADERS = {"Content-Type": "application/json"}


def _post_session(client, scenario_context_id_json: str):
    body = '{"language":"EN","scenarioContextId":"' + scenario_context_id_json + '"}'
    return client.post(f"{API}/intake-sessions", content=body.encode(), headers=JSON_HEADERS)


def _post_turn(client, session_id: str, text_json: str):
    return client.post(
        f"{API}/intake-sessions/{session_id}/turns",
        content=('{"text":"' + text_json + '"}').encode(),
        headers=JSON_HEADERS | {"Idempotency-Key": new_key()},
    )


def _stored_context(conn, session_id: str) -> str | None:
    return conn.execute(
        text("SELECT scenario_context_id FROM intake_session WHERE id = :s"), {"s": uuid.UUID(session_id)}
    ).scalar_one()


def _started_payload_context(conn, session_id: str) -> str | None:
    return conn.execute(
        text("SELECT payload->>'scenarioContextId' FROM event_log WHERE intake_session_id = :s AND event_type = :t"),
        {"s": uuid.UUID(session_id), "t": "INTAKE_STARTED"},
    ).scalar_one()


def _stored_turn_texts(conn, session_id: str) -> list[str]:
    rows = conn.execute(
        text("SELECT user_text FROM intake_turn WHERE session_id = :s ORDER BY turn_index"),
        {"s": uuid.UUID(session_id)},
    )
    return [r[0] for r in rows]


@pytest.mark.parametrize(("sent", "stored"), [(f"hero{NUL}-a{NUL}", "hero-a"), (NUL, "")], ids=["embedded", "only-nul"])
def test_nul_in_scenario_context_id_is_dropped_and_the_session_starts(client, db_conn, cleanup, sent, stored):
    r = _post_session(client, sent)
    assert r.status_code == 201, r.text
    session_id = r.json()["id"]
    cleanup[0].append(session_id)
    assert _stored_context(db_conn, session_id) == stored
    assert _started_payload_context(db_conn, session_id) == stored  # the jsonb event payload too


@pytest.mark.parametrize(("sent", "stored"), [(f"Hel{NUL}lo", "Hello"), (NUL, "")], ids=["embedded", "only-nul"])
def test_nul_in_turn_text_is_dropped_and_the_turn_runs(client, fake, db_conn, cleanup, sent, stored):
    session = create_session(client, "EN")
    cleanup[0].append(session["id"])
    r = _post_turn(client, session["id"], sent)
    assert r.status_code == 201, r.text
    assert r.json()["userText"] == stored
    assert _stored_turn_texts(db_conn, session["id"]) == [stored]
    assert fake.requests  # the agent loop ran on the stripped text


def test_create_session_still_keeps_other_control_characters(client, db_conn, cleanup):
    # Only U+0000 is dropped; a schema-valid tab or U+0001 is stored as sent.
    r = _post_session(client, "hero\\t\\u0001")
    assert r.status_code == 201, r.text
    cleanup[0].append(r.json()["id"])
    assert _stored_context(db_conn, r.json()["id"]) == "hero\t\x01"


def test_lone_surrogate_in_scenario_context_id_is_a_422(client, db_conn):
    marker = uuid.uuid4().hex[:12]
    r = _post_session(client, marker + LONE_SURROGATE)
    assert r.status_code == 422, r.text
    error = r.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert any("scenarioContextId" in d["loc"] for d in error["details"])
    assert error["details"][0]["input"] == marker + "\\ud800"  # echoed escaped, not the raw surrogate
    assert "X-Request-Id" in r.headers
    written = db_conn.execute(
        text("SELECT count(*) FROM intake_session WHERE strpos(scenario_context_id, :m) > 0"), {"m": marker}
    ).scalar_one()
    assert written == 0


def test_lone_surrogate_in_turn_text_is_a_422(client, fake, db_conn, cleanup):
    session = create_session(client, "EN")
    cleanup[0].append(session["id"])
    r = _post_turn(client, session["id"], "Hello" + LONE_SURROGATE)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert _stored_turn_texts(db_conn, session["id"]) == []
    assert fake.requests == []  # the model never saw the turn


def test_encodable_escapes_surrogates_in_keys_values_and_nesting():
    # Unit check of the envelope helper: every string a validation error can echo, keys included.
    from backend.app.main import _encodable

    out = _encodable({"loc": ["body", "k\ud800"], "input": {"\udfff": ["v\ud800", 1, None]}, "msg": "plain"})
    assert out == {"loc": ["body", "k\\ud800"], "input": {"\\udfff": ["v\\ud800", 1, None]}, "msg": "plain"}
    assert _encodable("ascii and é stay as they are") == "ascii and é stay as they are"
