"""GET /metrics/tiles: the three real-time continuous aggregates for a window (architecture §11).

All three views have ``materialized_only = false``, so a row written a moment ago shows up
without a refresh; ``real_time`` says so and the aggregate name goes in the caption.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import text

from backend.app.deps import EngineDep
from contracts.models.tiles import Tile, TileBucket, TileId, TilesResponse
from contracts.version import API_PREFIX

router = APIRouter(prefix=API_PREFIX, tags=["core"])

UNKNOWN_SERIES = "UNKNOWN"
WINDOW_DEFAULT_MINUTES = 60
WINDOW_MAX_MINUTES = 1440

# Closed map: tile id -> (aggregate name for the caption, query). The view name is never
# taken from the request.
TILE_SOURCES: dict[TileId, tuple[str, str]] = {
    TileId.DECISION_FLOW: ("band_flow_1m", (
        "SELECT bucket, band AS series, scored AS count, NULL AS mean_latency_ms, NULL AS max_latency_ms "
        "FROM band_flow_1m WHERE bucket >= :since ORDER BY bucket, series")),
    TileId.HUMAN_REVIEW: ("review_outcomes_5m", (
        "SELECT bucket, outcome AS series, decisions AS count, mean_latency_ms, max_latency_ms "
        "FROM review_outcomes_5m WHERE bucket >= :since ORDER BY bucket, series")),
    TileId.AGENT_GATE: ("agent_gate_5m", (
        "SELECT bucket, gate_outcome AS series, sum(calls) AS count, NULL AS mean_latency_ms, NULL AS max_latency_ms "
        "FROM agent_gate_5m WHERE bucket >= :since GROUP BY bucket, gate_outcome ORDER BY bucket, series")),
}


@router.get("/metrics/tiles", response_model=TilesResponse,
            description="Lane W3a (AGENT_GATE tile: Q1.3). Continuous-aggregate tiles for a window.")
def get_tiles(engine: EngineDep,
              window_minutes: int = Query(WINDOW_DEFAULT_MINUTES, ge=1, le=WINDOW_MAX_MINUTES)) -> TilesResponse:
    as_of = datetime.now(UTC)
    since = as_of - timedelta(minutes=window_minutes)
    tiles: list[Tile] = []
    with engine.connect() as conn:
        for tile_id, (aggregate, sql) in TILE_SOURCES.items():
            buckets = [
                TileBucket(bucket=r.bucket, series=r.series or UNKNOWN_SERIES, count=int(r.count),
                           mean_latency_ms=None if r.mean_latency_ms is None else float(r.mean_latency_ms),
                           max_latency_ms=None if r.max_latency_ms is None else int(r.max_latency_ms))
                for r in conn.execute(text(sql), {"since": since})
            ]
            tiles.append(Tile(id=tile_id, aggregate=aggregate, window_minutes=window_minutes, buckets=buckets,
                              total=sum(b.count for b in buckets), real_time=True))
    return TilesResponse(tiles=tiles, as_of=as_of)
