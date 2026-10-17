"""Timeline events from member resources (architecture S10). Each keeps its source. Pure."""
from __future__ import annotations

import base64
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from backend.rule.resources import (
    AllergyRecord,
    EncounterRecord,
    MemberResources,
    OrderRecord,
    strip_snomed_tag,
    worst_reaction,
)
from contracts.models.entities import TimelineEvent

TYPE_ENCOUNTER = "ENCOUNTER"
TYPE_ALLERGY = "ALLERGY"
TYPE_MEDICATION_ORDER = "MEDICATION_ORDER"


def _codes(coding) -> list[str]:
    if coding is None:
        return []
    system = "RxNorm" if coding.system and "rxnorm" in coding.system.lower() else "SNOMED" if coding.system and "snomed" in coding.system.lower() else (coding.system or "code")
    return [f"{system}:{coding.code}"]


def _allergy_event(entity_id: UUID, a: AllergyRecord) -> TimelineEvent | None:
    if a.recorded_at is None:
        return None
    name = (strip_snomed_tag(a.code.display) if a.code else None) or (a.code.code if a.code else "unknown substance")
    worst = worst_reaction(a.reactions)
    reaction = ""
    if worst is not None:
        parts = [p for p in (strip_snomed_tag(worst.manifestation_display), worst.severity) if p]
        reaction = f" (reaction: {', '.join(parts)})" if parts else ""
    return TimelineEvent(
        entity_id=entity_id, occurred_at=a.recorded_at, type=TYPE_ALLERGY, codes=_codes(a.code),
        display=f"Allergy to {name}{reaction}", source_record_id=a.ref.source_record_id, source_system=a.ref.source_system,
        resource_id=a.ref.resource_id, verification=a.ref.verification, is_constructed=a.ref.is_constructed,
    )


def _order_event(entity_id: UUID, o: OrderRecord) -> TimelineEvent | None:
    if o.authored_at is None:
        return None
    name = (o.code.display or o.code.code) if o.code else "unknown medication"
    status = f" ({o.status} order)" if o.status else ""
    return TimelineEvent(
        entity_id=entity_id, occurred_at=o.authored_at, type=TYPE_MEDICATION_ORDER, codes=_codes(o.code),
        display=f"{name}{status}", source_record_id=o.ref.source_record_id, source_system=o.ref.source_system,
        resource_id=o.ref.resource_id, verification=o.ref.verification, is_constructed=o.ref.is_constructed,
    )


def _encounter_event(entity_id: UUID, e: EncounterRecord) -> TimelineEvent | None:
    if e.start is None:
        return None
    name = (strip_snomed_tag(e.type.display) if e.type else None) or "encounter"
    where = f" at {e.service_provider}" if e.service_provider else ""
    return TimelineEvent(
        entity_id=entity_id, occurred_at=e.start, type=TYPE_ENCOUNTER, codes=_codes(e.type),
        display=f"{name[:1].upper()}{name[1:]}{where}", source_record_id=e.ref.source_record_id,
        source_system=e.ref.source_system, resource_id=e.ref.resource_id, verification=e.ref.verification,
        is_constructed=e.ref.is_constructed,
    )


def sort_key(event: TimelineEvent) -> tuple[datetime, str, str]:
    return (event.occurred_at, str(event.source_record_id), event.resource_id or "")


def timeline_events(entity_id: UUID, members: Sequence[MemberResources]) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for m in members:
        events.extend(e for a in m.allergies if (e := _allergy_event(entity_id, a)))
        events.extend(e for o in m.orders if (e := _order_event(entity_id, o)))
        events.extend(e for enc in m.encounters if (e := _encounter_event(entity_id, enc)))
    events.sort(key=sort_key)
    return events


def encode_cursor(event: TimelineEvent) -> str:
    raw = "|".join([event.occurred_at.isoformat(), str(event.source_record_id), event.resource_id or ""])
    return base64.urlsafe_b64encode(raw.encode()).decode()


class BadCursor(ValueError):
    """An opaque cursor the server did not mint: the route answers 422 VALIDATION_ERROR."""


def decode_cursor(cursor: str) -> tuple[datetime, str, str]:
    try:
        ts, rid, res = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 2)
        return (datetime.fromisoformat(ts), rid, res)
    except (ValueError, UnicodeDecodeError) as exc:
        raise BadCursor("cursor is not one this endpoint issued") from exc


def page(events: Sequence[TimelineEvent], limit: int, cursor: str | None) -> tuple[list[TimelineEvent], str | None]:
    """Keyset page: items strictly after the cursor's key, plus the cursor of the last one when more remain."""
    after = decode_cursor(cursor) if cursor else None
    remaining = [e for e in events if after is None or sort_key(e) > after]
    items = remaining[:limit]
    next_cursor = encode_cursor(items[-1]) if len(remaining) > limit and items else None
    return items, next_cursor
