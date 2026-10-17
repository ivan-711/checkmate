"""FrontDesk intake session, turn and tool-call records (architecture §22.4, ADR-016)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from contracts.models.common import Band, ContractModel, Contribution
from contracts.models.policy import EvidenceRef, Language, PolicyOutcome, PolicyReason
from contracts.version import MAX_USER_TEXT_CHARS


class AgentMode(StrEnum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"


class RegistrationState(StrEnum):
    NONE = "NONE"
    NEW_CHART = "NEW_CHART"
    PENDING_REGISTRAR = "PENDING_REGISTRAR"
    LINKED = "LINKED"
    RELEASED = "RELEASED"


class TurnStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EffectStatus(StrEnum):
    APPLIED = "APPLIED"
    REPLAYED = "REPLAYED"
    NONE = "NONE"


class AssistantTextSource(StrEnum):
    MODEL = "MODEL"
    TEMPLATE = "TEMPLATE"


class DegradedKind(StrEnum):
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    LOOP_GUARD = "LOOP_GUARD"
    REPLAY_DIVERGED = "REPLAY_DIVERGED"
    REPLAY_INPUT_MISMATCH = "REPLAY_INPUT_MISMATCH"


class Registration(ContractModel):
    """Derived on read from the intake record's decisions, never toggled."""

    state: RegistrationState
    intake_record_id: UUID | None = None
    handoff_pair_ids: list[UUID] = Field(default_factory=list)
    entity_id: UUID | None = None


class GateResult(ContractModel):
    outcome: PolicyOutcome
    reason_code: PolicyReason | None = None
    handoff_required: bool
    evidence_ids: list[EvidenceRef] = Field(default_factory=list)
    policy_version: str


class Effect(ContractModel):
    status: EffectStatus
    ref: str | None = None


class ToolCallCandidate(ContractModel):
    record_id: UUID
    source_system: str
    p: float = Field(ge=0, le=1)
    band: Band
    negative_rules_fired: list[str] = Field(default_factory=list)
    top_contributions: list[Contribution] = Field(default_factory=list)
    pair_id: UUID | None = None


class ToolCallRecord(ContractModel):
    """What the UI sees. The model sees only the minimal ToolResult (tools/tool_result.schema.json)."""

    id: UUID
    step_index: int = Field(ge=0)
    tool_name: str
    args: dict | None = Field(default=None, description="validated args; null when invalid")
    gate: GateResult
    effect: Effect
    candidates: list[ToolCallCandidate] = Field(
        default_factory=list, description="at most 10, highest band and raw score first; the audit row keeps all"
    )
    latency_ms: int = Field(ge=0)


class IntakeTurn(ContractModel):
    turn_index: int = Field(ge=0)
    user_text: str
    assistant_text: str
    assistant_text_source: AssistantTextSource
    agent_mode: AgentMode
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    registration: Registration
    degraded: DegradedKind | None = None


class IntakeSession(ContractModel):
    id: UUID
    created_at: datetime
    language: Language
    agent_mode: AgentMode
    registration: Registration
    turns: list[IntakeTurn] = Field(default_factory=list)
    closed: bool = False
    prompt_version: str
    tool_schema_version: str


class CreateIntakeSessionRequest(ContractModel):
    """No mode field: the server chooses the agent mode from FRONTDESK_AGENT_MODE."""

    language: Language | None = None
    scenario_context_id: str | None = Field(default=None, max_length=64)


class TurnRequest(ContractModel):
    """Requires the ``Idempotency-Key`` header, minted once per typed message."""

    text: str = Field(min_length=1, max_length=MAX_USER_TEXT_CHARS)
