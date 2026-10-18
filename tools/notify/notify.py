"""CheckMate patient notifier: an optional sidecar, off unless started.

It polls the running API (GET only) and texts the patient through macOS Messages at three check-in
milestones, each at most once per intake session. Every text is a fixed sentence with no name, no
record content and no medical detail. In the demo a stand-in contact receives it; in production it
would go to the number the patient typed at the kiosk. The product never imports this module and
works the same whether it runs or not.

Milestones, all read from the frozen API:
- HELD: a FRONTDESK_HANDOFF candidate pair whose current decision is PROPOSED (the identity gate
  denied a new chart and put the check-in in the registrar's queue).
- CONFIRMED: a FRONTDESK_HANDOFF pair whose current decision is LINKED (the registrar approved).
- NEW_CHART: GET /intake-sessions/{id} reports registration state NEW_CHART (the gate allowed a new
  chart). Intake session ids come from the event feed (GET /events, intakeSessionId).

A demo Reset starts a new demo session; the notifier then forgets what it sent, so the same scripted
check-in after a Reset texts again.

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
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

HELD, CONFIRMED, NEW_CHART = "HELD", "CONFIRMED", "NEW_CHART"
MILESTONES = (HELD, CONFIRMED, NEW_CHART)
# The only texts ever sent. Fixed, so no record field can reach the phone.
MESSAGES = {
    HELD: (
        "CheckMate: Thanks for checking in. A registrar is confirming your record. "
        "Please stay nearby; we'll text you when it's done."
    ),
    CONFIRMED: (
        "CheckMate: You're checked in. A registrar confirmed your record. "
        "Please have a seat; someone will call your name."
    ),
    NEW_CHART: (
        "CheckMate: Thanks for checking in. We've started your registration; "
        "a registrar will finish it with you shortly."
    ),
}

DEFAULT_API_BASE = "http://127.0.0.1:8000"
POLL_INTERVAL_S = 2.0
HTTP_TIMEOUT_S = 3.0
# Long enough for the one-time macOS Automation prompt, which blocks osascript until answered.
OSASCRIPT_TIMEOUT_S = 60.0
PAGE_LIMIT = 200  # the frozen schema's maximum for list endpoints
MAX_PAGES = 10  # bounds one read of the candidate-pair list; a demo holds a handful of hand-offs
# The event feed is drained before the watermark moves, or an intake older than the cut could be skipped for good.
# A match run writes hundreds of events; this cap (100,000 events) only guards against a runaway feed.
EVENT_MAX_PAGES = 500
# Events are re-read this far back each poll: an event can commit after a newer one was already read.
EVENT_OVERLAP_S = 30

PAIRS_PATH = "/api/v1/candidate-pairs"
SESSION_PATH = "/api/v1/sessions/current"
EVENTS_PATH = "/api/v1/events"
INTAKE_PATH = "/api/v1/intake-sessions"
HANDOFF_ORIGIN = "FRONTDESK_HANDOFF"
PENDING_STATUS = "PROPOSED"
LINKED_STATUS = "LINKED"
NEW_CHART_STATE = "NEW_CHART"
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


@dataclass(frozen=True)
class DemoSession:
    id: str | None
    created_at: str | None


def current_session(fetch: Fetch, api_base: str) -> DemoSession:
    """The demo session; its id changes on every Reset. Empty before the first Reset."""
    try:
        body = fetch(api_base + SESSION_PATH)
    except NotFound:
        return DemoSession(None, None)
    if not isinstance(body, dict):
        raise ApiUnavailable("unexpected session shape")
    session_id, created_at = body.get("id"), body.get("createdAt")
    return DemoSession(str(session_id) if session_id else None, str(created_at) if created_at else None)


def _pages(fetch: Fetch, url: str, query: dict, max_pages: int = MAX_PAGES) -> Iterator[dict]:
    query = dict(query)
    for _ in range(max_pages):
        body = fetch(f"{url}?{urllib.parse.urlencode(query)}")
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise ApiUnavailable("unexpected list shape")
        yield body
        cursor = body.get("nextCursor")
        if not cursor:
            return
        query["cursor"] = cursor


def handoff_checkins(fetch: Fetch, api_base: str, status: str) -> set[str]:
    """Intake session ids with a hand-off pair whose current decision has this status."""
    keys: set[str] = set()
    query = {"origin": HANDOFF_ORIGIN, "status": status, "limit": PAGE_LIMIT}
    for body in _pages(fetch, api_base + PAIRS_PATH, query):
        for item in body["items"]:
            key = _handoff_key(item, status)
            if key:
                keys.add(key)
    return keys


def _handoff_key(item: object, status: str) -> str | None:
    # The server already filters; re-check so a filter change can never turn into a false text.
    if not isinstance(item, dict) or item.get("origin") != HANDOFF_ORIGIN:
        return None
    decision = item.get("decision")
    if not isinstance(decision, dict) or decision.get("status") != status:
        return None
    # The hand-off writer always sets intakeSessionId (backend/chart_store/writes.py); the pair id is a fallback.
    key = item.get("intakeSessionId") or item.get("id")
    return str(key) if key else None


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def intake_ids_since(fetch: Fetch, api_base: str, since: str | None) -> tuple[set[str], datetime | None]:
    """Intake session ids named by events at or after `since`, and the newest event time read."""
    ids: set[str] = set()
    newest: datetime | None = None
    query: dict = {"limit": PAGE_LIMIT}
    if since:
        query["since"] = since
    for body in _pages(fetch, api_base + EVENTS_PATH, query, max_pages=EVENT_MAX_PAGES):
        for item in body["items"]:
            if not isinstance(item, dict):
                continue
            if item.get("intakeSessionId"):
                ids.add(str(item["intakeSessionId"]))
            ts = _parse_ts(item.get("ts"))
            if ts is not None and (newest is None or ts > newest):
                newest = ts
    return ids, newest


def registration_state(fetch: Fetch, api_base: str, intake_id: str) -> str | None:
    """The intake session's derived registration state, or None if it is gone (a Reset)."""
    try:
        body = fetch(f"{api_base}{INTAKE_PATH}/{urllib.parse.quote(intake_id, safe='')}")
    except NotFound:
        return None
    registration = body.get("registration") if isinstance(body, dict) else None
    state = registration.get("state") if isinstance(registration, dict) else None
    return str(state) if state else None


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
        log(f"Sent a check-in text to the configured {recipient.kind}.")

    return live_send


