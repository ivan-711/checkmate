"""Keyset paging over a queue of several pairs: pages are disjoint, ordered and complete."""

from __future__ import annotations

import uuid

from backend.api.sessions import insert_source_card
from backend.match.seam import resolve_core
from backend.tests.api.conftest import API, engine
from contracts.models.records import SourceCard


def _variants(card: SourceCard, n: int) -> list[SourceCard]:
    """Near-duplicates of one card with distinct ids: they block together and score differently."""
    out = []
    for i in range(n):
        rid = uuid.uuid4()
        record = card.record.model_copy(update={"id": rid, "source_local_id": f"VARIANT-{i}-{rid.hex[:6]}"})
        normalized = card.normalized.model_copy(
            update={
                "record_id": rid,
                "given_name": f"{card.normalized.given_name}{'x' * i}",
                "given_name_folded": f"{card.normalized.given_name_folded}{'x' * i}",
                "phone_e164": None if i % 2 else card.normalized.phone_e164,
            }
        )
        out.append(SourceCard(record=record, normalized=normalized, display_label=card.display_label))
    return out


def test_cursor_pages_are_disjoint_ordered_and_complete(client, session):
    base = SourceCard.model_validate(session["sources"][1])
    core = resolve_core()
    with engine.begin() as conn:
        for card in _variants(base, 4):
            insert_source_card(conn, card, core)
    run = client.post(f"{API}/match-runs").json()
    total = run["candidatePairs"]
    assert total >= 6, "six records in one DOB block give at least 6 pairs"

    seen: list[str] = []
    distances: list[float] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = client.get(f"{API}/candidate-pairs", params=params).json()
        pages += 1
        assert len(page["items"]) <= 2
        seen += [i["id"] for i in page["items"]]
        distances += [abs(i["decision"]["p"] - 0.5) for i in page["items"]]
        cursor = page.get("nextCursor")
        if not cursor:
            break
    assert pages == -(-total // 2)
    assert len(seen) == total
    assert len(set(seen)) == total
    assert distances == sorted(distances)
    full = [i["id"] for i in client.get(f"{API}/candidate-pairs", params={"limit": 200}).json()["items"]]
    assert full == seen
