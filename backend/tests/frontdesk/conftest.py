"""Route-level fixtures for the FrontDesk replay tests: the app against the lane's test database,
the hero's Clinic record seeded the way ingest writes it, and per-session cleanup.

The test database name must contain ``test``; the dev database is refused.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

TEST_URL = os.environ.get(
    "CHECKMATE_TEST_DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "postgresql://checkmate:checkmate@127.0.0.1:5432/checkmate_test_q1_4"),
)
if "test" not in TEST_URL.rsplit("/", 1)[-1]:
    raise SystemExit(
        f"refusing to run FrontDesk route tests against a non-test database: {TEST_URL.rsplit('/', 1)[-1]}"
    )

# The composition root reads DATABASE_URL at import; point it at the test database first.
os.environ["DATABASE_URL"] = TEST_URL
os.environ.setdefault("FRONTDESK_AGENT_MODE", "REPLAY")
os.environ["FRONTDESK_REPLAY_PACING"] = "0"  # transcript latencies are cosmetic; never sleep in tests

from backend.app.main import app, engine
from backend.tests.conftest import purge
from backend.tests.policy.seed import insert_record
from contracts.models.common import SourceKind

API = "/api/v1"

# The hero's Clinic record exactly as hero.json on origin/main renders it (ISO date for the seeder).
HERO_CLINIC_DEMOGRAPHICS = {
    "given_name": "Sofia",
    "family_name": "MesaLópez",
    "birth_date": "1964-05-16",
    "sex": "F",
    "phone": None,
    "address_line": "899 Sawayn Trafficway",
    "zip": "01915",
}


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def hero_clinic_record() -> Iterator[UUID]:
    """Commit the hero's Clinic record so the gate finds it by block key; purge it afterwards."""
    with engine.begin() as conn:
        rid = insert_record(
            conn,
            system="CLINIC_CSV",
            local_id="hero-clinic-q1-4",
            kind=SourceKind.CSV_ROW,
            demographics=HERO_CLINIC_DEMOGRAPHICS,
        )
    yield rid
    purge(engine, [rid])


def purge_intake_session(session_id: str) -> None:
    """Delete everything a FrontDesk session committed: events, handoff pairs and decisions, the
    intake record, and the session (tool calls and turns cascade)."""
    with engine.begin() as c:
        sid = UUID(session_id)
        pairs = [
            r[0] for r in c.execute(text("SELECT id FROM candidate_pair WHERE intake_session_id = :s"), {"s": sid})
        ]
        record = c.execute(text("SELECT intake_record_id FROM intake_session WHERE id = :s"), {"s": sid}).scalar()
        c.execute(
            text("DELETE FROM event_log WHERE intake_session_id = :s OR pair_id = ANY(:p)"), {"s": sid, "p": pairs}
        )
        c.execute(text("DELETE FROM match_decision WHERE pair_id = ANY(:p)"), {"p": pairs})
        c.execute(text("DELETE FROM candidate_pair WHERE id = ANY(:p)"), {"p": pairs})
        c.execute(text("DELETE FROM intake_session WHERE id = :s"), {"s": sid})
        if record is not None:
            c.execute(text("DELETE FROM entity_member WHERE source_record_id = :r"), {"r": record})
            c.execute(text("DELETE FROM source_record WHERE id = :r"), {"r": record})


@pytest.fixture
def intake_sessions() -> Iterator[list[str]]:
    """Collect session ids created in a test; purge them at the end."""
    created: list[str] = []
    yield created
    for sid in created:
        purge_intake_session(sid)
