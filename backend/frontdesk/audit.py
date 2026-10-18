"""FrontDesk event rows (ADR-016 §6): ``AGENT_TOOL_CALLED``, ``INTAKE_STARTED``, ``AGENT_TURN_DEGRADED``.

Sibling of ``backend.events.writer.write_event`` with its own bound INSERT, because the intake
columns (``intake_session_id`` ... ``effect_status``) are not in that writer's statement. Same
rule on ``payload``: validated tool arguments or enums and ids, never free text. The string cap
is the longest field the tool schemas allow (``attach_history`` text, 200 chars), so a validated
argument always passes and a transcript line never does.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.app import request_context
from backend.events.writer import PayloadNotStructured
from contracts.models.common import ActorType, Band, EntryPoint, EventType, Mode
from contracts.models.events import Versions
from contracts.models.intake import AgentMode

AGENT_ACTOR = "agent:frontdesk"
MAX_ARG_STRING = 200  # attach_history text/evidenceQuote maxLength; the longest validated argument

_INSERT = text(
    "INSERT INTO event_log (ts, event_id, event_type, request_id, entry_point, entity_id, pair_id, decision_id, "
    "actor, actor_type, band, outcome, latency_ms, mode, versions, payload, intake_session_id, tool_call_id, "
    "tool_name, gate_outcome, reason_code, evidence_ids, evidence_snapshot, client_request_id, effect_status) "
    "VALUES (:ts, :event_id, :event_type, :request_id, :entry_point, :entity_id, :pair_id, :decision_id, "
    ":actor, :actor_type, :band, :outcome, :latency_ms, :mode, CAST(:versions AS jsonb), CAST(:payload AS jsonb), "
    ":intake_session_id, :tool_call_id, :tool_name, :gate_outcome, :reason_code, :evidence_ids, "
    "CAST(:evidence_snapshot AS jsonb), :client_request_id, :effect_status)"
)


def check_structured(value, path: str = "payload") -> None:
    if isinstance(value, str):
        if len(value) > MAX_ARG_STRING:
            raise PayloadNotStructured(f"{path}: string of {len(value)} chars; payloads carry validated args only")
    elif isinstance(value, dict):
        for k, v in value.items():
            check_structured(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            check_structured(v, f"{path}[{i}]")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise PayloadNotStructured(f"{path}: unsupported type {type(value).__name__}")


def event_mode(agent_mode: AgentMode) -> Mode:
    """Where the model step came from: LIVE or REPLAY on the event row."""
    return Mode.LIVE if agent_mode == AgentMode.LIVE else Mode.REPLAY


def write_agent_event(
    conn: Connection,
    *,
    event_type: EventType,
    intake_session_id: UUID,
    mode: Mode,
    actor: str = AGENT_ACTOR,
    actor_type: ActorType = ActorType.AGENT,
    entry_point: EntryPoint = EntryPoint.AGENT,
    band: Band | None = None,
    outcome: str | None = None,
    latency_ms: int | None = None,
    versions: Versions | None = None,
    payload: dict | None = None,
    tool_call_id: UUID | None = None,
    tool_name: str | None = None,
    gate_outcome: str | None = None,
    reason_code: str | None = None,
    evidence_ids: list[UUID] | None = None,
    evidence_snapshot: dict | None = None,
    client_request_id: str | None = None,
    effect_status: str | None = None,
    pair_id: UUID | None = None,
    decision_id: UUID | None = None,
    entity_id: UUID | None = None,
) -> UUID:
    ctx = request_context.current()
    payload = payload or {}
    check_structured(payload)
    event_id = uuid.uuid4()
    conn.execute(
        _INSERT,
        {
            "ts": datetime.now(UTC),
            "event_id": event_id,
            "event_type": event_type.value,
            "request_id": ctx.request_id,
            "entry_point": entry_point.value,
            "entity_id": entity_id,
            "pair_id": pair_id,
            "decision_id": decision_id,
            "actor": actor,
            "actor_type": actor_type.value,
            "band": Band(band).value if band else None,
            "outcome": outcome,
            "latency_ms": ctx.elapsed_ms() if latency_ms is None else latency_ms,
            "mode": mode.value,
            "versions": json.dumps((versions or Versions()).model_dump(by_alias=True, exclude_none=True)),
            "payload": json.dumps(payload, default=str),
            "intake_session_id": intake_session_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "gate_outcome": gate_outcome,
            "reason_code": reason_code,
            "evidence_ids": list(evidence_ids or []),
            "evidence_snapshot": None if evidence_snapshot is None else json.dumps(evidence_snapshot, default=str),
            "client_request_id": client_request_id,
            "effect_status": effect_status,
        },
    )
    return event_id
