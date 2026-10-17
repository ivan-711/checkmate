"""POST /sessions: reset. Truncate the state tables (never event_log), load the scenario,
append DEMO_RESET (architecture §4, §5, §9). Idempotent by natural keys: the same scenario
loads the same records with the same ids."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.api.common import current_thresholds, source_card
from backend.app.deps import EngineDep
from backend.app.errors import ApiError
from backend.app.openapi_meta import common_error_responses, error_responses
from backend.events.writer import write_event
from backend.match.seam import MatchCore, resolve_core
from backend.scenarios.loader import ScenarioNotFound, load_scenario
from contracts.models.common import ActorType, ErrorCode, EventType
from contracts.models.events import Versions
from contracts.models.records import SourceCard
from contracts.models.sessions import CreateSessionRequest, SessionResponse
from contracts.version import API_PREFIX

router = APIRouter(prefix=API_PREFIX, tags=["core"])

# The demo state a reset clears, in one statement so foreign keys need no CASCADE.
# event_log (audit), schema_migration, threshold_set (config), demo_session (restore
# snapshots) and eval_* (evaluation history) are kept.
STATE_TABLES = (
    "source_record",
    "normalized_record",
    "block_key",
    "candidate_pair",
    "match_decision",
    "not_a_match",
    "entity",
    "entity_member",
    "safety_alert",
    "idempotency_record",
    "intake_session",
    "intake_turn",
    "agent_tool_call",
    "intake_history_item",
)
_CLEAR_STATE = text("TRUNCATE TABLE " + ", ".join(STATE_TABLES))
_SESSION_COLUMNS = "id, scenario_id, scorer_version, threshold_set_id, snapshot, previous_session_id, created_at"
_LAST_SESSION = text(f"SELECT {_SESSION_COLUMNS} FROM demo_session ORDER BY created_at DESC, id DESC LIMIT 1")
_SESSION_BY_ID = text(f"SELECT {_SESSION_COLUMNS} FROM demo_session WHERE id = :id")
_INSERT_SESSION = text(
    "INSERT INTO demo_session (id, scenario_id, scorer_version, threshold_set_id, snapshot, previous_session_id, "
    "created_at) VALUES (:id, :scenario_id, :scorer_version, :threshold_set_id, CAST(:snapshot AS jsonb), "
    ":previous_session_id, :created_at)"
)
_EXISTING_RECORDS = text("SELECT id FROM source_record WHERE id = ANY(:ids)")

# demo_session.snapshot keys this lane writes; a restore lane may add its own beside them.
SHOWCASE_IDS_KEY, HERO_PROVISIONAL_KEY, HERO_CONSTRUCTED_FLOOR_KEY = (
    "showcaseRecordIds",
    "heroProvisional",
    "heroConstructedFloor",
)
_INSERT_SOURCE = text(
    "INSERT INTO source_record (id, source_system, source_local_id, kind, raw_payload, payload_sha256, is_constructed, "
    "ingested_at) VALUES (:id, :source_system, :source_local_id, :kind, CAST(:raw_payload AS jsonb), :payload_sha256, "
    ":is_constructed, :ingested_at) ON CONFLICT (source_system, source_local_id) DO NOTHING"
)
_INSERT_NORMALIZED = text(
    "INSERT INTO normalized_record (record_id, given_name, family_name, given_name_folded, family_name_folded, "
    "birth_date, birth_year, birth_month, birth_day, sex, phone_e164, address_line, zip5) VALUES (:record_id, "
    ":given_name, :family_name, :given_name_folded, :family_name_folded, :birth_date, :birth_year, :birth_month, "
    ":birth_day, :sex, :phone_e164, :address_line, :zip5) ON CONFLICT (record_id) DO NOTHING"
)
_INSERT_BLOCK_KEY = text(
    "INSERT INTO block_key (key_type, key_value, record_id) VALUES (:key_type, :key_value, :record_id) "
    "ON CONFLICT DO NOTHING"
)


def insert_source_card(conn: Connection, card: SourceCard, core: MatchCore) -> None:
    """S1 + S2 + block keys for one record, in the caller's transaction (architecture §4)."""
    rec, norm = card.record, card.normalized
    conn.execute(
        _INSERT_SOURCE,
        {
            "id": rec.id,
            "source_system": rec.source_system,
            "source_local_id": rec.source_local_id,
            "kind": rec.kind.value,
            "raw_payload": json.dumps(rec.raw_payload or {}),
            "payload_sha256": rec.payload_sha256,
            "is_constructed": rec.is_constructed,
            "ingested_at": rec.ingested_at,
        },
    )
    bd = norm.birth_date
    conn.execute(
        _INSERT_NORMALIZED,
        {
            "record_id": rec.id,
            "given_name": norm.given_name,
            "family_name": norm.family_name,
            "given_name_folded": norm.given_name_folded,
            "family_name_folded": norm.family_name_folded,
            "birth_date": bd,
            "birth_year": bd.year if bd else None,
            "birth_month": bd.month if bd else None,
            "birth_day": bd.day if bd else None,
            "sex": norm.sex,
            "phone_e164": norm.phone_e164,
            "address_line": norm.address_line,
            "zip5": norm.zip5,
        },
    )
    for key in core.block_keys(norm):
        conn.execute(_INSERT_BLOCK_KEY, {"key_type": key.key_type, "key_value": key.key_value, "record_id": rec.id})


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=201,
    responses=error_responses(ErrorCode.NOT_FOUND) | common_error_responses(),
    description="Lane W1/W3a. Reset: truncate state, load the scenario, append DEMO_RESET.",
)
def create_session(body: CreateSessionRequest, engine: EngineDep) -> SessionResponse:
    try:
        scenario = load_scenario(body.scenario_id)
    except ScenarioNotFound:
        raise ApiError(ErrorCode.NOT_FOUND, "unknown scenario") from None
    core = resolve_core()
    session_id = uuid.uuid4()
    created_at = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(_CLEAR_STATE)
        previous = conn.execute(_LAST_SESSION).one_or_none()
        previous_id = previous.id if previous else None
        thresholds = current_thresholds(conn)
        for card in scenario.sources:
            insert_source_card(conn, card, core)
        conn.execute(
            _INSERT_SESSION,
            {
                "id": session_id,
                "scenario_id": scenario.scenario_id,
                "scorer_version": core.scorer_version,
                "threshold_set_id": thresholds.threshold_set_id,
                "snapshot": json.dumps(
                    {
                        SHOWCASE_IDS_KEY: [str(c.record.id) for c in scenario.showcase],
                        HERO_PROVISIONAL_KEY: scenario.hero_provisional,
                        HERO_CONSTRUCTED_FLOOR_KEY: scenario.hero_constructed_floor,
                    }
                ),
                "previous_session_id": previous_id,
                "created_at": created_at,
            },
        )
        write_event(
            conn,
            event_type=EventType.DEMO_RESET,
            actor="system:reset",
            actor_type=ActorType.SYSTEM,
            versions=Versions(scorer_version=core.scorer_version, threshold_set_id=thresholds.threshold_set_id),
            payload={
                "session_id": str(session_id),
                "scenario_id": scenario.scenario_id,
                "records": len(scenario.sources),
                "previous_session_id": str(previous_id) if previous_id else None,
            },
        )
        # Built from what was just stored, the same way GET /sessions/current builds it.
        return session_response(conn, conn.execute(_SESSION_BY_ID, {"id": session_id}).one())


