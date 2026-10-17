"""Response metadata for real routes, mirroring the frozen stubs in contracts/api_spec.py so
the served /openapi.json documents the same error statuses as the committed snapshot."""
from __future__ import annotations

from contracts.api_spec import _err
from contracts.models.common import ErrorCode


def error_responses(*codes: ErrorCode) -> dict:
    return _err(*codes)


def common_error_responses() -> dict:
    """What every stub documents: 422 VALIDATION_ERROR, 500 INTERNAL and the 501 stub status."""
    return _err(ErrorCode.VALIDATION_ERROR, ErrorCode.INTERNAL, ErrorCode.NOT_IMPLEMENTED)
