"""GET /candidate-pairs (bounded, keyset cursor, filters) and GET /candidate-pairs/{id}."""
from __future__ import annotations

import uuid

from backend.tests.api.conftest import API, approve_body, review
from contracts.models.common import Page
from contracts.models.pairs import CandidatePair, CandidatePairDetail


def test_list_returns_pairs_with_current_decision(client, match_run):
    r = client.get(f"{API}/candidate-pairs")
    assert r.status_code == 200, r.text
    page = Page[CandidatePair].model_validate(r.json())
    assert len(page.items) == match_run["candidatePairs"]
    assert {str(p.id) for p in page.items} >= set(match_run["queuedPairIds"])
    assert all(p.decision.status == "PROPOSED" for p in page.items)
    assert all(p.origin == "MATCH_RUN" for p in page.items)
    assert page.next_cursor is None


def test_list_is_ordered_by_distance_from_half(client, match_run):
    items = client.get(f"{API}/candidate-pairs").json()["items"]
    distances = [abs(i["decision"]["p"] - 0.5) for i in items]
    assert distances == sorted(distances)


def test_list_limit_is_clamped_and_cursor_walks_the_queue(client, match_run):
    r = client.get(f"{API}/candidate-pairs", params={"limit": 1000})
    assert r.status_code == 200, r.text
    r = client.get(f"{API}/candidate-pairs", params={"limit": 1})
    page = r.json()
    assert len(page["items"]) == 1
    seen = [page["items"][0]["id"]]
    total = match_run["candidatePairs"]
    if total > 1:
        assert page["nextCursor"], "more pairs exist, so a cursor must be returned"
    while page.get("nextCursor"):
        page = client.get(f"{API}/candidate-pairs", params={"limit": 1, "cursor": page["nextCursor"]}).json()
        assert len(page["items"]) == 1
        seen.append(page["items"][0]["id"])
    assert len(seen) == total
    assert len(set(seen)) == total


def test_list_rejects_malformed_cursor(client, match_run):
    r = client.get(f"{API}/candidate-pairs", params={"cursor": "not-a-cursor"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_filters_by_status_and_band(client, match_run, pair_id):
    review(client, pair_id, approve_body())
    linked = client.get(f"{API}/candidate-pairs", params={"status": "LINKED"}).json()["items"]
    assert [p["id"] for p in linked] == [pair_id]
    proposed = client.get(f"{API}/candidate-pairs", params={"status": "PROPOSED"}).json()["items"]
    assert pair_id not in {p["id"] for p in proposed}
    band = linked[0]["decision"]["band"]
    same_band = client.get(f"{API}/candidate-pairs", params={"band": band}).json()["items"]
    assert pair_id in {p["id"] for p in same_band}
    other = client.get(f"{API}/candidate-pairs", params={"origin": "FRONTDESK_HANDOFF"}).json()["items"]
    assert other == []


def test_detail_has_records_contributions_history_and_preview(client, pair_id):
    r = client.get(f"{API}/candidate-pairs/{pair_id}")
    assert r.status_code == 200, r.text
    detail = CandidatePairDetail.model_validate(r.json())
    assert str(detail.pair.id) == pair_id
    assert detail.record_a.record.id == detail.pair.record_a_id
    assert detail.record_b.record.id == detail.pair.record_b_id
    assert detail.contributions
    assert [h.version for h in detail.history] == [1]
    assert detail.history[0].evidence_snapshot is not None
    assert detail.merge_preview.member_count_if_approved >= 1


def test_detail_history_is_oldest_first_after_a_review(client, pair_id):
    review(client, pair_id, approve_body())
    detail = client.get(f"{API}/candidate-pairs/{pair_id}").json()
    assert [h["version"] for h in detail["history"]] == [1, 2]
    assert detail["pair"]["decision"]["version"] == 2


def test_detail_unknown_pair_is_404(client, session):
    r = client.get(f"{API}/candidate-pairs/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