def session_response(conn: Connection, row) -> SessionResponse:
    """A demo_session row as the contract's SessionResponse: the showcase cards read back from
    source_record (raw payload left out), in the order the reset stored them."""
    snapshot = row.snapshot or {}
    wanted = [UUID(i) for i in snapshot.get(SHOWCASE_IDS_KEY, [])]
    present = {r.id for r in conn.execute(_EXISTING_RECORDS, {"ids": wanted})} if wanted else set()
    return SessionResponse(
        id=row.id,
        scenario_id=row.scenario_id,
        scorer_version=row.scorer_version,
        threshold_set_id=row.threshold_set_id,
        created_at=row.created_at,
        sources=[source_card(conn, i) for i in wanted if i in present],
        hero_provisional=bool(snapshot.get(HERO_PROVISIONAL_KEY, True)),
        hero_constructed_floor=bool(snapshot.get(HERO_CONSTRUCTED_FLOOR_KEY, False)),
        previous_session_id=row.previous_session_id,
    )


@router.get(
    "/sessions/current",
    response_model=SessionResponse,
    responses=error_responses(ErrorCode.NOT_FOUND) | common_error_responses(),
    description="Lane W3a (additive). The current demo session, so a reloaded page rebinds the hero "
    "without a reset; 404 before the first reset.",
)
def get_current_session(engine: EngineDep) -> SessionResponse:
    with engine.connect() as conn:
        row = conn.execute(_LAST_SESSION).one_or_none()
        if row is None:
            raise ApiError(ErrorCode.NOT_FOUND, "no demo session yet: reset first")
        return session_response(conn, row)
