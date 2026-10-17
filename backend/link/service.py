"""Link seam: what the review route calls after a decision is written (architecture §7, §8, §10).

STAND-IN for lane W3b. W3b replaces the bodies (union-find over LINKED edges, read-time
golden record, rule BL-AMOX-01) and keeps these signatures, which the review route and
the evidence view are coded against:

    apply_approve(conn, pair_id, decision_id) -> (Entity, list[SafetyAlert])
    apply_reject(conn, pair_id, decision_id) -> None
    preview_approve(conn, pair_id) -> MergePreview
    entity_for_pair(conn, pair_id) -> Entity | None     (the entity a LINKED pair belongs to)
    alerts_for_entity(conn, entity_id) -> list[SafetyAlert]  (its current, PRELIMINARY alerts; read only)

All three run inside the caller's transaction on ``conn`` (a SQLAlchemy Connection); the
pair row is already locked ``FOR UPDATE`` by the route. Events the seam writes
(ENTITY_MERGED, ALERT_RAISED) go through ``backend.events.writer.write_event`` on the same
connection; the request context is bound, so no ``ctx`` argument is needed.

The stand-in writes no entity rows and raises no alerts: it returns a single-member entity
whose id is derived from the pair id, so repeated calls are stable.
"""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from contracts.models.alerts import SafetyAlert
from contracts.models.entities import Entity, EntityMember
from contracts.models.pairs import MergePreview

_STANDIN_NAMESPACE = uuid.UUID("c0a6d2b0-2f7e-4b1e-9d6a-5a0f5b9a3f01")  # stand-in only; W3b assigns real ids

_PAIR_RECORD_A = text(
    "SELECT sr.id, sr.source_system, sr.is_constructed FROM candidate_pair cp "
    "JOIN source_record sr ON sr.id = cp.record_a_id WHERE cp.id = :pair_id"
)


def _standin_entity(conn: Connection, pair_id: UUID) -> Entity:
    row = conn.execute(_PAIR_RECORD_A, {"pair_id": pair_id}).one()
    return Entity(
        id=uuid.uuid5(_STANDIN_NAMESPACE, str(pair_id)),
        version=1,
        members=[
            EntityMember(source_record_id=row.id, source_system=row.source_system, is_constructed=row.is_constructed)
        ],
        golden=[],
    )


def apply_approve(conn: Connection, pair_id: UUID, decision_id: UUID) -> tuple[Entity, list[SafetyAlert]]:
    """STAND-IN (W3b replaces): no entity rows, no rule evaluation, no alerts."""
    return _standin_entity(conn, pair_id), []


def apply_reject(conn: Connection, pair_id: UUID, decision_id: UUID) -> None:
    """STAND-IN (W3b replaces): nothing to unlink before any entity exists."""


def entity_for_pair(conn: Connection, pair_id: UUID) -> Entity | None:
    """STAND-IN (W3b replaces with an entity_member lookup): the entity a LINKED pair belongs to."""
    return _standin_entity(conn, pair_id)


def alerts_for_entity(conn: Connection, entity_id: UUID) -> list[SafetyAlert]:
    """STAND-IN (W3b replaces, e.g. with golden.read_alerts(conn, entity_id, status=PRELIMINARY)): the
    entity's current alerts, read only. The stand-in raises none, so there are none to read."""
    return []


def preview_approve(conn: Connection, pair_id: UUID) -> MergePreview:
    """STAND-IN (W3b replaces): the entity the approve would produce and whether the rule would fire."""
    entity = _standin_entity(conn, pair_id)
    return MergePreview(
        entity_id_if_approved=entity.id, member_count_if_approved=len(entity.members), alert_would_fire=False
    )
