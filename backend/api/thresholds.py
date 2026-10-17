"""GET /threshold-sets/current (architecture §5, §6): the row that decides bands.
Additive route: the model is frozen in contracts/models/thresholds.py; the path is not in the
13:15 stub set and is flagged as additive in the W3a PR."""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.common import current_threshold_row
from backend.app.deps import EngineDep
from backend.app.errors import ApiError
from backend.app.openapi_meta import common_error_responses
from contracts.models.common import ErrorCode
from contracts.models.thresholds import ThresholdSet
from contracts.version import API_PREFIX

router = APIRouter(prefix=API_PREFIX, tags=["core"])


@router.get(
    "/threshold-sets/current",
    response_model=ThresholdSet,
    responses=common_error_responses(),
    description="Lane W3a. The current threshold set: cLow/cHigh decide; display values are display-only.",
)
def get_current_threshold_set(engine: EngineDep) -> ThresholdSet:
    with engine.connect() as conn:
        row = current_threshold_row(conn)
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "no current threshold set")
    return ThresholdSet(
        thresholds_id=row.thresholds_id,
        c_low=row.c_low,
        c_high=row.c_high,
        t_low_display=row.t_low_display,
        t_high_display=row.t_high_display,
        auto_link_enabled=row.auto_link_enabled,
        is_calibrated=row.is_calibrated,
        source_run_id=row.source_run_id,
    )
