"""GET /threshold-sets/current (architecture §6). Raw cutoffs decide; Platt is display-only."""
from __future__ import annotations

from pydantic import Field

from contracts.models.common import ContractModel


class ThresholdSet(ContractModel):
    thresholds_id: str
    c_low: float
    c_high: float
    t_low_display: float | None = None
    t_high_display: float | None = None
    auto_link_enabled: bool = Field(default=False, description="always false in the demo (ADR-015)")
    is_calibrated: bool = Field(default=False, description='"calibrated" appears in the UI only when true')
    source_run_id: str | None = None
