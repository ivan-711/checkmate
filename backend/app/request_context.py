"""Per-request correlation: request id, the middleware's clock, mode and entry point.

The middleware in ``backend.app.main`` builds one context per request and publishes it
through a context variable, so the event writer (and any lane's service code running
inside the request) can stamp ``request_id`` and ``latency_ms`` without threading the
request object through every call. Starlette copies context variables into the thread
that runs a sync endpoint, so the variable is visible there too.
"""

from __future__ import annotations

import re
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field

from contracts.models.common import EntryPoint, Mode


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    mode: Mode
    entry_point: EntryPoint = EntryPoint.API
    started: float = field(default_factory=time.perf_counter)

    def elapsed_ms(self) -> int:
        """Milliseconds since the middleware saw the request: the latency recorded on events."""
        return int((time.perf_counter() - self.started) * 1000)


_current: ContextVar[RequestContext | None] = ContextVar("checkmate_request_context", default=None)


def parse_mode(raw: str) -> Mode:
    """FRONTDESK_AGENT_MODE as an event mode; anything unknown is treated as REPLAY (offline)."""
    try:
        return Mode(raw)
    except ValueError:
        return Mode.REPLAY


REQUEST_ID_MAX_CHARS = 64
_REQUEST_ID_RE = re.compile(rf"^[A-Za-z0-9-]{{1,{REQUEST_ID_MAX_CHARS}}}$")


def accept_request_id(raw: str | None) -> str:
    """A client id is kept only as a short opaque token (<= 64 chars of [A-Za-z0-9-]): it is
    echoed into the response header, the log line and event_log, so it must never carry text."""
    if raw and _REQUEST_ID_RE.match(raw):
        return raw
    return str(uuid.uuid4())


def new_context(request_id: str | None, mode: Mode, entry_point: EntryPoint = EntryPoint.API) -> RequestContext:
    return RequestContext(request_id=accept_request_id(request_id), mode=mode, entry_point=entry_point)


def bind(ctx: RequestContext):
    """Publish ``ctx`` for the current task; returns the token for ``reset``."""
    return _current.set(ctx)


def reset(token) -> None:
    _current.reset(token)


def current() -> RequestContext:
    """The bound request context, or a fresh CLI context outside a request (scripts, tests)."""
    ctx = _current.get()
    if ctx is None:
        ctx = new_context(None, Mode.REPLAY, EntryPoint.CLI)
    return ctx
