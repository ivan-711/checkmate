"""GET /events: the append-only feed, newest first, keyset over (ts DESC, event_id DESC) (G16 step 7).

The acceptance script loops ``GET /events?limit=200&cursor=...`` and counts ``items[].eventType``.
Tests stay bounded: event_log is never truncated, so they compare pages against the database's
own ordering instead of walking the whole table.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from backend.api.events import encode_event_cursor
from backend.tests.api.conftest import API, approve_body, engine, reject_body, review
from contracts.models.common import EventType, Page
from contracts.models.events import EventLogRow

UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9_]*$")
NOTE_MARKER = "EVENTS-FEED-NOTE-MARKER"
RECORD_FIELDS = ("givenName", "familyName", "birthDate", "phoneE164", "addressLine")


def _top_ids(conn, n: int) -> list[str]:
    rows = conn.execute(text("SELECT event_id FROM event_log ORDER BY ts DESC, event_id DESC LIMIT :n"), {"n": n})
    return [str(r.event_id) for r in rows]


def _insert_at(conn, ts: datetime, n: int) -> list[str]:
    ids = sorted((uuid.uuid4() for _ in range(n)), reverse=True)  # event_id DESC within one ts
    for event_id in ids:
        conn.execute(
            text(
                "INSERT INTO event_log (ts, event_id, event_type, entry_point, actor, actor_type, mode) "
                "VALUES (:ts, :id, 'EXTERNAL_CALL', 'CLI', 'system:test', 'SYSTEM', 'REPLAY')"
            ),
            {"ts": ts, "id": event_id},
        )
    return [str(i) for i in ids]


def test_two_pages_return_the_newest_rows_exactly_once_in_order(client, match_run, db_conn):
    first = client.get(f"{API}/events", params={"limit": 3})
    assert first.status_code == 200, first.text
    page1 = Page[EventLogRow].model_validate(first.json())
    assert len(page1.items) == 3
    assert page1.next_cursor
    page2 = Page[EventLogRow].model_validate(
        client.get(f"{API}/events", params={"limit": 3, "cursor": page1.next_cursor}).json()
    )
    served = [str(e.event_id) for e in page1.items + page2.items]
    assert len(set(served)) == len(served) == 6
    assert served == _top_ids(db_conn, 6), "pages are the database's newest rows, no gaps, no repeats"


def test_rows_sharing_one_timestamp_are_split_across_pages_without_loss(client, session):
    ts = datetime.now(UTC)
    with engine.begin() as conn:
        tied = _insert_at(conn, ts, 3)
    page1 = client.get(f"{API}/events", params={"limit": 2}).json()
    page2 = client.get(f"{API}/events", params={"limit": 2, "cursor": page1["nextCursor"]}).json()
    served = [e["eventId"] for e in page1["items"] + page2["items"]]
    assert served[:3] == tied, "the event_id tie-break keeps every row of one ts exactly once"


def test_last_page_has_no_next_cursor(client, db_conn):
    oldest = db_conn.execute(text("SELECT ts, event_id FROM event_log ORDER BY ts ASC, event_id ASC LIMIT 3")).all()
    assert len(oldest) == 3, "earlier tests wrote events"
    # A cursor positioned at the third-oldest row leaves exactly two rows after it.
    cursor = encode_event_cursor(oldest[2].ts, oldest[2].event_id)
    page = client.get(f"{API}/events", params={"limit": 200, "cursor": cursor}).json()
    assert [e["eventId"] for e in page["items"]] == [str(oldest[1].event_id), str(oldest[0].event_id)]
    assert page["nextCursor"] is None


def test_limit_over_200_is_a_422_envelope(client):
    r = client.get(f"{API}/events", params={"limit": 201})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert r.headers["X-Request-Id"]


def test_bad_cursor_is_422_validation_error(client):
    for bad in ("not-a-cursor", "eyJ0cyI6ICJub3QtYS1kYXRlIn0", encode_event_cursor(datetime(2026, 1, 1), uuid.uuid4())):
        r = client.get(f"{API}/events", params={"cursor": bad})
        assert r.status_code == 422, (bad, r.text)
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_event_types_are_upper_snake_and_payloads_never_carry_records(client, session, pair_id):
    review(client, pair_id, reject_body("INSUFFICIENT_EVIDENCE", note=NOTE_MARKER))
    review(client, pair_id, approve_body(note=NOTE_MARKER))
    r = client.get(f"{API}/events", params={"limit": 200})
    body = r.json()
    items = body["items"]
    types = [e["eventType"] for e in items]
    assert {"DEMO_RESET", "PAIR_SCORED", "MATCH_RUN_COMPLETED", "LINK_REJECTED", "LINK_APPROVED"} <= set(types)
    assert all(UPPER_SNAKE.match(t) and t in EventType.__members__ for t in types)
    # Fields that cannot occur by chance inside a uuid or a number (a 5-digit ZIP could).
    record_values = {
        source["normalized"][field]
        for source in session["sources"]
        for field in RECORD_FIELDS
        if source["normalized"][field]
    }
    serialized = r.text
    assert NOTE_MARKER not in serialized, "note text never reaches the event log"
    for value in record_values:
        assert value not in serialized, f"record field {value!r} in the feed"
    for e in items:
        assert e["payload"] is not None
        assert "raw_payload" not in e["payload"] and "rawPayload" not in e["payload"]
