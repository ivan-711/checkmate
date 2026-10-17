"""Safety alerts, DetectedIssue-shaped (rule spec §5; architecture §4, §10)."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from contracts.models.common import ContractModel
from contracts.version import RULE_ID, RULE_VERSION

CARD_FOOTER = (
    "Rule BL-AMOX-01 v1. Not checked: cephalosporin cross-reactivity, intolerances, dose, "
    "free-text allergies. Absence of a flag is not evidence that no conflict exists. "
    "This rule and its wording were not reviewed by a clinician."
)


class AlertTier(StrEnum):
    A = "A"  # severe or anaphylaxis recorded
    B = "B"  # mild, moderate or severity not recorded; shown collapsed


class AlertStatus(StrEnum):
    PRELIMINARY = "PRELIMINARY"
    RETRACTED = "RETRACTED"


class ResourceRef(ContractModel):
    source_record_id: UUID
    source_system: str
    resource_id: str


class Citation(ContractModel):
    label_name: str
    set_id: str
    revised: str
    url: str
    quote: str = Field(description="verbatim contraindication text; never paraphrased")


class SafetyAlert(ContractModel):
    id: UUID
    entity_id: UUID
    rule_id: str = RULE_ID
    rule_version: str = RULE_VERSION
    tier: AlertTier
    allergy_ref: ResourceRef
    order_ref: ResourceRef
    revealed_by_merge: bool
    severity: str = Field(default="moderate", description="both tiers: nothing renders as a time-critical alarm")
    status: AlertStatus
    card_text: str
    card_footer: str = CARD_FOOTER
    citation: Citation | None = Field(default=None, description="Tier A only; None when no cached label")
    constructed_scenario: bool = Field(default=False, description='"constructed scenario" badge')
    identified_at: datetime
