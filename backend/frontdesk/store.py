"""Bound SQL over the FrontDesk tables ``intake_session``, ``intake_turn`` and ``agent_tool_call``.

Chart-store rows (source records, pairs, decisions, history) are written only through
``backend.chart_store.writes`` from the executor; this module never touches them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Row

from contracts.models.intake import AgentMode, TurnStatus
from contracts.models.policy import Language

_INSERT_SESSION = text(
    "INSERT INTO intake_session (id, language, agent_mode, scenario_context_id, prompt_version, tool_schema_version, "
    "model_id) VALUES (:id, :language, :agent_mode, :scenario_context_id, :prompt_version, :tool_schema_version, "
    ":model_id)"
)
_SESSION = text(
    "SELECT id, created_at, language, agent_mode, scenario_context_id, prompt_version, tool_schema_version, model_id, "
    "intake_record_id, intake_args_sha256, closed_at FROM intake_session WHERE id = :id"
)
_SESSION_FOR_UPDATE = text(f"{_SESSION.text} FOR UPDATE")
_CLOSE_SESSION = text("UPDATE intake_session SET closed_at = now() WHERE id = :id AND closed_at IS NULL")
_TURNS = text(
    "SELECT session_id, turn_index, client_request_id, request_sha256, status, claimed_at, completed_at, user_text, "
    "response, degraded FROM intake_turn WHERE session_id = :session_id ORDER BY turn_index"
)
_TURN_BY_KEY = text(
    "SELECT session_id, turn_index, client_request_id, request_sha256, status, claimed_at, completed_at, user_text, "
    "response, degraded FROM intake_turn WHERE session_id = :session_id AND client_request_id = :key"
)
_EXPIRE_LEASES = text(
    "UPDATE intake_turn SET status = 'FAILED', completed_at = now() WHERE session_id = :session_id "
    "AND status = 'IN_PROGRESS' AND claimed_at < now() - make_interval(secs => :lease_s)"
)
_RECLAIM_FAILED = text(
    "UPDATE intake_turn SET status = 'IN_PROGRESS', claimed_at = now(), completed_at = NULL, response = NULL, "
    "degraded = NULL WHERE session_id = :session_id AND client_request_id = :key AND status = 'FAILED'"
)
_CLAIM_TURN = text(
    "INSERT INTO intake_turn (session_id, turn_index, client_request_id, request_sha256, status, user_text) "
    "VALUES (:session_id, :turn_index, :key, :sha, 'IN_PROGRESS', :user_text)"
)
_NEXT_TURN_INDEX = text("SELECT coalesce(max(turn_index) + 1, 0) FROM intake_turn WHERE session_id = :session_id")
_COMPLETE_TURN = text(
    "UPDATE intake_turn SET status = :status, completed_at = now(), response = CAST(:response AS jsonb), "
    "degraded = :degraded WHERE session_id = :session_id AND turn_index = :turn_index"
)
_TOOL_CALLS = text(
    "SELECT id, session_id, turn_index, step_index, tool_name, args, args_sha256, grounding_ok, gate_outcome, "
    "reason_code, evidence_ids, evidence_snapshot, effect_key, effect_status, effect_ref, policy_version, latency_ms, "
    "created_at FROM agent_tool_call WHERE session_id = :session_id ORDER BY turn_index, step_index"
)
_NEXT_STEP_INDEX = text(
    "SELECT coalesce(max(step_index) + 1, 0) FROM agent_tool_call WHERE session_id = :session_id "
    "AND turn_index = :turn_index"
)
_IDENTICAL_CALLS = text(
    "SELECT count(*) FROM agent_tool_call WHERE session_id = :session_id AND tool_name = :tool_name "
    "AND args_sha256 = :args_sha256"
)
_EFFECT_BY_KEY = text("SELECT effect_status, effect_ref FROM agent_tool_call WHERE effect_key = :effect_key")
_INSERT_TOOL_CALL = text(
    "INSERT INTO agent_tool_call (id, session_id, turn_index, step_index, tool_name, args, args_sha256, grounding_ok, "
    "gate_outcome, reason_code, evidence_ids, evidence_snapshot, effect_key, effect_status, effect_ref, policy_version, "
    "latency_ms) VALUES (:id, :session_id, :turn_index, :step_index, :tool_name, CAST(:args AS jsonb), :args_sha256, "
    ":grounding_ok, :gate_outcome, :reason_code, :evidence_ids, CAST(:evidence_snapshot AS jsonb), :effect_key, "
    ":effect_status, :effect_ref, :policy_version, :latency_ms)"
)
_HAS_EFFECT_KEY = text("SELECT 1 FROM agent_tool_call WHERE effect_key = :effect_key LIMIT 1")


@dataclass(frozen=True)
class SessionRow:
    id: UUID
    created_at: datetime
    language: Language
    agent_mode: AgentMode
    scenario_context_id: str | None
    prompt_version: str
    tool_schema_version: str
    model_id: str | None
    intake_record_id: UUID | None
    intake_args_sha256: str | None
    closed_at: datetime | None

    @property
    def closed(self) -> bool:
        return self.closed_at is not None


def _session(row: Row) -> SessionRow:
    return SessionRow(
        id=row.id,
        created_at=row.created_at,
        language=Language(row.language),
        agent_mode=AgentMode(row.agent_mode),
        scenario_context_id=row.scenario_context_id,
        prompt_version=row.prompt_version,
        tool_schema_version=row.tool_schema_version,
        model_id=row.model_id,
        intake_record_id=row.intake_record_id,
        intake_args_sha256=row.intake_args_sha256,
        closed_at=row.closed_at,
    )


def insert_session(
    conn: Connection,
    *,
    session_id: UUID,
    language: Language,
    agent_mode: AgentMode,
    scenario_context_id: str | None,
    prompt_version: str,
    tool_schema_version: str,
    model_id: str | None,
) -> None:
    conn.execute(
        _INSERT_SESSION,
        {
            "id": session_id,
            "language": language.value,
            "agent_mode": agent_mode.value,
            "scenario_context_id": scenario_context_id,
            "prompt_version": prompt_version,
            "tool_schema_version": tool_schema_version,
            "model_id": model_id,
        },
    )


def read_session(conn: Connection, session_id: UUID, *, for_update: bool = False) -> SessionRow | None:
    row = conn.execute(_SESSION_FOR_UPDATE if for_update else _SESSION, {"id": session_id}).one_or_none()
    return None if row is None else _session(row)


def close_session(conn: Connection, session_id: UUID) -> None:
    conn.execute(_CLOSE_SESSION, {"id": session_id})


def read_turns(conn: Connection, session_id: UUID) -> list[Row]:
    return list(conn.execute(_TURNS, {"session_id": session_id}))


def turn_by_key(conn: Connection, session_id: UUID, key: str) -> Row | None:
    return conn.execute(_TURN_BY_KEY, {"session_id": session_id, "key": key}).one_or_none()


def expire_leases(conn: Connection, session_id: UUID, lease_s: int) -> int:
    return conn.execute(_EXPIRE_LEASES, {"session_id": session_id, "lease_s": lease_s}).rowcount


def reclaim_failed(conn: Connection, session_id: UUID, key: str) -> int:
    return conn.execute(_RECLAIM_FAILED, {"session_id": session_id, "key": key}).rowcount


def next_turn_index(conn: Connection, session_id: UUID) -> int:
    return int(conn.execute(_NEXT_TURN_INDEX, {"session_id": session_id}).scalar_one())


def claim_turn(conn: Connection, session_id: UUID, turn_index: int, key: str, sha: str, user_text: str) -> None:
    conn.execute(
        _CLAIM_TURN,
        {"session_id": session_id, "turn_index": turn_index, "key": key, "sha": sha, "user_text": user_text},
    )


def complete_turn(
    conn: Connection, session_id: UUID, turn_index: int, status: TurnStatus, response: dict | None, degraded: str | None
) -> None:
    conn.execute(
        _COMPLETE_TURN,
        {
            "session_id": session_id,
            "turn_index": turn_index,
            "status": status.value,
            "response": None if response is None else json.dumps(response),
            "degraded": degraded,
        },
    )


def read_tool_calls(conn: Connection, session_id: UUID) -> list[Row]:
    return list(conn.execute(_TOOL_CALLS, {"session_id": session_id}))


def next_step_index(conn: Connection, session_id: UUID, turn_index: int) -> int:
    """A re-claimed turn continues its step numbering: audit rows from the failed run stay."""
    return int(conn.execute(_NEXT_STEP_INDEX, {"session_id": session_id, "turn_index": turn_index}).scalar_one())


def identical_call_count(conn: Connection, session_id: UUID, tool_name: str, args_sha256: str) -> int:
    return int(
        conn.execute(
            _IDENTICAL_CALLS, {"session_id": session_id, "tool_name": tool_name, "args_sha256": args_sha256}
        ).scalar_one()
    )


def effect_by_key(conn: Connection, effect_key: str) -> Row | None:
    return conn.execute(_EFFECT_BY_KEY, {"effect_key": effect_key}).one_or_none()


def has_effect_key(conn: Connection, effect_key: str) -> bool:
    return conn.execute(_HAS_EFFECT_KEY, {"effect_key": effect_key}).one_or_none() is not None


def insert_tool_call(conn: Connection, row: dict) -> None:
    conn.execute(
        _INSERT_TOOL_CALL,
        {
            **row,
            "args": None if row["args"] is None else json.dumps(row["args"]),
            "evidence_snapshot": json.dumps(row["evidence_snapshot"], default=str),
        },
    )
