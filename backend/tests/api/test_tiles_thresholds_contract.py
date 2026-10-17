"""Tiles from the continuous aggregates, the current threshold set, and a contract check that
every response body validates against the frozen Pydantic models."""

from __future__ import annotations

from backend.tests.api.conftest import API, approve_body, engine, review
from contracts.models.common import ErrorEnvelope, Page
from contracts.models.health import Health
from contracts.models.pairs import CandidatePair, CandidatePairDetail
from contracts.models.reviews import ReviewResponse
from contracts.models.sessions import MatchRunResponse, SessionResponse
from contracts.models.thresholds import ThresholdSet
from contracts.models.tiles import TileId, TilesResponse


def _tile(body: dict, tile_id: str) -> dict:
    return next(t for t in body["tiles"] if t["id"] == tile_id)


def test_tiles_return_rows_from_the_aggregates_after_a_review(client, match_run, pair_id):
    review(client, pair_id, approve_body())
    r = client.get(f"{API}/metrics/tiles", params={"window_minutes": 60})
    assert r.status_code == 200, r.text
    body = TilesResponse.model_validate(r.json())
    assert [t.id for t in body.tiles] == [TileId.DECISION_FLOW, TileId.HUMAN_REVIEW, TileId.AGENT_GATE]
    assert all(t.real_time for t in body.tiles)
    flow = _tile(r.json(), "DECISION_FLOW")
    assert flow["aggregate"] == "band_flow_1m"
    assert flow["total"] >= match_run["candidatePairs"], "PAIR_SCORED rows show without a refresh"
    human = _tile(r.json(), "HUMAN_REVIEW")
    assert human["aggregate"] == "review_outcomes_5m"
    approved = [b for b in human["buckets"] if b["series"] == "APPROVED"]
    assert approved and sum(b["count"] for b in approved) >= 1
    assert approved[0]["meanLatencyMs"] is not None
    gate = _tile(r.json(), "AGENT_GATE")
    assert gate["aggregate"] == "agent_gate_5m"
    assert gate["windowMinutes"] == 60


def test_tiles_window_is_aligned_to_bucket_boundaries(client, session, db_conn):
    """Codex finding 7: a review whose bucket started before the raw cutoff is still in the window.
    An event sits exactly on its 5-minute bucket start, 1 minute ago or less; window_minutes=1
    must still show it, which only an aligned cutoff does."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    now = datetime.now(UTC)
    bucket_start = (now - timedelta(minutes=1)).replace(second=0, microsecond=0)
    bucket_start -= timedelta(minutes=bucket_start.minute % 5)
    marker = "registrar:window-edge"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO event_log (ts, event_id, event_type, entry_point, actor, actor_type, outcome, latency_ms, mode) "
                "VALUES (:ts, gen_random_uuid(), 'LINK_APPROVED', 'API', :actor, 'REGISTRAR', 'APPROVED', 3, 'REPLAY')"
            ),
            {"ts": bucket_start, "actor": marker},
        )
    r = client.get(f"{API}/metrics/tiles", params={"window_minutes": 1})
    human = _tile(r.json(), "HUMAN_REVIEW")
    buckets = [b for b in human["buckets"] if b["bucket"].startswith(bucket_start.strftime("%Y-%m-%dT%H:%M"))]
    assert buckets, f"bucket {bucket_start.isoformat()} missing from a 1-minute window at {now.isoformat()}"


def test_tiles_window_is_bounded(client):
    assert client.get(f"{API}/metrics/tiles", params={"window_minutes": 0}).status_code == 422
    assert client.get(f"{API}/metrics/tiles", params={"window_minutes": 100000}).status_code == 422


def test_current_threshold_set(client):
    r = client.get(f"{API}/threshold-sets/current")
    assert r.status_code == 200, r.text
    body = ThresholdSet.model_validate(r.json())
    assert body.c_low <= body.c_high
    assert body.auto_link_enabled is False


def test_every_response_validates_against_the_contract(client):
    Health.model_validate(client.get(f"{API}/health").json())
    session = client.post(f"{API}/sessions", json={"scenarioId": "hero"})
    SessionResponse.model_validate(session.json())
    run = client.post(f"{API}/match-runs")
    run_body = MatchRunResponse.model_validate(run.json())
    pair_id = str(run_body.queued_pair_ids[0])
    Page[CandidatePair].model_validate(client.get(f"{API}/candidate-pairs").json())
    CandidatePairDetail.model_validate(client.get(f"{API}/candidate-pairs/{pair_id}").json())
    ReviewResponse.model_validate(review(client, pair_id, approve_body()).json())
    ReviewResponse.model_validate(review(client, pair_id, approve_body()).json())  # the 200 same-state shape
    TilesResponse.model_validate(client.get(f"{API}/metrics/tiles").json())
    ThresholdSet.model_validate(client.get(f"{API}/threshold-sets/current").json())
    for failing in (
        client.post(f"{API}/sessions", json={"scenarioId": "nope"}),
        client.get(f"{API}/candidate-pairs/00000000-0000-4000-8000-000000000000"),
        client.post(f"{API}/candidate-pairs/{pair_id}/reviews", json=approve_body()),
        client.get(f"{API}/candidate-pairs", params={"cursor": "zzz"}),
    ):
        env = ErrorEnvelope.model_validate(failing.json())
        assert failing.headers["X-Request-Id"]
        assert env.error.code.value in failing.text
