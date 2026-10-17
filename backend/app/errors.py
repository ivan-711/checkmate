"""The one application error: a code from the contract plus a message, rendered by the
envelope handler registered in ``backend.app.main``."""

from __future__ import annotations

from contracts.models.common import ErrorCode


class ApiError(Exception):
    def __init__(self, code: ErrorCode, message: str, details: dict | list | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
