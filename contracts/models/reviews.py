"""POST /candidate-pairs/{id}/reviews: the human decision (architecture §5, §7).

A discriminated union on ``action`` so the schema itself says REJECT needs a reason:
the frontend generator and schemathesis see the rule, not just the server.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from contracts.models.alerts import SafetyAlert
from contracts.models.common import ContractModel, ReasonCode
from contracts.models.entities import Entity
from contracts.models.pairs import MatchDecision

ACTOR_DESCRIPTION = "registrar:<label>; a fixture label, not an authenticated identity"


class ApproveRequest(ContractModel):
    """Requires the ``Idempotency-Key`` header, minted once when the decision dialog opens."""

    action: Literal["APPROVE"]
    actor: str = Field(min_length=1, max_length=80, description=ACTOR_DESCRIPTION)
    note: str | None = Field(default=None, max_length=500)


class RejectRequest(ContractModel):
    """Requires the ``Idempotency-Key`` header. DIFFERENT_PERSON writes not_a_match; INSUFFICIENT_EVIDENCE does not."""

    action: Literal["REJECT"]
    actor: str = Field(min_length=1, max_length=80, description=ACTOR_DESCRIPTION)
    reason_code: ReasonCode
    note: str | None = Field(default=None, max_length=500)


ReviewRequest = Annotated[ApproveRequest | RejectRequest, Field(discriminator="action")]


class ReviewResponse(ContractModel):
    decision: MatchDecision
    entity: Entity | None = Field(default=None, description="the entity after APPROVE; None after REJECT")
    alerts: list[SafetyAlert] = Field(default_factory=list)
