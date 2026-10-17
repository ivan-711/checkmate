"""GET /metrics/tiles: continuous-aggregate tiles (architecture §11)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from contracts.models.common import ContractModel


class TileId(StrEnum):
    DECISION_FLOW = "DECISION_FLOW"   # band_flow_1m
    HUMAN_REVIEW = "HUMAN_REVIEW"     # review_outcomes_5m
    AGENT_GATE = "AGENT_GATE"         # agent_gate_5m


class TileBucket(ContractModel):
    bucket: datetime
    series: str = Field(description="band, outcome, or gate outcome (ALLOW/DENY)")
    count: int = Field(ge=0)
    mean_latency_ms: float | None = None
    max_latency_ms: int | None = None


class Tile(ContractModel):
    id: TileId
    aggregate: str = Field(description="the continuous aggregate name shown in the caption")
    window_minutes: int = Field(ge=1)
    buckets: list[TileBucket]
    total: int = Field(ge=0)
    real_time: bool = Field(default=True, description="materialized_only = false")


class TilesResponse(ContractModel):
    tiles: list[Tile]
    as_of: datetime
