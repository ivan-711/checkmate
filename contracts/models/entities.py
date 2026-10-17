"""Entities, read-time golden record, timeline and history (architecture §4, §8)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from contracts.models.common import ContractModel, Crosswalk


class GoldenAlternate(ContractModel):
    value: str | int | float | bool | dict | list | None
    crosswalk: Crosswalk


class GoldenField(ContractModel):
    field: str
    value: str | int | float | bool | dict | list | None
    crosswalk: Crosswalk
    rule: str = Field(description="why this value won, e.g. MOST_FREQUENT, MOST_RECENT, MAJORITY, CONFLICT_UNRESOLVED")
    alternates: list[GoldenAlternate] = Field(default_factory=list)


class EntityMember(ContractModel):
    source_record_id: UUID
    source_system: str
    is_constructed: bool = False
    verification: str | None = Field(default=None, description="e.g. AGENT_INTAKE_UNVERIFIED for intake records")


class Entity(ContractModel):
    id: UUID
    version: int = Field(ge=1)
    members: list[EntityMember]
    golden: list[GoldenField] = Field(default_factory=list)
    all_links_reviewer_approved: bool = Field(default=True, description="true by construction: only humans create LINKED")


class TimelineVerification(StrEnum):
    CODED = "CODED"
    CSV_DERIVED = "CSV_DERIVED"
    AGENT_INTAKE_UNVERIFIED = "AGENT_INTAKE_UNVERIFIED"


class TimelineEvent(ContractModel):
    entity_id: UUID
    occurred_at: datetime
    type: str = Field(description="e.g. ENCOUNTER, ALLERGY, MEDICATION_ORDER")
    codes: list[str] = Field(default_factory=list)
    display: str
    source_record_id: UUID
    source_system: str
    resource_id: str | None = None
    verification: TimelineVerification
    is_constructed: bool = False


class HistoryEvent(ContractModel):
    ts: datetime
    event_type: str
    actor: str
    actor_type: str
    pair_id: UUID | None = None
    decision_id: UUID | None = None
    summary: str
