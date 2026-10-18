"""Capability tokens the chart-store writes require (ADR-016 §1).

``backend.policy.decide.allow_token`` / ``handoff_token`` build these from a decision whose
outcome matches; the token also names the tool the decision was made for, so an ALLOW minted for
the read-only ``search_patients`` is never a write capability. The constructors check the
decision, and a write function given anything else raises ``TokenMismatch``. The hard boundary
is the import test: only the executor may import ``backend.chart_store.writes``.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts.models.policy import PolicyDecision, PolicyOutcome, PolicyReason, ToolName


class TokenMismatch(TypeError):
    """The decision's outcome, reason or tool does not permit this token or this write."""


@dataclass(frozen=True)
class PolicyAllow:
    decision: PolicyDecision
    tool: ToolName

    def __post_init__(self) -> None:
        if not isinstance(self.decision, PolicyDecision) or self.decision.outcome != PolicyOutcome.ALLOW:
            raise TokenMismatch("PolicyAllow needs a PolicyDecision with outcome ALLOW")
        if not isinstance(self.tool, ToolName):
            raise TokenMismatch("PolicyAllow needs the ToolName the decision was made for")


@dataclass(frozen=True)
class PolicyHandoff:
    decision: PolicyDecision
    tool: ToolName

    def __post_init__(self) -> None:
        if (
            not isinstance(self.decision, PolicyDecision)
            or self.decision.reason_code != PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER
        ):
            raise TokenMismatch("PolicyHandoff needs a DENY CANDIDATE_IN_REVIEW_OR_HIGHER decision")
        if self.tool != ToolName.PROPOSE_NEW_CHART:
            raise TokenMismatch("only propose_new_chart hands off to a registrar")


def require_token(token: object, *kinds: type, tool: ToolName) -> None:
    """Raise unless ``token`` is one of the accepted token classes and was minted for ``tool``."""
    if not isinstance(token, kinds):
        names = " | ".join(k.__name__ for k in kinds)
        raise TokenMismatch(f"this write requires {names}, got {type(token).__name__}")
    if token.tool != tool:
        raise TokenMismatch(f"this write requires a {tool.value} token, got {token.tool.value}")
