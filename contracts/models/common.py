"""Shared enums, the error envelope and pagination (architecture §0, §5)."""
from __future__ import annotations

from enum import StrEnum
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from contracts.version import LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX


class ContractModel(BaseModel):
    """camelCase JSON on the wire, snake_case in Python, unknown keys rejected."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=False
    )


class Band(StrEnum):
    AUTO_LINK = "AUTO_LINK"
    REVIEW = "REVIEW"
    KEEP_SEPARATE = "KEEP_SEPARATE"


class DecisionStatus(StrEnum):
    PROPOSED = "PROPOSED"
    LINKED = "LINKED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class ReviewAction(StrEnum):
    """Explicit action, never a toggle: a retried request cannot flip a decision."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ReasonCode(StrEnum):
    DIFFERENT_PERSON = "DIFFERENT_PERSON"          # writes not_a_match
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"  # no suppression


class NegativeRule(StrEnum):
    SEX_CONFLICT = "SEX_CONFLICT"
    BIRTH_YEAR_GAP_GT_2 = "BIRTH_YEAR_GAP_GT_2"
    TWIN = "TWIN"
    PARENT_CHILD = "PARENT_CHILD"
    GENERATION_SUFFIX_MISMATCH = "GENERATION_SUFFIX_MISMATCH"
    PLACEHOLDER_NAME = "PLACEHOLDER_NAME"
    PLACEHOLDER_DOB = "PLACEHOLDER_DOB"
    STRONG_ID_CONFLICT = "STRONG_ID_CONFLICT"  # reserved; SSN is not a feature (13:15 decision)


class Mode(StrEnum):
    LIVE = "LIVE"
    LOCAL = "LOCAL"
    REPLAY = "REPLAY"


class ActorType(StrEnum):
    AGENT = "AGENT"
    REGISTRAR = "REGISTRAR"
    PATIENT = "PATIENT"
    SYSTEM = "SYSTEM"


class EntryPoint(StrEnum):
    API = "API"
    CLI = "CLI"
    EVAL_WORKER = "EVAL_WORKER"
    REPLAY = "REPLAY"
    AGENT = "AGENT"


class SourceKind(StrEnum):
    FHIR_PATIENT = "FHIR_PATIENT"
    CSV_ROW = "CSV_ROW"
    TEMPLATED_SPECIALIST = "TEMPLATED_SPECIALIST"
    ONC_BENCH = "ONC_BENCH"  # evaluation only; never rendered
    FRONTDESK_INTAKE = "FRONTDESK_INTAKE"


class PairOrigin(StrEnum):
    MATCH_RUN = "MATCH_RUN"
    FRONTDESK_HANDOFF = "FRONTDESK_HANDOFF"


class EventType(StrEnum):
    """The TEXT + CHECK list in migration 0001. Migration 0002 widens it after 16:00."""

    RECORD_INGESTED = "RECORD_INGESTED"
    MATCH_RUN_COMPLETED = "MATCH_RUN_COMPLETED"
    PAIR_SCORED = "PAIR_SCORED"
    LINK_APPROVED = "LINK_APPROVED"
    LINK_REJECTED = "LINK_REJECTED"
    LINK_REVOKED = "LINK_REVOKED"
    ENTITY_MERGED = "ENTITY_MERGED"
    ENTITY_SPLIT = "ENTITY_SPLIT"
    ALERT_RAISED = "ALERT_RAISED"
    ALERT_RETRACTED = "ALERT_RETRACTED"
    WHATIF_APPLIED = "WHATIF_APPLIED"
    DEMO_RESET = "DEMO_RESET"
    DEMO_RESTORED = "DEMO_RESTORED"
    EXPLANATION_GENERATED = "EXPLANATION_GENERATED"
    EXTERNAL_CALL = "EXTERNAL_CALL"
    EVAL_RUN_STARTED = "EVAL_RUN_STARTED"
    EVAL_RUN_FINISHED = "EVAL_RUN_FINISHED"
    INTAKE_STARTED = "INTAKE_STARTED"
    AGENT_TOOL_CALLED = "AGENT_TOOL_CALLED"
    INTAKE_HANDOFF_CREATED = "INTAKE_HANDOFF_CREATED"
    AGENT_TURN_DEGRADED = "AGENT_TURN_DEGRADED"


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"          # 422
    NOT_FOUND = "NOT_FOUND"                        # 404
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"      # 405
    CANNOT_LINK_CONFLICT = "CANNOT_LINK_CONFLICT"  # 409
    IDEMPOTENCY_MISMATCH = "IDEMPOTENCY_MISMATCH"  # 422
    DECISION_NOT_PENDING = "DECISION_NOT_PENDING"  # 409
    TURN_IN_PROGRESS = "TURN_IN_PROGRESS"          # 409
    SESSION_CLOSED = "SESSION_CLOSED"              # 409
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"  # 503
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"            # 501, stub routes only
    INTERNAL = "INTERNAL"                          # 500


ERROR_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.CANNOT_LINK_CONFLICT: 409,
    ErrorCode.IDEMPOTENCY_MISMATCH: 422,
    ErrorCode.DECISION_NOT_PENDING: 409,
    ErrorCode.TURN_IN_PROGRESS: 409,
    ErrorCode.SESSION_CLOSED: 409,
    ErrorCode.UPSTREAM_UNAVAILABLE: 503,
    ErrorCode.NOT_IMPLEMENTED: 501,
    ErrorCode.INTERNAL: 500,
}


class ErrorBody(ContractModel):
    code: ErrorCode
    message: str
    details: dict | list | None = None


class ErrorEnvelope(ContractModel):
    """The one error shape: ``{"error": {"code", "message", "details?"}}``."""

    error: ErrorBody


class Crosswalk(ContractModel):
    """Where a value came from: (source system, native record id)."""

    source_system: str
    source_record_id: str


class Contribution(ContractModel):
    feature: str
    logit: float
    value: float | None = Field(default=None, description="feature value in [0,1]; None when missing")


class PageParams(ContractModel):
    limit: int = Field(default=LIST_LIMIT_DEFAULT, ge=1, le=LIST_LIMIT_MAX)
    cursor: str | None = None


T = TypeVar("T")


class Page[T](ContractModel):
    items: list[T]
    next_cursor: str | None = None
