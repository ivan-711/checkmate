"""Minimal event_log writer for the link lane.

W3a owns the full writer (backend/events). Until it lands, this one writes the same row
shape with bound parameters so the merge only has to swap the import.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from contracts.models.common import ActorType, EntryPoint, EventType, Mode


@dataclass(frozen=True)
class EventContext:
    """Who is acting and through which door; the service copies actor fields from the decision row."""

    actor: str
    actor_type: ActorType
    entry_point: EntryPoint = EntryPoint.API
    mode: Mode = Mode.LOCAL
    request_id: str | None = None


_INSERT = text(
    "INSERT INTO event_log (event_id, event_type, request_id, entry_point, entity_id, pair_id, decision_id, "
    "actor, actor_type, outcome, mode, versions, payload) "
    "VALUES (:event_id, :event_type, :request_id, :entry_point, :entity_id, :pair_id, :decision_id, "
    ":actor, :actor_type, :outcome, :mode, CAST(:versions AS jsonb), CAST(:payload AS jsonb))"
)


def write_event(conn: Connection, ctx: EventContext, event_type: EventType, *, entity_id: UUID | None = None,
                pair_id: UUID | None = None, decision_id: UUID | None = None, outcome: str | None = None,
                payload: dict | None = None, versions: dict | None = None) -> UUID:
    event_id = uuid4()
    conn.execute(_INSERT, {
        "event_id": event_id, "event_type": event_type.value, "request_id": ctx.request_id,
        "entry_point": ctx.entry_point.value, "entity_id": entity_id, "pair_id": pair_id, "decision_id": decision_id,
        "actor": ctx.actor, "actor_type": ctx.actor_type.value, "outcome": outcome, "mode": ctx.mode.value,
        "versions": json.dumps(versions or {}, default=str), "payload": json.dumps(payload or {}, default=str),
    })
    return event_id
