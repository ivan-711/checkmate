"""GET /events: the append-only event feed, newest first (architecture §5 bounded lists, §11).

Keyset over (ts DESC, event_id DESC), the hypertable's primary key read backwards, so a page
never skips or repeats a row even when several events share one timestamp.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BeforeValidator
from sqlalchemy import text

from backend.api.common import invalid_cursor, pack_cursor, unpack_cursor
from backend.app.deps import EngineDep
from backend.app.errors import ApiError
from backend.app.openapi_meta import common_error_responses
from contracts.models.common import ErrorCode, Page
from contracts.models.events import EventLogRow, Versions
from contracts.version import API_PREFIX, LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX

# RFC 3339 date-time, the contract's ``format: date-time``: full-date "T" full-time, offset required.
RFC3339_DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")


def rfc3339_date_time(value):
    """Lax datetime parsing would read 0.5 or 1700000000 as Unix times and 2026-10-17 as midnight in no
    stated zone; the feed takes only what the contract declares. Anything else is the 422 envelope."""
    if value is None or isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not RFC3339_DATE_TIME.match(value):
        raise ValueError("since must be an RFC 3339 date-time with a time and an offset, e.g. 2026-10-17T21:00:00Z")
    return datetime.fromisoformat(value.upper())  # an impossible date or time raises ValueError: also 422


Since = Annotated[datetime | None, BeforeValidator(rfc3339_date_time)]


def encode_event_cursor(ts: datetime, event_id: UUID, since: datetime | None = None) -> str:
    """The last row's sort key, plus the ``since`` filter the page was cut with, so a follow-up
    request that sends only the cursor keeps the same filter."""
    fields = {"ts": ts.isoformat(), "id": str(event_id)}
    if since is not None:
        fields["since"] = since.isoformat()
    return pack_cursor(fields)


def decode_event_cursor(cursor: str) -> tuple[datetime, UUID, datetime | None]:
    data = unpack_cursor(cursor)
    try:
        ts = datetime.fromisoformat(data["ts"])
        event_id = UUID(data["id"])
        since = datetime.fromisoformat(data["since"]) if data.get("since") is not None else None
    except (ValueError, KeyError, TypeError, AttributeError):
        raise invalid_cursor() from None
    # event_log.ts is timestamptz and the server writes offsets: a naive time is not one of our cursors
    if ts.tzinfo is None or (since is not None and since.tzinfo is None):
        raise invalid_cursor()
    return ts, event_id, since


def effective_since(requested: datetime | None, from_cursor: datetime | None) -> datetime | None:
    """The cursor carries the filter it was issued under; a different ``since`` beside it is a client error."""
    if requested is not None and requested != from_cursor:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "since differs from the filter the cursor was issued for")
    return from_cursor if from_cursor is not None else requested


router = APIRouter(prefix=API_PREFIX, tags=["core"])

EVENT_COLUMNS = (
    "ts, event_id, event_type, request_id, run_id, entry_point, entity_id, pair_id, decision_id, actor, actor_type, "
    "band, outcome, latency_ms, mode, versions, payload, intake_session_id, tool_call_id, tool_name, gate_outcome, "
    "reason_code, evidence_ids, evidence_snapshot, client_request_id, effect_status"
)
# Closed set of filter fragments; the request supplies values only.
_SINCE = "ts >= :since"
_AFTER = "(ts, event_id) < (:after_ts, :after_id)"


def page_query(with_since: bool, with_cursor: bool):
    clauses = [c for c, on in ((_SINCE, with_since), (_AFTER, with_cursor)) if on]
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return text(f"SELECT {EVENT_COLUMNS} FROM event_log{where} ORDER BY ts DESC, event_id DESC LIMIT :limit_plus_one")


# The contract's Versions keys, in both spellings a writer may store (camelCase alias or snake_case).
VERSION_KEYS = frozenset(
    key for name, info in Versions.model_fields.items() for key in (name, info.alias) if key is not None
)


def contract_versions(stored: dict | None) -> dict:
    """Only the keys the contract's ``Versions`` declares. Writers other than ``write_event`` may store
    more (W3b's ALERT_RAISED keeps ruleId, ruleVersion and the class table there); the table keeps
    them, the feed serves the contract shape, so one such row can never turn a page into a 500."""
    return {k: v for k, v in (stored or {}).items() if k in VERSION_KEYS}


SNAKE_CASE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def snake_to_camel(key: str) -> str:
    """A plain word join; pydantic's to_camel turns x_2y into x2Y."""
    first, *rest = key.split("_")
    return first + "".join(word[:1].upper() + word[1:] for word in rest)


def camel_keys(value):
    """Payload keys as the wire wants them (JSON is camelCase), at any depth; values untouched, and stored
    rows keep the keys their writer chose. Only snake_case identifiers (lowercase words joined by
    underscores) change. Every other key is data or already camelCase and is served exactly as stored:
    a uuid, an enum value such as AUTO_LINK, HTTPStatus, alertId. A conversion that would land on a key
    already present, or on another key's conversion, is skipped, so no value is ever dropped."""
    if isinstance(value, list):
        return [camel_keys(v) for v in value]
    if not isinstance(value, dict):
        return value
    targets = {k: snake_to_camel(k) for k in value if SNAKE_CASE_IDENTIFIER.match(k)}
    claims = Counter(targets.values())
    served = {}
    for key, inner in value.items():
        target = targets.get(key)
        out_key = target if target is not None and target not in value and claims[target] == 1 else key
        served[out_key] = camel_keys(inner)
    return served


def event_from_row(row) -> EventLogRow:
    fields = dict(row._mapping)
    fields["payload"] = camel_keys(fields["payload"] or {})
    fields["evidence_ids"] = fields["evidence_ids"] or []  # the column is nullable; the model's list is not
    fields["versions"] = contract_versions(fields["versions"])
    return EventLogRow.model_validate(fields)


@router.get(
    "/events",
    response_model=Page[EventLogRow],
    responses=common_error_responses(),
    description="Lane W3a (additive, G16 step 7). The append-only event feed, newest first; bounded list "
    "with an opaque keyset cursor over (ts, eventId). `since` keeps only rows with ts at or "
    "after it, so a caller can count one run's events on a reused database.",
)
def list_events(
    engine: EngineDep,
    since: Since = None,
    limit: int = Query(LIST_LIMIT_DEFAULT, ge=1, le=LIST_LIMIT_MAX),
    cursor: str | None = None,
) -> Page[EventLogRow]:
    params: dict = {"limit_plus_one": limit + 1}
    cursor_since = None
    if cursor:
        params["after_ts"], params["after_id"], cursor_since = decode_event_cursor(cursor)
    since = effective_since(since, cursor_since) if cursor else since
    if since is not None:
        params["since"] = since
    with engine.connect() as conn:
        rows = conn.execute(page_query(since is not None, bool(cursor)), params).all()
    page = rows[:limit]
    next_cursor = encode_event_cursor(page[-1].ts, page[-1].event_id, since) if len(rows) > limit else None
    return Page[EventLogRow](items=[event_from_row(r) for r in page], next_cursor=next_cursor)
