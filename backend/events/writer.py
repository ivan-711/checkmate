"""Append one ``event_log`` row per action, inside the caller's transaction (architecture §4, §11, §16).

Every lane writes its events through ``write_event``. The row is committed with the state
change it describes, so an event never exists without its effect and vice versa.
``request_id`` and ``latency_ms`` come from the request context the middleware bound;
``mode`` and ``entry_point`` too. ``payload`` carries identifiers, counts and enums only:
never free text (notes), full records or keys. A string longer than ``MAX_PAYLOAD_STRING``
is refused so a note cannot slip in by accident.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.app import request_context
from contracts.models.common import ActorType, Band, EventType
from contracts.models.events import Versions

MAX_PAYLOAD_STRING = 64  # a uuid is 36 chars, an enum under 40; a note is never this short

_INSERT = text(
    "INSERT INTO event_log (ts, event_id, event_type, request_id, run_id, entry_point, entity_id, pair_id, "
    "decision_id, actor, actor_type, band, outcome, latency_ms, mode, versions, payload, reason_code) "
    "VALUES (:ts, :event_id, :event_type, :request_id, :run_id, :entry_point, :entity_id, :pair_id, "
    ":decision_id, :actor, :actor_type, :band, :outcome, :latency_ms, :mode, CAST(:versions AS jsonb), "
    "CAST(:payload AS jsonb), :reason_code)"
)


class PayloadNotStructured(ValueError):
    """The payload carried something that looks like free text."""


def _check_structured(value, path: str = "payload") -> None:
    if isinstance(value, str):
        if len(value) > MAX_PAYLOAD_STRING:
            raise PayloadNotStructured(f"{path}: string of {len(value)} chars; payloads carry ids and enums only")
    elif isinstance(value, dict):
        for k, v in value.items():
            _check_structured(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _check_structured(v, f"{path}[{i}]")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise PayloadNotStructured(f"{path}: unsupported type {type(value).__name__}")


def write_event(
    conn: Connection,
    *,
    event_type: EventType,
    actor: str,
    actor_type: ActorType,
    ctx: request_context.RequestContext | None = None,
    run_id: UUID | None = None,
    entity_id: UUID | None = None,
    pair_id: UUID | None = None,
    decision_id: UUID | None = None,
    band: Band | None = None,
    outcome: str | None = None,
    reason_code: str | None = None,
    versions: Versions | None = None,
    payload: dict | None = None,
) -> UUID:
    """Insert one event row on ``conn`` and return its event id. ``ctx`` defaults to the
    request context bound by the middleware (a CLI context outside a request)."""
    ctx = ctx or request_context.current()
    payload = payload or {}
    _check_structured(payload)
    event_id = uuid.uuid4()
    conn.execute(
        _INSERT,
        {
            "ts": datetime.now(UTC),
            "event_id": event_id,
            "event_type": event_type.value,
            "request_id": ctx.request_id,
            "run_id": run_id,
            "entry_point": ctx.entry_point.value,
            "entity_id": entity_id,
            "pair_id": pair_id,
            "decision_id": decision_id,
            "actor": actor,
            "actor_type": actor_type.value,
            "band": band.value if band else None,
            "outcome": outcome,
            "latency_ms": ctx.elapsed_ms(),
            "mode": ctx.mode.value,
            "versions": json.dumps((versions or Versions()).model_dump(by_alias=True, exclude_none=True)),
            "payload": json.dumps(payload, default=str),
            "reason_code": reason_code,
        },
    )
    return event_id
