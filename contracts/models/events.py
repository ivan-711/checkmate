"""event_log rows and the feed (architecture §4, §11; ADR-016 §6)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from contracts.models.common import ActorType, Band, ContractModel, EntryPoint, EventType, Mode


class Versions(ContractModel):
    """Every agent_tool_called event and every replay recording carries promptVersion."""

    scorer_version: str | None = None
    threshold_set_id: str | None = None
    policy_version: str | None = None
    prompt_version: str | None = None
    tool_schema_version: str | None = None
    model_id: str | None = None
    transcript_sha256: str | None = None


class EventLogRow(ContractModel):
    ts: datetime
    event_id: UUID
    event_type: EventType
    request_id: str | None = None
    run_id: UUID | None = None
    entry_point: EntryPoint
    entity_id: UUID | None = None
    pair_id: UUID | None = None
    decision_id: UUID | None = None
    actor: str
    actor_type: ActorType
    band: Band | None = None
    outcome: str | None = None
    latency_ms: int | None = None
    mode: Mode
    versions: Versions = Field(default_factory=Versions)
    payload: dict = Field(default_factory=dict, description="validated args or summary; never free text")
    intake_session_id: UUID | None = None
    tool_call_id: UUID | None = None
    tool_name: str | None = None
    gate_outcome: str | None = None
    reason_code: str | None = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    evidence_snapshot: dict | None = None
    client_request_id: str | None = None
    effect_status: str | None = None
