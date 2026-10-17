"""Candidate pairs and append-only match decisions (architecture §4, §5)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from contracts.models.common import (
    ActorType,
    Band,
    ContractModel,
    Contribution,
    DecisionStatus,
    PairOrigin,
    ReasonCode,
)
from contracts.models.records import SourceCard


class EvidenceSnapshot(ContractModel):
    """Immutable at decision time; never re-decoded (the HAPI bug we avoid)."""

    features: dict[str, float | None]
    missing_flags: dict[str, bool] = Field(default_factory=dict)
    weights: dict[str, float]
    intercept: float
    contributions: list[Contribution]
    raw_score: float
    c_low: float
    c_high: float
    platt_a: float | None = None
    platt_b: float | None = None
    t_low_display: float | None = None
    t_high_display: float | None = None
    negative_rules_fired: list[str] = Field(default_factory=list)
    scorer_version: str
    threshold_set_id: str
    policy_version: str | None = None


class MatchDecision(ContractModel):
    id: UUID
    pair_id: UUID
    version: int = Field(ge=1)
    logit: float
    p: float = Field(ge=0, le=1, description="display-only")
    band: Band
    negative_rules_fired: list[str] = Field(default_factory=list)
    status: DecisionStatus
    actor: str = Field(description="recorded label, e.g. registrar:Registrar A or system:scorer")
    actor_type: ActorType
    reason_code: ReasonCode | None = None
    note: str | None = Field(default=None, max_length=500)
    decided_at: datetime
    scorer_version: str
    threshold_set_id: str
    evidence_snapshot: EvidenceSnapshot | None = Field(default=None, description="present in the evidence view")


class CandidatePair(ContractModel):
    id: UUID
    record_a_id: UUID
    record_b_id: UUID
    block_keys: list[str] = Field(default_factory=list)
    origin: PairOrigin
    intake_session_id: UUID | None = None
    decision: MatchDecision = Field(description="the current (max version) decision")
    auto_eligible: bool = Field(default=False, description='"auto-eligible" tag; auto-link is evaluation-only')


class MergePreview(ContractModel):
    entity_id_if_approved: UUID | None = None
    member_count_if_approved: int = Field(ge=0)
    alert_would_fire: bool


class CandidatePairDetail(ContractModel):
    pair: CandidatePair
    record_a: SourceCard
    record_b: SourceCard
    contributions: list[Contribution]
    history: list[MatchDecision] = Field(default_factory=list, description="all versions, oldest first")
    merge_preview: MergePreview
