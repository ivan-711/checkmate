"""CheckMate registrar notifier: an optional sidecar, off unless started.

It polls the running API (GET only) and, once per new kiosk hand-off, sends the registrar one
generic iMessage through macOS Messages. The message carries no patient data. The product never
imports this module and works the same whether it runs or not.

A hold is a candidate pair with origin FRONTDESK_HANDOFF whose current decision is PROPOSED: the
identity gate denied a new chart and put the check-in in the registrar's queue. One check-in can
produce several such pairs (one per blocking candidate), so one notification is sent per intake
session. A demo Reset starts a new demo session; the notifier then forgets what it sent, so the
same scripted check-in after a Reset notifies again.

Run from the repository root:  python3 tools/notify/notify.py   or   uv run python -m tools.notify
Standard library only.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

# The only text ever sent. Fixed, so no record field can reach the phone.
MESSAGE = "CheckMate: a kiosk check-in is waiting for registrar review."

DEFAULT_API_BASE = "http://127.0.0.1:8000"
POLL_INTERVAL_S = 2.0
HTTP_TIMEOUT_S = 3.0
# Long enough for the one-time macOS Automation prompt, which blocks osascript until answered.
OSASCRIPT_TIMEOUT_S = 60.0
PAGE_LIMIT = 200  # the frozen schema's maximum for list endpoints
MAX_PAGES = 10  # a demo holds a handful of hand-offs; this bounds one poll

PAIRS_PATH = "/api/v1/candidate-pairs"
SESSION_PATH = "/api/v1/sessions/current"
HANDOFF_ORIGIN = "FRONTDESK_HANDOFF"
PENDING_STATUS = "PROPOSED"
DRY_RUN_OFF_VALUES = frozenset({"0", "false", "no", "off"})

HERE = Path(__file__).resolve().parent
HANDLE_SCRIPT = HERE / "send_handle.applescript"
CONTACT_SCRIPT = HERE / "send_contact.applescript"

# Error numbers raised inside send_contact.applescript, and the only lines printed for them.
CONTACT_NOT_FOUND = "contact not found"
NO_PHONE = "no phone"
AUTOMATION_DENIED_CODE = "-1743"  # macOS errAEEventNotPermitted
_OSA_ERROR_CODE = re.compile(r"\((-?\d{1,5})\)\s*$")


class ApiUnavailable(Exception):
    """The API could not be read (down, timeout, non-JSON or unexpected shape)."""


class NotFound(ApiUnavailable):
    """The API answered 404."""


class ConfigError(Exception):
    pass


class SendFailed(Exception):
    """A send failed; str(exc) is one printable line that never holds the recipient or a number."""


@dataclass(frozen=True)
class Recipient:
    kind: str  # "handle" or "contact"
    value: str = field(repr=False)  # never printed: it may be a phone number


@dataclass(frozen=True)
class Config:
    api_base: str
    dry_run: bool
    recipient: Recipient | None


def load_config(env: Mapping[str, str]) -> Config:
    api_base = (env.get("CHECKMATE_API_BASE") or DEFAULT_API_BASE).strip().rstrip("/")
    dry_run = (env.get("NOTIFY_DRY_RUN") or "1").strip().lower() not in DRY_RUN_OFF_VALUES
    handle = (env.get("NOTIFY_IMESSAGE_TO") or "").strip()
    contact = (env.get("NOTIFY_IMESSAGE_TO_CONTACT") or "").strip()
    if handle and contact:
        raise ConfigError("Set NOTIFY_IMESSAGE_TO or NOTIFY_IMESSAGE_TO_CONTACT, not both.")
    recipient = Recipient("contact", contact) if contact else Recipient("handle", handle) if handle else None
    if not dry_run and recipient is None:
        raise ConfigError("NOTIFY_DRY_RUN=0 needs NOTIFY_IMESSAGE_TO or NOTIFY_IMESSAGE_TO_CONTACT.")
    return Config(api_base=api_base, dry_run=dry_run, recipient=recipient)


# --- reading the API -------------------------------------------------------------------------

Fetch = Callable[[str], object]


def http_get_json(url: str) -> object:
    """GET one URL and parse JSON. Every failure becomes ApiUnavailable (404 becomes NotFound)."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        exc.close()  # release the error response's socket; polls repeat every few seconds
        if exc.code == 404:
            raise NotFound(url) from None
        raise ApiUnavailable(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:  # refused, timeout, bad body
        raise ApiUnavailable(type(exc).__name__) from None


def current_session_id(fetch: Fetch, api_base: str) -> str | None:
    """The demo session id; it changes on every Reset. None before the first Reset."""
    try:
        body = fetch(api_base + SESSION_PATH)
    except NotFound:
        return None
    if not isinstance(body, dict):
        raise ApiUnavailable("unexpected session shape")
    session_id = body.get("id")
    return str(session_id) if session_id else None


def held_checkins(fetch: Fetch, api_base: str) -> set[str]:
    """One key per check-in waiting for the registrar: its intake session id (or the pair id)."""
    keys: set[str] = set()
    query = {"origin": HANDOFF_ORIGIN, "status": PENDING_STATUS, "limit": PAGE_LIMIT}
    for _ in range(MAX_PAGES):
        body = fetch(f"{api_base}{PAIRS_PATH}?{urllib.parse.urlencode(query)}")
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise ApiUnavailable("unexpected candidate-pairs shape")
        for item in body["items"]:
            key = _held_key(item)
            if key:
                keys.add(key)
        cursor = body.get("nextCursor")
        if not cursor:
            break
        query["cursor"] = cursor
    return keys


def _held_key(item: object) -> str | None:
    # The server already filters; re-check so a filter change can never turn into a false buzz.
    if not isinstance(item, dict) or item.get("origin") != HANDOFF_ORIGIN:
        return None
    decision = item.get("decision")
    if not isinstance(decision, dict) or decision.get("status") != PENDING_STATUS:
        return None
    # The hand-off writer always sets intakeSessionId (backend/chart_store/writes.py); the pair id is a fallback.
    key = item.get("intakeSessionId") or item.get("id")
    return str(key) if key else None


# --- sending ---------------------------------------------------------------------------------

Runner = Callable[[list[str], float], subprocess.CompletedProcess]
Send = Callable[[str], None]


def run_osascript(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def osascript_args(recipient: Recipient, text: str) -> list[str]:
    """Recipient and text go in as argv to `on run argv`; nothing is spliced into script source."""
    script = CONTACT_SCRIPT if recipient.kind == "contact" else HANDLE_SCRIPT
    return ["osascript", str(script), recipient.value, text]


def failure_line(recipient: Recipient, stderr: str) -> str:
    """One printable line for a failed send. stderr is never echoed: it can hold the number."""
    if recipient.kind == "contact":
        if CONTACT_NOT_FOUND in stderr:
            return CONTACT_NOT_FOUND
        if NO_PHONE in stderr:
            return NO_PHONE
    match = _OSA_ERROR_CODE.search(stderr.strip())
    code = match.group(1) if match else "unknown"
    if code == AUTOMATION_DENIED_CODE:
        return "Send failed: Automation access was not allowed. Allow it in the macOS prompt, then try again."
    return f"Send failed (osascript error {code}). Check that Messages is signed in to iMessage."


def make_sender(config: Config, runner: Runner = run_osascript, log: Callable[[str], None] = print) -> Send:
    if config.dry_run:
        target = config.recipient.kind if config.recipient else "no recipient set"

        def dry_send(text: str) -> None:
            log(f"[dry run] would send to {target}: {text}")

        return dry_send

    recipient = config.recipient
    if recipient is None:  # load_config refuses this; kept so a direct caller cannot send to nobody
        raise ConfigError("Live sending needs a recipient.")

    def live_send(text: str) -> None:
        try:
            proc = runner(osascript_args(recipient, text), OSASCRIPT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise SendFailed(
                "Send timed out. If macOS is asking for Automation access, click Allow, then Reset and check in again."
            ) from None
        except FileNotFoundError:
            raise SendFailed("osascript not found: live sending needs macOS.") from None
        if proc.returncode != 0:
            raise SendFailed(failure_line(recipient, proc.stderr or ""))
        log(f"Sent the registrar notice to the configured {recipient.kind}.")

    return live_send


# --- the poll loop ---------------------------------------------------------------------------


@dataclass
class Notifier:
    fetch: Fetch
    send: Send
    api_base: str
    log: Callable[[str], None] = print
    session_id: str | None = None
    seen: set[str] = field(default_factory=set)
    baselined: bool = False
    session_known: bool = False
    api_down: bool = False

    def poll_once(self) -> int:
        """Read the API once and notify each new hold. Returns how many notices were sent."""
        try:
            session_id = current_session_id(self.fetch, self.api_base)
            keys = held_checkins(self.fetch, self.api_base)
            if current_session_id(self.fetch, self.api_base) != session_id:
                return 0  # a Reset landed between the reads; the next poll sees one consistent session
        except ApiUnavailable:
            if not self.baselined:
                # Down at start: nothing is known to be waiting, so every hold seen once it answers is new.
                self.baselined = True
            if not self.api_down:
                self.log(f"API not reachable; retrying quietly every {POLL_INTERVAL_S:g} s.")
                self.api_down = True
            return 0
        if self.api_down:
            self.log("API reachable again.")
            self.api_down = False
        if not self.baselined:
            # Holds already waiting at start are not announced, so restarting the notifier never re-buzzes.
            self.session_id, self.session_known, self.seen = session_id, True, set(keys)
            self.baselined = True
            self.log(f"Watching for held check-ins ({len(keys)} already waiting, not announced).")
            return 0
        if not self.session_known or session_id != self.session_id:
            if self.session_known:
                self.log("Demo reset seen; the next held check-in notifies again.")
            self.session_id, self.session_known, self.seen = session_id, True, set()
        sent = 0
        for key in sorted(keys - self.seen):
            self.seen.add(key)  # one attempt per hold: a failing send never becomes a retry loop
            try:
                self.send(MESSAGE)
                sent += 1
            except SendFailed as exc:
                self.log(str(exc))
        return sent


def main() -> int:
    try:
        config = load_config(os.environ)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    notifier = Notifier(fetch=http_get_json, send=make_sender(config), api_base=config.api_base)
    mode = "dry run, nothing is sent" if config.dry_run else f"live, sending to the configured {config.recipient.kind}"
    print(f"CheckMate notifier: polling {config.api_base} every {POLL_INTERVAL_S:g} s ({mode}). Ctrl-C stops it.")
    last_error = None
    try:
        while True:
            try:
                notifier.poll_once()
                last_error = None
            except Exception as exc:  # noqa: BLE001 - a sidecar must never die mid-demo; print the type only, once
                if type(exc).__name__ != last_error:
                    last_error = type(exc).__name__
                    print(f"Unexpected {last_error}; still running.")
            time.sleep(POLL_INTERVAL_S)
    except KeyboardInterrupt:
        print("Notifier stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
