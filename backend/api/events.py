"""GET /events: the append-only event feed, newest first (architecture §5 bounded lists, §11).

Keyset over (ts DESC, event_id DESC), the hypertable's primary key read backwards, so a page
never skips or repeats a row even when several events share one timestamp.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import text

from backend.api.common import invalid_cursor, pack_cursor, unpack_cursor
from backend.app.deps import EngineDep
from backend.app.openapi_meta import common_error_responses
from contracts.models.common import Page
from contracts.models.events import EventLogRow, Versions
from contracts.version import API_PREFIX, LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX


def encode_event_cursor(ts: datetime, event_id: UUID) -> str:
    return pack_cursor({"ts": ts.isoformat(), "id": str(event_id)})


def decode_event_cursor(cursor: str) -> tuple[datetime, UUID]:
    data = unpack_cursor(cursor)
    try:
        ts = datetime.fromisoformat(data["ts"])
        event_id = UUID(data["id"])
    except (ValueError, KeyError, TypeError, AttributeError):
        raise invalid_cursor() from None
    if ts.tzinfo is None:  # event_log.ts is timestamptz; a naive time is not one of our cursors
        raise invalid_cursor()
    return ts, event_id


router = APIRouter(prefix=API_PREFIX, tags=["core"])

EVENT_COLUMNS = (
    "ts, event_id, event_type, request_id, run_id, entry_point, entity_id, pair_id, decision_id, actor, actor_type, "
    "band, outcome, latency_ms, mode, versions, payload, intake_session_id, tool_call_id, tool_name, gate_outcome, "
    "reason_code, evidence_ids, evidence_snapshot, client_request_id, effect_status"
)
_FIRST_PAGE = text(f"SELECT {EVENT_COLUMNS} FROM event_log ORDER BY ts DESC, event_id DESC LIMIT :limit_plus_one")
_NEXT_PAGE = text(
    f"SELECT {EVENT_COLUMNS} FROM event_log WHERE (ts, event_id) < (:after_ts, :after_id) "
    "ORDER BY ts DESC, event_id DESC LIMIT :limit_plus_one"
)


# The contract's Versions keys, in both spellings a writer may store (camelCase alias or snake_case).
VERSION_KEYS = frozenset(
    key for name, info in Versions.model_fields.items() for key in (name, info.alias) if key is not None
)


def contract_versions(stored: dict | None) -> dict:
    """Only the keys the contract's ``Versions`` declares. Writers other than ``write_event`` may store
    more (W3b's ALERT_RAISED keeps ruleId, ruleVersion and the class table there); the table keeps
    them, the feed serves the contract shape, so one such row can never turn a page into a 500."""
    return {k: v for k, v in (stored or {}).items() if k in VERSION_KEYS}


def event_from_row(row) -> EventLogRow:
    fields = dict(row._mapping)
    fields["evidence_ids"] = fields["evidence_ids"] or []  # the column is nullable; the model's list is not
    fields["versions"] = contract_versions(fields["versions"])
    return EventLogRow.model_validate(fields)


@router.get(
    "/events",
    response_model=Page[EventLogRow],
    responses=common_error_responses(),
    description="Lane W3a (additive, G16 step 7). The append-only event feed, newest first; bounded list "
    "with an opaque keyset cursor over (ts, eventId).",
)
def list_events(
    engine: EngineDep,
    limit: int = Query(LIST_LIMIT_DEFAULT, ge=1, le=LIST_LIMIT_MAX),
    cursor: str | None = None,
) -> Page[EventLogRow]:
    params: dict = {"limit_plus_one": limit + 1}
    if cursor:
        params["after_ts"], params["after_id"] = decode_event_cursor(cursor)
    with engine.connect() as conn:
        rows = conn.execute(_NEXT_PAGE if cursor else _FIRST_PAGE, params).all()
    page = rows[:limit]
    next_cursor = encode_event_cursor(page[-1].ts, page[-1].event_id) if len(rows) > limit else None
    return Page[EventLogRow](items=[event_from_row(r) for r in page], next_cursor=next_cursor)
