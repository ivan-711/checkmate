"""Capability tokens the chart-store writes require (ADR-016 §1).

Only ``backend.policy.decide.allow_token`` / ``handoff_token`` build these, from a decision whose
outcome matches. A write function given a bare ``PolicyDecision`` raises, so no path reaches the
chart store without going through ``decide``.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts.models.policy import PolicyDecision, PolicyOutcome, PolicyReason


class TokenMismatch(TypeError):
    """The decision's outcome does not permit this token."""


@dataclass(frozen=True)
class PolicyAllow:
    decision: PolicyDecision

    def __post_init__(self) -> None:
        if not isinstance(self.decision, PolicyDecision) or self.decision.outcome != PolicyOutcome.ALLOW:
            raise TokenMismatch("PolicyAllow needs a PolicyDecision with outcome ALLOW")


@dataclass(frozen=True)
class PolicyHandoff:
    decision: PolicyDecision

    def __post_init__(self) -> None:
        if (
            not isinstance(self.decision, PolicyDecision)
            or self.decision.reason_code != PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER
        ):
            raise TokenMismatch("PolicyHandoff needs a DENY CANDIDATE_IN_REVIEW_OR_HIGHER decision")


def require_token(token: object, *kinds: type) -> None:
    """Raise unless ``token`` is one of the accepted token classes (never a bare decision)."""
    if not isinstance(token, kinds):
        names = " | ".join(k.__name__ for k in kinds)
        raise TokenMismatch(f"this write requires {names}, got {type(token).__name__}")
