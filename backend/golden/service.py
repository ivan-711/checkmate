"""Read side: entity with its read-time golden record, timeline page, alerts page.

Every query matches how the screen reads the data: one entity, its members, their
normalized rows and raw payloads. Nothing is cached (ADR-014).
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.golden.survivorship import MemberDemographics, golden_demographics, golden_union
from backend.golden.timeline import BadCursor, timeline_events
from backend.golden.timeline import page as timeline_page
from backend.rule.resources import MemberResources, parse_member
from contracts.models.alerts import AlertStatus, AlertTier, Citation, ResourceRef, SafetyAlert
from contracts.models.common import Crosswalk, Page
from contracts.models.entities import Entity, EntityMember, GoldenField, TimelineEvent

_MEMBERS = text(
    "SELECT sr.id, sr.source_system, sr.source_local_id, sr.kind, sr.raw_payload, sr.is_constructed, sr.ingested_at, "
    "nr.given_name, nr.family_name, nr.birth_date, nr.sex, nr.phone_e164, nr.address_line, nr.zip5 "
    "FROM entity_member em JOIN source_record sr ON sr.id = em.source_record_id "
    "LEFT JOIN normalized_record nr ON nr.record_id = sr.id "
    "WHERE em.entity_id = :entity_id ORDER BY sr.ingested_at, sr.id"
)
_ENTITY = text("SELECT id, version FROM entity WHERE id = :entity_id")
_ALERTS = text(
    "SELECT sa.id, sa.entity_id, sa.rule_id, sa.rule_version, sa.tier, sa.allergy_record_id, sa.allergy_resource_id, "
    "sa.order_record_id, sa.order_resource_id, sa.revealed_by_merge, sa.severity, sa.status, sa.card_text, sa.citation, "
    "sa.constructed_scenario, sa.identified_at, a.source_system AS allergy_system, o.source_system AS order_system "
    "FROM safety_alert sa JOIN source_record a ON a.id = sa.allergy_record_id "
    "JOIN source_record o ON o.id = sa.order_record_id "
    "WHERE (CAST(:entity_id AS uuid) IS NULL OR sa.entity_id = :entity_id) ORDER BY sa.identified_at, sa.id"
)


def _member_rows(conn: Connection, entity_id: UUID):
    return conn.execute(_MEMBERS, {"entity_id": entity_id}).mappings().all()


def _parse_rows(rows) -> list[MemberResources]:
    return [
        parse_member(
            source_record_id=r["id"],
            source_system=r["source_system"],
            source_local_id=r["source_local_id"],
            kind=r["kind"],
            is_constructed=r["is_constructed"],
            ingested_at=r["ingested_at"],
            raw_payload=r["raw_payload"],
        )
        for r in rows
    ]


def load_members(conn: Connection, entity_id: UUID) -> list[MemberResources]:
    return _parse_rows(_member_rows(conn, entity_id))


def entity_exists(conn: Connection, entity_id: UUID) -> bool:
    return conn.execute(_ENTITY, {"entity_id": entity_id}).first() is not None


def _demographics(rows) -> list[MemberDemographics]:
    return [
        MemberDemographics(
            source_system=r["source_system"],
            source_local_id=r["source_local_id"],
            ingested_at=r["ingested_at"],
            given_name=r["given_name"],
            family_name=r["family_name"],
            birth_date=r["birth_date"],
            sex=r["sex"],
            phone_e164=r["phone_e164"],
            address_line=r["address_line"],
            zip5=r["zip5"],
        )
        for r in rows
    ]


def clinical_union(members: Sequence[MemberResources]) -> list[GoldenField]:
    """Allergies and active orders as union golden values; the full list lives in the timeline."""
    allergies, orders = [], []
    for m in members:
        xw = Crosswalk(source_system=m.source_system, source_record_id=m.source_local_id)
        for a in m.allergies:
            if a.code:
                allergies.append(
                    (
                        {
                            "code": a.code.code,
                            "display": a.code.display,
                            "status": a.clinical_status,
                            "resourceId": a.ref.resource_id,
                        },
                        xw,
                    )
                )
        for o in m.orders:
            if o.code and o.status == "active":
                orders.append(
                    (
                        {
                            "code": o.code.code,
                            "display": o.code.display,
                            "status": o.status,
                            "resourceId": o.ref.resource_id,
                        },
                        xw,
                    )
                )
    return golden_union("allergy", allergies, per_resource=False) + golden_union(
        "activeMedicationOrder", orders, per_resource=True
    )


def read_entity(conn: Connection, entity_id: UUID) -> Entity | None:
    head = conn.execute(_ENTITY, {"entity_id": entity_id}).mappings().first()
    if head is None:
        return None
    rows = _member_rows(conn, entity_id)
    members = _parse_rows(rows)
    return Entity(
        id=head["id"],
        version=head["version"],
        members=[
            EntityMember(source_record_id=r["id"], source_system=r["source_system"], is_constructed=r["is_constructed"])
            for r in rows
        ],
        golden=golden_demographics(_demographics(rows)) + clinical_union(members),
        all_links_reviewer_approved=True,
    )


def read_timeline(conn: Connection, entity_id: UUID, limit: int, cursor: str | None) -> Page[TimelineEvent] | None:
    """None for an unknown entity; raises BadCursor for a cursor the server did not mint."""
    if not entity_exists(conn, entity_id):
        return None
    items, next_cursor = timeline_page(timeline_events(entity_id, load_members(conn, entity_id)), limit, cursor)
    return Page[TimelineEvent](items=items, next_cursor=next_cursor)


def _alert(r) -> SafetyAlert:
    return SafetyAlert(
        id=r["id"],
        entity_id=r["entity_id"],
        rule_id=r["rule_id"],
        rule_version=r["rule_version"],
        tier=AlertTier(r["tier"]),
        allergy_ref=ResourceRef(
            source_record_id=r["allergy_record_id"],
            source_system=r["allergy_system"],
            resource_id=r["allergy_resource_id"],
        ),
        order_ref=ResourceRef(
            source_record_id=r["order_record_id"], source_system=r["order_system"], resource_id=r["order_resource_id"]
        ),
        revealed_by_merge=r["revealed_by_merge"],
        severity=r["severity"],
        status=AlertStatus(r["status"]),
        card_text=r["card_text"],
        citation=Citation(**r["citation"]) if r["citation"] else None,
        constructed_scenario=r["constructed_scenario"],
        identified_at=r["identified_at"],
    )


def read_alerts(conn: Connection, entity_id: UUID | None, *, status: AlertStatus | None = None) -> list[SafetyAlert]:
    """Alerts of one entity, or of every entity when ``entity_id`` is None (demo scale; paged in memory)."""
    rows = conn.execute(_ALERTS, {"entity_id": entity_id}).mappings().all()
    alerts = [_alert(r) for r in rows]
    return [a for a in alerts if status is None or a.status == status]


def _alert_key(alert: SafetyAlert) -> tuple[datetime, str]:
    return (alert.identified_at, str(alert.id))


def _encode_alert_cursor(alert: SafetyAlert) -> str:
    return base64.urlsafe_b64encode(f"{alert.identified_at.isoformat()}|{alert.id}".encode()).decode()


def _decode_alert_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        ts, alert_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        when = datetime.fromisoformat(ts)
        UUID(alert_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise BadCursor("cursor is not one this endpoint issued") from exc
    if when.tzinfo is None:
        raise BadCursor("cursor is not one this endpoint issued")
    return (when, alert_id)


def alert_page(alerts: Sequence[SafetyAlert], limit: int, cursor: str | None) -> Page[SafetyAlert]:
    """Keyset on (identified_at, id): a cursor stays valid when the alert it names is retracted later."""
    after = _decode_alert_cursor(cursor) if cursor else None
    remaining = [a for a in alerts if after is None or _alert_key(a) > after]
    items = remaining[:limit]
    next_cursor = _encode_alert_cursor(items[-1]) if len(remaining) > limit and items else None
    return Page[SafetyAlert](items=items, next_cursor=next_cursor)