# --- the poll loop ---------------------------------------------------------------------------


class _SessionChanged(Exception):
    """A Reset landed between the reads of one poll."""


@dataclass(frozen=True)
class Reading:
    session: DemoSession
    found: dict[str, set[str]]  # milestone -> intake session ids at that milestone now
    intakes: set[str]  # every intake session id known in this demo session
    newest_event: datetime | None


def _no_sends() -> dict[str, set[str]]:
    return {milestone: set() for milestone in MILESTONES}


@dataclass
class Notifier:
    fetch: Fetch
    send: Send
    api_base: str
    log: Callable[[str], None] = print
    session_id: str | None = None
    sent: dict[str, set[str]] = field(default_factory=_no_sends)  # milestone -> intake ids already handled
    intakes: set[str] = field(default_factory=set)
    event_since: str | None = None
    baselined: bool = False
    session_known: bool = False
    api_down: bool = False

    def _read(self) -> Reading:
        session = current_session(self.fetch, self.api_base)
        same = self.session_known and session.id == self.session_id
        held = handoff_checkins(self.fetch, self.api_base, PENDING_STATUS)
        confirmed = handoff_checkins(self.fetch, self.api_base, LINKED_STATUS)
        found_ids, newest = intake_ids_since(
            self.fetch, self.api_base, self.event_since if same else session.created_at
        )
        intakes = (self.intakes if same else set()) | found_ids | held | confirmed
        settled = (self.sent[CONFIRMED] | self.sent[NEW_CHART]) if same else set()
        new_chart = {
            intake_id
            for intake_id in sorted(intakes - settled - confirmed)
            if registration_state(self.fetch, self.api_base, intake_id) == NEW_CHART_STATE
        }
        if current_session(self.fetch, self.api_base).id != session.id:
            raise _SessionChanged
        found = {HELD: held, CONFIRMED: confirmed, NEW_CHART: new_chart}
        return Reading(session=session, found=found, intakes=intakes, newest_event=newest)

    def _start_session(self, reading: Reading) -> None:
        self.session_id, self.session_known = reading.session.id, True
        self.sent, self.intakes = _no_sends(), set()
        self.event_since = reading.session.created_at

    def _remember(self, reading: Reading) -> None:
        self.intakes = set(reading.intakes)
        if reading.newest_event is not None:
            self.event_since = (reading.newest_event - timedelta(seconds=EVENT_OVERLAP_S)).isoformat()

    def poll_once(self) -> int:
        """Read the API once and text each new milestone. Returns how many texts were sent."""
        try:
            reading = self._read()
        except _SessionChanged:
            return 0  # the next poll sees one consistent session
        except ApiUnavailable:
            if not self.baselined:
                # Down at start: nothing is known to have happened, so every milestone seen once it answers is new.
                self.baselined = True
            if not self.api_down:
                self.log(f"API not reachable; retrying quietly every {POLL_INTERVAL_S:g} s.")
                self.api_down = True
            return 0
        if self.api_down:
            self.log("API reachable again.")
            self.api_down = False
        if not self.baselined:
            # Milestones already reached at start are not announced, so restarting the notifier never re-texts.
            self._start_session(reading)
            for milestone in MILESTONES:
                self.sent[milestone] = set(reading.found[milestone])
            self._remember(reading)
            self.baselined = True
            waiting = len(set().union(*reading.found.values()))
            self.log(f"Watching check-ins ({waiting} already past a milestone, not announced).")
            return 0
        if not self.session_known or reading.session.id != self.session_id:
            if self.session_known:
                self.log("Demo reset seen; the next check-in texts again.")
            self._start_session(reading)
        self._remember(reading)
        return self._send_new(reading.found)

    def _send_new(self, found: dict[str, set[str]]) -> int:
        done = found[CONFIRMED] | found[NEW_CHART] | self.sent[CONFIRMED] | self.sent[NEW_CHART]
        due = {
            HELD: found[HELD] - self.sent[HELD] - done,  # never a late "held" text once it is settled
            CONFIRMED: found[CONFIRMED] - self.sent[CONFIRMED],
            NEW_CHART: found[NEW_CHART] - self.sent[NEW_CHART],
        }
        self.sent[HELD] |= done
        sent = 0
        for milestone in MILESTONES:
            for intake_id in sorted(due[milestone]):
                self.sent[milestone].add(intake_id)  # one attempt per milestone: a failing send never loops
                try:
                    self.send(MESSAGES[milestone])
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
