"""Invalid text at the intake boundary is a 422 VALIDATION_ERROR, never a 500.

Two causes, one test each per route. (1) JSON lets a string carry U+0000 and the frozen schema allows
it, but Postgres text and jsonb cannot hold it: the insert raised DataError, the 500 CI's schemathesis
job found on POST /intake-sessions. (2) Pydantic rejects an unpaired surrogate (``\\ud800``) as a 422,
but the validation envelope echoed it back and could not be encoded to UTF-8 (UnicodeEncodeError).
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


def _sessions_with_context(conn, marker: str) -> int:
    return conn.execute(
        text("SELECT count(*) FROM intake_session WHERE strpos(scenario_context_id, :m) > 0"), {"m": marker}
    ).scalar_one()


def _assert_validation_error(r, field: str) -> None:
    assert r.status_code == 422, r.text
    error = r.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    if isinstance(error["details"], list):  # Pydantic's errors, each naming where it failed
        assert any(field in d["loc"] for d in error["details"]), error["details"]
    else:  # the route's own boundary check
        assert error["details"] == {"field": field}
    assert "X-Request-Id" in r.headers


@pytest.mark.parametrize("bad", [NUL, LONE_SURROGATE], ids=["nul", "lone-surrogate"])
def test_create_session_rejects_unstorable_scenario_context_id(client, db_conn, bad):
    marker = uuid.uuid4().hex[:12]
    body = '{"language":"EN","scenarioContextId":"' + marker + bad + '"}'
    r = client.post(f"{API}/intake-sessions", content=body.encode(), headers=JSON_HEADERS)
    _assert_validation_error(r, "scenarioContextId")
    assert _sessions_with_context(db_conn, marker) == 0  # nothing was written before the refusal


def test_surrogate_in_validation_details_is_escaped_not_dropped(client):
    r = client.post(f"{API}/intake-sessions", content=b'{"scenarioContextId":"x\\ud800"}', headers=JSON_HEADERS)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["details"][0]["input"] == "x\\ud800"  # escaped as text, not the raw surrogate


def test_create_session_still_accepts_other_control_characters(client, cleanup):
    # Only what the store cannot hold is refused; a schema-valid tab or U+0001 is still a 201.
    body = '{"language":"EN","scenarioContextId":"hero\\t\\u0001"}'
    r = client.post(f"{API}/intake-sessions", content=body.encode(), headers=JSON_HEADERS)
    assert r.status_code == 201, r.text
    cleanup[0].append(r.json()["id"])


@pytest.mark.parametrize("bad", [NUL, LONE_SURROGATE], ids=["nul", "lone-surrogate"])
def test_turn_rejects_unstorable_text(client, fake, db_conn, cleanup, bad):
    session = create_session(client, "EN")
    cleanup[0].append(session["id"])
    body = '{"text":"Hello' + bad + '"}'
    r = client.post(
        f"{API}/intake-sessions/{session['id']}/turns",
        content=body.encode(),
        headers=JSON_HEADERS | {"Idempotency-Key": new_key()},
    )
    _assert_validation_error(r, "text")
    turns = db_conn.execute(
        text("SELECT count(*) FROM intake_turn WHERE session_id = :s"), {"s": uuid.UUID(session["id"])}
    ).scalar_one()
    assert turns == 0
    assert fake.requests == []  # the model never saw the turn


def test_encodable_escapes_surrogates_in_keys_values_and_nesting():
    # Unit check of the envelope helper: every string a validation error can echo, keys included.
    from backend.app.main import _encodable

    out = _encodable({"loc": ["body", "k\ud800"], "input": {"\udfff": ["v\ud800", 1, None]}, "msg": "plain"})
    assert out == {"loc": ["body", "k\\ud800"], "input": {"\\udfff": ["v\\ud800", 1, None]}, "msg": "plain"}
    assert _encodable("ascii and é stay as they are") == "ascii and é stay as they are"
