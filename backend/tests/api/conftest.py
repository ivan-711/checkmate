"""API tests run against the lane's own test database, never the dev database.

Set ``CHECKMATE_TEST_DATABASE_URL`` to override the default. The database name must
contain ``test``; the dev database ``checkmate`` is refused so a reset in a test can never
truncate demo state.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

DEFAULT_TEST_URL = "postgresql://checkmate:checkmate@127.0.0.1:5432/checkmate_test_w3a"
TEST_URL = os.environ.get("CHECKMATE_TEST_DATABASE_URL", DEFAULT_TEST_URL)

if "test" not in TEST_URL.rsplit("/", 1)[-1]:
    raise SystemExit(f"refusing to run API tests against a non-test database: {TEST_URL.rsplit('/', 1)[-1]}")

# The composition root reads DATABASE_URL at import; point it at the test database first.
os.environ["DATABASE_URL"] = TEST_URL
os.environ.setdefault("FRONTDESK_AGENT_MODE", "REPLAY")

from backend.app.main import app, engine  # after the environment is set
from backend.tests.api.hero_corpus import hero_corpus  # noqa: F401  (fixture for every API test module)

API = "/api/v1"


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_conn():
    """Read-only inspection of tables the tests assert on (event_log, not_a_match, ...).

    Autocommit, so a read holds no lock past its own statement: an open read transaction would make
    a later reset's TRUNCATE wait out the 5 s statement_timeout and answer 503."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        yield conn


def count_events(conn, event_type: str, **where) -> int:
    clauses = " AND ".join(f"{k} = :{k}" for k in where)
    sql = "SELECT count(*) FROM event_log WHERE event_type = :event_type"
    if clauses:
        sql += " AND " + clauses
    return conn.execute(text(sql), {"event_type": event_type, **where}).scalar_one()


@pytest.fixture
def session(client: TestClient) -> dict:
    """A fresh demo state: reset to the hero scenario."""
    r = client.post(f"{API}/sessions", json={"scenarioId": "hero"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def match_run(client: TestClient, session: dict) -> dict:
    r = client.post(f"{API}/match-runs")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["queuedPairIds"], "the hero scenario must queue at least one pair"
    return body


@pytest.fixture
def pair_id(match_run: dict) -> str:
    return match_run["queuedPairIds"][0]


def new_key() -> str:
    return str(uuid.uuid4())


def review(client: TestClient, pair_id: str, body: dict, key: str | None = None):
    headers = {"Idempotency-Key": key or new_key()}
    return client.post(f"{API}/candidate-pairs/{pair_id}/reviews", json=body, headers=headers)


def approve_body(actor: str = "Registrar A", note: str | None = None) -> dict:
    body = {"action": "APPROVE", "actor": actor}
    if note is not None:
        body["note"] = note
    return body


def reject_body(reason: str = "INSUFFICIENT_EVIDENCE", actor: str = "Registrar A", note: str | None = None) -> dict:
    body = {"action": "REJECT", "actor": actor, "reasonCode": reason}
    if note is not None:
        body["note"] = note
    return body
