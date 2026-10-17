"""``policy.decide`` signature and types (ADR-016 §3). The body lands in lane Q1.1.

``decide`` is a pure function: no I/O, no clock, no randomness. Only it constructs the
``PolicyAllow`` / ``PolicyHandoff`` values the chart-store writes require.
"""
from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from contracts.models.common import Band, ContractModel, DecisionStatus
from contracts.version import POLICY_VERSION


class ToolName(StrEnum):
    SEARCH_PATIENTS = "search_patients"
    PROPOSE_NEW_CHART = "propose_new_chart"
    ATTACH_HISTORY = "attach_history"


class PolicyReason(StrEnum):
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    SESSION_CLOSED = "SESSION_CLOSED"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    UNGROUNDED_FIELD = "UNGROUNDED_FIELD"
    LOOP_GUARD = "LOOP_GUARD"
    INCOMPLETE_DEMOGRAPHICS = "INCOMPLETE_DEMOGRAPHICS"  # UX copy key gate.missingid
    INTAKE_ALREADY_RECORDED = "INTAKE_ALREADY_RECORDED"
    ALREADY_LINKED = "ALREADY_LINKED"
    CANDIDATE_IN_REVIEW_OR_HIGHER = "CANDIDATE_IN_REVIEW_OR_HIGHER"
    NO_INTAKE_RECORD = "NO_INTAKE_RECORD"


HANDOFF_REASONS: frozenset[PolicyReason] = frozenset(
    {
        PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER,
        PolicyReason.LOOP_GUARD,
        PolicyReason.INTAKE_ALREADY_RECORDED,
    }
)


class PolicyOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class Sex(StrEnum):
    FEMALE = "FEMALE"
    MALE = "MALE"
    UNKNOWN = "UNKNOWN"


class Language(StrEnum):
    ES = "ES"
    EN = "EN"


class Evidence(ContractModel):
    """For every demographic field the model fills, the patient's exact words (verbatim)."""

    given_name: str | None = Field(default=None, max_length=160)
    family_name: str | None = Field(default=None, max_length=160)
    birth_date: str | None = Field(default=None, max_length=160)
    sex: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=160)
    address_line: str | None = Field(default=None, max_length=160)
    postal_code: str | None = Field(default=None, max_length=160)


class Demographics(ContractModel):
    given_name: str | None = Field(default=None, max_length=60)
    family_name: str | None = Field(
        default=None, max_length=80, description="All surnames exactly as the patient said them"
    )
    birth_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    sex: Sex | None = None
    phone: str | None = Field(default=None, max_length=20)
    address_line: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, pattern=r"^[0-9]{5}$")


class SearchArgs(Demographics):
    """Server-side rule: (givenName and familyName) or birthDate, else INVALID_ARGUMENTS."""

    evidence: Evidence

    @model_validator(mode="after")
    def _enough_to_search(self) -> SearchArgs:
        if not ((self.given_name and self.family_name) or self.birth_date):
            raise ValueError("search needs (givenName and familyName) or birthDate")
        return self


class ProposeArgs(Demographics):
    given_name: str = Field(max_length=60)
    family_name: str = Field(max_length=80)
    birth_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    sex: Sex
    preferred_language: Language
    evidence: Evidence


class HistoryKind(StrEnum):
    ALLERGY = "ALLERGY"
    MEDICATION = "MEDICATION"
    CONDITION = "CONDITION"
    OTHER = "OTHER"


class HistoryItem(ContractModel):
    kind: HistoryKind
    text: str = Field(max_length=200)
    evidence_quote: str = Field(max_length=200)


class AttachArgs(ContractModel):
    """No target field: the target is always this session's intake record."""

    items: list[HistoryItem] = Field(min_length=1, max_length=5)


class InvalidArgs(ContractModel):
    """What the executor builds when the model's arguments fail validation."""

    raw: dict
    errors: list[str]


class SessionFacts(ContractModel):
    intake_record_id: UUID | None = None
    intake_args_sha256: str | None = None
    session_closed: bool = False
    tool_calls_this_turn: int = Field(ge=0, description="including this one")
    identical_call_count: int = Field(ge=0, description="same (tool, args_sha256) earlier in this session")


class AgentAction(ContractModel):
    tool: str = Field(description="a ToolName, or whatever name the model invented")
    args: SearchArgs | ProposeArgs | AttachArgs | InvalidArgs
    args_sha256: str
    grounding_ok: bool
    session: SessionFacts


class ScoredCandidate(ContractModel):
    record_id: UUID
    source_system: str
    s: float = Field(description="raw score; bands are cut on s through c_low/c_high")
    p: float = Field(ge=0, le=1, description="display-only Platt estimate; never read by decide()")
    band: Band
    negative_rules_fired: list[str] = Field(default_factory=list)
    human_status: DecisionStatus | None = Field(
        default=None, description="current decision on (intake, candidate), if a pair exists"
    )
    pair_id: UUID | None = None
    decision_id: UUID | None = None
    evidence_snapshot_sha256: str


class EvidenceKind(StrEnum):
    CANDIDATE_RECORD = "CANDIDATE_RECORD"
    MATCH_DECISION = "MATCH_DECISION"
    INTAKE_RECORD = "INTAKE_RECORD"


class EvidenceRef(ContractModel):
    kind: EvidenceKind
    id: UUID


class PolicyDecision(ContractModel):
    outcome: PolicyOutcome
    reason_code: PolicyReason | None = Field(default=None, description="None iff ALLOW")
    handoff_required: bool
    evidence_ids: list[EvidenceRef] = Field(default_factory=list)
    message_key: str = Field(description="template key for the EN/ES text shown to the model and the UI")
    policy_version: Literal["frontdesk-gate/1"] = POLICY_VERSION

    @model_validator(mode="after")
    def _reason_iff_deny(self) -> PolicyDecision:
        if (self.outcome == PolicyOutcome.DENY) != (self.reason_code is not None):
            raise ValueError("reason_code is set iff outcome is DENY")
        if self.handoff_required and self.reason_code not in HANDOFF_REASONS:
            raise ValueError("handoff_required only for CANDIDATE_IN_REVIEW_OR_HIGHER, LOOP_GUARD, INTAKE_ALREADY_RECORDED")
        return self


def decide(action: AgentAction, candidates: Sequence[ScoredCandidate]) -> PolicyDecision:
    """The 13-row decision table of ADR-016 §3. Implemented by lane Q1.1 in ``backend/policy``.

    Row order (first match wins): UNKNOWN_TOOL, SESSION_CLOSED, LOOP_GUARD, INVALID_ARGUMENTS,
    UNGROUNDED_FIELD, search ALLOW, INCOMPLETE_DEMOGRAPHICS, INTAKE_ALREADY_RECORDED,
    ALREADY_LINKED, CANDIDATE_IN_REVIEW_OR_HIGHER, propose ALLOW, NO_INTAKE_RECORD, attach ALLOW.
    """
    raise NotImplementedError("lane Q1.1 implements policy.decide in backend/policy")
