"""POST /candidate-pairs/{id}/what-ifs: engine-computed counterfactuals on the hero pair (ADR-013)."""
from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from contracts.models.common import Band, ContractModel, Contribution


class WhatIfButton(StrEnum):
    REMOVE_ADDRESS = "REMOVE_ADDRESS"
    CHANGE_BIRTH_YEAR = "CHANGE_BIRTH_YEAR"
    SWAP_DOB_DAY_MONTH = "SWAP_DOB_DAY_MONTH"
    ACCENT_HYPHEN_SURNAME = "ACCENT_HYPHEN_SURNAME"


class WhatIfRequest(ContractModel):
    """The full button set, never a toggle."""

    buttons: list[WhatIfButton] = Field(default_factory=list, max_length=4)


class ScoreState(ContractModel):
    p: float = Field(ge=0, le=1)
    raw_score: float
    band: Band
    contributions: list[Contribution]
    negative_rules_fired: list[str] = Field(default_factory=list)


class HeldOutRecall(ContractModel):
    button: WhatIfButton
    category: str
    recall: float | None = Field(default=None, ge=0, le=1)
    n_pairs: int = Field(ge=0)
    n_entities: int = Field(ge=0)
    n_components: int = Field(ge=0)
    low_support: bool = Field(default=False, description="fewer than 50 components")


class WhatIfResponse(ContractModel):
    baseline: ScoreState
    what_if: ScoreState
    deltas: list[Contribution] = Field(description="per-feature logit change")
    caption: str = Field(description='plain language; REMOVE_ADDRESS reads "not enough to link", never "two people"')
    counterfactual_fields: dict[str, str | None] = Field(default_factory=dict)
    alert_would_be_hidden: bool
    held_out_recall: list[HeldOutRecall] = Field(description="every button's category, not just the ones pressed")
    seed: int
