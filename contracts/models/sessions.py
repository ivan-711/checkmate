"""Demo sessions (reset) and match runs (architecture §5)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from contracts.models.common import Band, ContractModel
from contracts.models.records import SourceCard
from contracts.version import MATCH_RUN_QUEUED_PAIR_IDS_MAX


class CreateSessionRequest(ContractModel):
    scenario_id: str = Field(max_length=64, description='e.g. "hero" or "frontdesk-hero"')


class SessionResponse(ContractModel):
    id: UUID
    scenario_id: str
    scorer_version: str
    threshold_set_id: str
    created_at: datetime
    sources: list[SourceCard] = Field(description="the scenario's showcase source cards (the hero pair's records), never the whole loaded corpus")
    hero_provisional: bool = Field(description='true until the 20:00 selection; UI badge "provisional"')
    hero_constructed_floor: bool = Field(default=False, description="the labeled hand-built hero is in use")
    previous_session_id: UUID | None = Field(default=None, description="for POST /sessions/{previousId}/restore")


class OversizedBlock(ContractModel):
    key_type: str
    size: int = Field(ge=0)


class MatchRunResponse(ContractModel):
    run_id: UUID
    records: int = Field(ge=0)
    entities: int = Field(ge=0)
    all_pairs: int = Field(ge=0)
    candidate_pairs: int = Field(ge=0)
    reduction_ratio: float = Field(ge=0, le=1)
    band_counts: dict[Band, int]
    oversized_blocks: list[OversizedBlock] = Field(default_factory=list)
    pairs_skipped_oversized: int = Field(ge=0)
    queued_pair_ids: list[UUID] = Field(default_factory=list, max_length=MATCH_RUN_QUEUED_PAIR_IDS_MAX)
    scorer_version: str
    threshold_set_id: str
    elapsed_ms: int = Field(ge=0)
