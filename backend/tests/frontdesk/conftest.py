"""FrontDesk route tests: the real app, the real gate and chart-store writes, a scripted fake model.

The lane's own test database only (``CHECKMATE_TEST_DATABASE_URL``); the dev database is refused.
No test here ever touches the network or needs a key: the model is injected through
``backend.api.intake.get_model_factory``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.frontdesk.model import ErrorStep, ModelRequest, ModelStep, TextStep, ToolCallStep
from contracts.models.intake import AgentMode

DEFAULT_TEST_URL = "postgresql://checkmate:checkmate@127.0.0.1:5432/checkmate_test_q1_2"
TEST_URL = os.environ.get("CHECKMATE_TEST_DATABASE_URL", DEFAULT_TEST_URL)
if "test" not in TEST_URL.rsplit("/", 1)[-1]:
    raise SystemExit(f"refusing to run FrontDesk tests against a non-test database: {TEST_URL.rsplit('/', 1)[-1]}")

os.environ["DATABASE_URL"] = TEST_URL
os.environ.setdefault("FRONTDESK_AGENT_MODE", "REPLAY")
# No test ever calls the live API: the key leaves the environment for the whole session before the
# app is imported, and every Client construction in gemini.py is a fake unless a test installs its own.
os.environ.pop("GEMINI_API_KEY", None)

from backend.api import intake as intake_api
from backend.app.main import app, engine
from backend.frontdesk import budget, gemini

API = "/api/v1"
DEFAULT_TEXT_REPLY = "Gracias. Una persona de registro va a confirmar su expediente en un momento."


@dataclass
class FakeAgentModel:
    """Returns the scripted steps in order, then a plain text reply; records every request it saw."""

    steps: list[ModelStep] = field(default_factory=list)
    mode: AgentMode = AgentMode.LIVE
    requests: list[ModelRequest] = field(default_factory=list)
    final_text: str = DEFAULT_TEXT_REPLY

    def next_step(self, req: ModelRequest) -> ModelStep:
        self.requests.append(req)
        if self.steps:
            return self.steps.pop(0)
        return TextStep(text=self.final_text, latency_ms=1, mode=self.mode)


def tool_call(name: str, args: dict, mode: AgentMode = AgentMode.LIVE) -> ToolCallStep:
    return ToolCallStep(tool_name=name, args=args, model_call_id=None, latency_ms=1, mode=mode)


def error(kind: str, retryable: bool, mode: AgentMode = AgentMode.LIVE) -> ErrorStep:
    return ErrorStep(kind=kind, retryable=retryable, mode=mode)


class ModelHolder:
    def __init__(self) -> None:
        self.model = FakeAgentModel()

    def factory(self, mode, settings):
        return self.model


HOLDER = ModelHolder()
app.dependency_overrides[intake_api.get_model_factory] = lambda: HOLDER.factory


class _NoNetworkClient:
    """Stands in for google.genai.Client in every test; any call is a test bug, never a request."""

    def __init__(self, **kwargs) -> None:
        raise AssertionError("tests never construct a real Gemini client; install a fake on gemini.Client")


@pytest.fixture(scope="session", autouse=True)
def _no_key_for_the_session():
    # Another module's load_dotenv() may have re-read a .env after collection: drop the key again for
    # the whole session. The value is never read, compared or printed.
    os.environ.pop("GEMINI_API_KEY", None)
    yield
    os.environ.pop("GEMINI_API_KEY", None)


@pytest.fixture(autouse=True)
def _never_the_live_api(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert "GEMINI_API_KEY" not in os.environ
    monkeypatch.setattr(gemini, "Client", _NoNetworkClient)


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake(monkeypatch) -> FakeAgentModel:
    HOLDER.model = FakeAgentModel()
    monkeypatch.setattr(budget, "RETRY_DELAY_S", 0.0)  # the retry is still taken; the wait is not
    return HOLDER.model


@pytest.fixture
def db_conn():
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        yield conn


def new_key() -> str:
    return str(uuid.uuid4())


def create_session(client: TestClient, language: str = "ES", scenario_context_id: str | None = None) -> dict:
    body = {"language": language}
    if scenario_context_id:
        body["scenarioContextId"] = scenario_context_id
    r = client.post(f"{API}/intake-sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def turn(client: TestClient, session_id: str, text_: str, key: str | None = None):
    return client.post(
        f"{API}/intake-sessions/{session_id}/turns", json={"text": text_}, headers={"Idempotency-Key": key or new_key()}
    )


def purge_session(conn, session_id: str) -> None:
    """Delete what a session committed through the app's pool: events, handoff pairs and decisions,
    the intake record, then the session (turns and tool calls cascade). Test database only."""
    sid = uuid.UUID(session_id)
    pairs = [r[0] for r in conn.execute(text("SELECT id FROM candidate_pair WHERE intake_session_id = :s"), {"s": sid})]
    intake = conn.execute(text("SELECT intake_record_id FROM intake_session WHERE id = :s"), {"s": sid}).scalar()
    conn.execute(
        text("DELETE FROM event_log WHERE intake_session_id = :s OR pair_id = ANY(:p)"), {"s": sid, "p": pairs}
    )
    conn.execute(
        text("DELETE FROM not_a_match WHERE decision_id IN (SELECT id FROM match_decision WHERE pair_id = ANY(:p))"),
        {"p": pairs},
    )
    conn.execute(text("DELETE FROM match_decision WHERE pair_id = ANY(:p)"), {"p": pairs})
    conn.execute(text("DELETE FROM candidate_pair WHERE id = ANY(:p)"), {"p": pairs})
    conn.execute(text("DELETE FROM intake_session WHERE id = :s"), {"s": sid})
    if intake is not None:
        conn.execute(text("DELETE FROM source_record WHERE id = :r"), {"r": intake})


def purge_records(conn, record_ids) -> None:
    ids = list(record_ids)
    if ids:
        conn.execute(text("DELETE FROM source_record WHERE id = ANY(:ids)"), {"ids": ids})


@pytest.fixture
def cleanup(db_conn):
    """Collects session ids and seeded record ids to purge after the test."""
    sessions: list[str] = []
    records: list = []
    yield sessions, records
    for sid in sessions:
        purge_session(db_conn, sid)
    purge_records(db_conn, records)
