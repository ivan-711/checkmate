"""Unit tests for the optional patient notifier. The HTTP fetch and the osascript runner are fakes:
nothing here reads a real API or sends a message."""

from __future__ import annotations

import socket
import subprocess
import threading
import urllib.parse
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tools.notify import notify
from tools.notify.notify import (
    CONFIRMED,
    EVENTS_PATH,
    HELD,
    INTAKE_PATH,
    MESSAGES,
    NEW_CHART,
    PAIRS_PATH,
    SESSION_PATH,
    ApiUnavailable,
    Config,
    ConfigError,
    Notifier,
    Recipient,
    http_get_json,
    load_config,
    make_sender,
    osascript_args,
)

API = "http://127.0.0.1:8000"
FAKE_NUMBER = "+15555550123"
T0 = datetime(2026, 10, 18, 15, 0, tzinfo=UTC)


def handoff(pair_id: str, intake_id: str | None = "intake-1", status: str = "PROPOSED") -> dict:
    return {
        "id": pair_id,
        "recordAId": "rec-a-" + pair_id,
        "recordBId": "rec-b-" + pair_id,
        "origin": "FRONTDESK_HANDOFF",
        "intakeSessionId": intake_id,
        "blockKeys": ["DM_SURNAME_BY:TNRS|1987"],
        "decision": {"id": "dec-" + pair_id, "status": status, "band": "REVIEW", "rawScore": 3.1},
    }


class FakeApi:
    """Serves the four GET endpoints the notifier reads from in-memory state; can be switched off."""

    def __init__(self) -> None:
        self.session_id: str | None = "session-1"
        self.created_at = T0
        self.items: list[dict] = []  # candidate pairs
        self.events: list[dict] = []
        self.registrations: dict[str, str] = {}
        self.down = False
        self.urls: list[str] = []
        self.clock = 0

    def checkin(self, intake_id: str, state: str = "NONE") -> None:
        """A kiosk check-in starts: one INTAKE_STARTED event and a derived registration state."""
        self.clock += 1
        ts = (self.created_at + timedelta(seconds=self.clock)).isoformat().replace("+00:00", "Z")
        self.events.append({"ts": ts, "eventType": "INTAKE_STARTED", "intakeSessionId": intake_id})
        self.registrations[intake_id] = state

    def reset(self, session_id: str) -> None:
        self.session_id, self.items, self.registrations = session_id, [], {}
        self.created_at = self.created_at + timedelta(minutes=10)
        self.clock = 0

    def set_status(self, status: str) -> None:
        for item in self.items:
            item["decision"]["status"] = status

    def __call__(self, url: str) -> object:
        self.urls.append(url)
        if self.down:
            raise ApiUnavailable("ConnectionRefusedError")
        path, _, raw_query = url.removeprefix(API).partition("?")
        query = dict(urllib.parse.parse_qsl(raw_query))
        if path == SESSION_PATH:
            if self.session_id is None:
                raise notify.NotFound(url)
            return {"id": self.session_id, "scenarioId": "hero", "createdAt": self.created_at.isoformat()}
        if path == PAIRS_PATH:
            status = query.get("status")
            return {"items": [i for i in self.items if i["decision"]["status"] == status], "nextCursor": None}
        if path == EVENTS_PATH:
            since = datetime.fromisoformat(query["since"]) if "since" in query else None
            rows = [e for e in self.events if since is None or datetime.fromisoformat(e["ts"]) >= since]
            return {"items": sorted(rows, key=lambda e: e["ts"], reverse=True), "nextCursor": None}
        if path.startswith(INTAKE_PATH + "/"):
            intake_id = urllib.parse.unquote(path.removeprefix(INTAKE_PATH + "/"))
            if intake_id not in self.registrations:
                raise notify.NotFound(url)
            return {"id": intake_id, "registration": {"state": self.registrations[intake_id]}}
        raise AssertionError(f"unexpected URL {url}")


class Recorder:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.lines: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)

    def log(self, line: str) -> None:
        self.lines.append(line)


def make_notifier(api: FakeApi, rec: Recorder) -> Notifier:
    return Notifier(fetch=api, send=rec.send, api_base=API, log=rec.log)


def hold(api: FakeApi, intake_id: str = "intake-1", pair_id: str = "pair-1") -> None:
    api.checkin(intake_id, "PENDING_REGISTRAR")
    api.items.append(handoff(pair_id, intake_id))


def test_held_checkin_texts_once():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    assert n.poll_once() == 0  # baseline: nothing waiting
    hold(api)
    assert n.poll_once() == 1
    assert rec.sent == [MESSAGES[HELD]]
    assert any("origin=FRONTDESK_HANDOFF" in u and "status=PROPOSED" in u for u in api.urls)


def test_same_hold_does_not_resend():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    # one check-in held against two blocking candidates: two pairs, one intake session, one text
    hold(api, "intake-1", "pair-1")
    api.items.append(handoff("pair-2", "intake-1"))
    for _ in range(5):
        n.poll_once()
    assert rec.sent == [MESSAGES[HELD]]


def test_confirmed_follows_held_once():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    hold(api)
    n.poll_once()
    api.set_status("LINKED")  # the registrar approved the hand-off pair
    api.registrations["intake-1"] = "LINKED"
    for _ in range(4):
        n.poll_once()
    assert rec.sent == [MESSAGES[HELD], MESSAGES[CONFIRMED]]
    assert any("status=LINKED" in u for u in api.urls)


def test_new_chart_texts_once():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    api.checkin("intake-7")  # still talking: registration NONE, nothing to send
    n.poll_once()
    assert rec.sent == []
    api.registrations["intake-7"] = "NEW_CHART"  # the gate allowed a new chart
    for _ in range(4):
        n.poll_once()
    assert rec.sent == [MESSAGES[NEW_CHART]]
    assert any(u.endswith(INTAKE_PATH + "/intake-7") for u in api.urls)


def test_new_chart_after_a_released_hold_texts_both_once():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    hold(api)
    n.poll_once()
    api.set_status("REJECTED")  # DIFFERENT_PERSON: the hold is released, then the gate allows a new chart
    api.registrations["intake-1"] = "NEW_CHART"
    n.poll_once()
    n.poll_once()
    assert rec.sent == [MESSAGES[HELD], MESSAGES[NEW_CHART]]


def test_hold_approved_within_one_poll_texts_only_confirmed():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    api.checkin("intake-1", "LINKED")
    api.items = [handoff("pair-1", "intake-1", status="LINKED"), handoff("pair-2", "intake-1")]
    n.poll_once()
    n.poll_once()
    assert rec.sent == [MESSAGES[CONFIRMED]]


def test_second_checkin_texts_again():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    hold(api, "intake-1", "pair-1")
    n.poll_once()
    hold(api, "intake-2", "pair-3")
    n.poll_once()
    assert rec.sent == [MESSAGES[HELD], MESSAGES[HELD]]


def test_reset_rearms_every_milestone():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()

    def scripted_run():
        hold(api, "intake-1", "pair-1")
        n.poll_once()
        api.set_status("LINKED")
        n.poll_once()
        api.checkin("intake-2", "NEW_CHART")
        n.poll_once()

    scripted_run()
    # Reset: a new demo session, state truncated, then the same scripted check-ins again.
    # Even with identical ids, the new session makes them new.
    api.reset("session-2")
    n.poll_once()
    scripted_run()
    once = [MESSAGES[HELD], MESSAGES[CONFIRMED], MESSAGES[NEW_CHART]]
    assert rec.sent == once + once
    assert any("reset" in line for line in rec.lines)


def test_reset_between_the_reads_does_not_double_text():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    real_call = api.__class__.__call__
    flipped = {"done": False}

    def racing_fetch(url: str) -> object:
        body = real_call(api, url)
        if url.endswith(SESSION_PATH) and not flipped["done"]:
            # Reset and a fast scripted check-in land right after the first session read.
            flipped["done"] = True
            api.reset("session-2")
            hold(api)
        return body

    n.fetch = racing_fetch
    for _ in range(4):
        n.poll_once()
    assert rec.sent == [MESSAGES[HELD]]


def test_milestones_reached_while_the_api_was_down_at_start_are_texted():
    api, rec = FakeApi(), Recorder()
    api.down = True
    n = make_notifier(api, rec)
    n.poll_once()
    api.down = False
    hold(api)
    assert n.poll_once() == 1
    assert n.poll_once() == 0
    assert not any("reset" in line for line in rec.lines)


def test_milestones_already_reached_at_start_are_not_announced():
    api, rec = FakeApi(), Recorder()
    hold(api, "intake-1", "pair-1")
    api.checkin("intake-2", "LINKED")
    api.items.append(handoff("pair-2", "intake-2", status="LINKED"))
    api.checkin("intake-3", "NEW_CHART")
    n = make_notifier(api, rec)
    for _ in range(3):
        n.poll_once()
    assert rec.sent == []
    assert any("3 already past a milestone" in line for line in rec.lines)


def test_rejected_or_match_run_pairs_never_text():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    api.checkin("intake-1", "RELEASED")
    match_run = handoff("pair-2", None, status="LINKED") | {"origin": "MATCH_RUN"}
    api.items = [handoff("pair-1", "intake-1", status="REJECTED"), match_run]
    n.poll_once()
    n.poll_once()
    assert rec.sent == []


def test_events_are_read_from_the_demo_session_start():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    first = next(u for u in api.urls if u.startswith(API + EVENTS_PATH))
    assert dict(urllib.parse.parse_qsl(first.partition("?")[2]))["since"] == T0.isoformat()


class PagedEventsApi(FakeApi):
    """Pages the event feed 200 at a time, newest first, like the real cursor."""

    def __call__(self, url: str) -> object:
        path, _, raw_query = url.removeprefix(API).partition("?")
        if path != EVENTS_PATH:
            return super().__call__(url)
        self.urls.append(url)
        rows = sorted(self.events, key=lambda e: e["ts"], reverse=True)
        start = int(dict(urllib.parse.parse_qsl(raw_query)).get("cursor", 0))
        end = start + 200
        return {"items": rows[start:end], "nextCursor": str(end) if end < len(rows) else None}


def test_a_new_chart_behind_a_long_event_backlog_is_still_found():
    api, rec = PagedEventsApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    api.checkin("intake-9", "NEW_CHART")  # the oldest event in this window
    for i in range(2_500):  # a match run's PAIR_SCORED events land after it, more than ten pages
        ts = (api.created_at + timedelta(seconds=2, microseconds=i + 1)).isoformat()
        api.events.append({"ts": ts, "eventType": "PAIR_SCORED", "intakeSessionId": None})
    n.poll_once()
    n.poll_once()
    assert rec.sent == [MESSAGES[NEW_CHART]]


def test_api_down_does_not_crash_and_recovers():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    api.down = True
    for _ in range(5):
        assert n.poll_once() == 0
    assert sum("not reachable" in line for line in rec.lines) == 1  # quiet: one line, not one per poll
    api.down = False
    hold(api)
    assert n.poll_once() == 1


def test_no_session_yet_is_not_an_outage():
    api, rec = FakeApi(), Recorder()
    api.session_id = None
    n = make_notifier(api, rec)
    n.poll_once()
    hold(api)
    assert n.poll_once() == 1


def test_malformed_payload_is_treated_as_unavailable():
    rec = Recorder()

    def fetch(url: str) -> object:
        return {"id": "s"} if url.endswith(SESSION_PATH) else {"unexpected": True}

    n = Notifier(fetch=fetch, send=rec.send, api_base=API, log=rec.log)
    assert n.poll_once() == 0
    assert rec.sent == []


def test_texts_contain_no_field_from_the_record():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    item = handoff("3f1c9e1a-0000-4000-8000-000000000001", "9a7b6c5d-0000-4000-8000-000000000002")
    api.checkin(item["intakeSessionId"], "PENDING_REGISTRAR")
    api.items = [item]
    n.poll_once()
    api.set_status("LINKED")
    n.poll_once()
    api.checkin("5e4d3c2b-0000-4000-8000-000000000003", "NEW_CHART")
    n.poll_once()
    assert rec.sent == [MESSAGES[HELD], MESSAGES[CONFIRMED], MESSAGES[NEW_CHART]]

    def values(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                yield from values(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from values(v)
        elif obj is not None:
            yield str(obj)

    payload_values = set(values(item)) | set(values(api.events))
    for text in rec.sent:
        for value in payload_values:
            assert value not in text
    for text in MESSAGES.values():
        assert text.startswith("CheckMate: ") and not any(ch.isdigit() for ch in text)


def test_real_http_get_against_a_closed_port_raises_api_unavailable():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with pytest.raises(ApiUnavailable):
        http_get_json(f"http://127.0.0.1:{port}{SESSION_PATH}")


class _StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(404 if self.path.endswith(SESSION_PATH) else 500)
        self.end_headers()

    def log_message(self, *args):  # keep test output quiet
        pass


def test_real_http_error_statuses_map_to_not_found_and_unavailable():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StatusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(notify.NotFound):
            http_get_json(base + SESSION_PATH)
        with pytest.raises(ApiUnavailable) as caught:
            http_get_json(base + PAIRS_PATH)
        assert not isinstance(caught.value, notify.NotFound)
    finally:
        server.shutdown()
        server.server_close()


def test_dry_run_never_calls_osascript():
    def runner(args, timeout):
        raise AssertionError("osascript must not run in dry run")

    lines: list[str] = []
    for recipient in (None, Recipient("handle", FAKE_NUMBER), Recipient("contact", "Test Person")):
        send = make_sender(Config(API, True, recipient), runner=runner, log=lines.append)
        send(MESSAGES[HELD])
    assert len(lines) == 3 and all(MESSAGES[HELD] in line for line in lines)
    assert not any(FAKE_NUMBER in line for line in lines)


def test_dry_run_is_the_default():
    config = load_config({})
    assert config.dry_run is True
    assert config.api_base == "http://127.0.0.1:8000"
    assert config.recipient is None
    assert load_config({"NOTIFY_DRY_RUN": "1", "NOTIFY_IMESSAGE_TO": FAKE_NUMBER}).dry_run is True


def test_live_mode_needs_exactly_one_recipient():
    with pytest.raises(ConfigError):
        load_config({"NOTIFY_DRY_RUN": "0"})
    with pytest.raises(ConfigError):
        load_config({"NOTIFY_DRY_RUN": "0", "NOTIFY_IMESSAGE_TO": FAKE_NUMBER, "NOTIFY_IMESSAGE_TO_CONTACT": "A B"})
    config = load_config({"NOTIFY_DRY_RUN": "0", "NOTIFY_IMESSAGE_TO_CONTACT": "Test Person"})
    assert config.dry_run is False and config.recipient == Recipient("contact", "Test Person")


def test_recipient_and_text_are_passed_as_argv():
    for recipient, script in (
        (Recipient("handle", FAKE_NUMBER), notify.HANDLE_SCRIPT),
        (Recipient("contact", "Test Person"), notify.CONTACT_SCRIPT),
    ):
        assert osascript_args(recipient, MESSAGES[HELD]) == ["osascript", str(script), recipient.value, MESSAGES[HELD]]
        source = script.read_text()
        assert "on run argv" in source and recipient.value not in source


def test_recipient_repr_hides_the_value():
    assert FAKE_NUMBER not in repr(Recipient("handle", FAKE_NUMBER))


def completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["osascript"], returncode=returncode, stdout=stdout, stderr=stderr)


def live(recipient: Recipient, runner, lines: list[str]):
    return make_sender(Config(API, False, recipient), runner=runner, log=lines.append)


def run_one_hold(send, lines: list[str]) -> int:
    api = FakeApi()
    n = Notifier(fetch=api, send=send, api_base=API, log=lines.append)
    n.poll_once()
    api.items = [handoff("pair-1")]
    return n.poll_once()


def test_contact_path_never_prints_the_resolved_number(capsys):
    calls: list[list[str]] = []
    outcomes = [
        completed(0, stdout=FAKE_NUMBER + "\n", stderr=FAKE_NUMBER),
        completed(1, stderr=f'execution error: Messages got an error: Can\'t get participant "{FAKE_NUMBER}". (-1728)'),
        completed(1, stderr=f"execution error: {FAKE_NUMBER} not authorized (-1743)"),
    ]

    def runner(args, timeout):
        calls.append(args)
        return outcomes[len(calls) - 1]

    lines: list[str] = []
    send = live(Recipient("contact", "Test Person"), runner, lines)
    for _ in outcomes:
        run_one_hold(send, lines)
    out = capsys.readouterr()
    assert len(calls) == 3
    assert all(FAKE_NUMBER not in line for line in lines)
    assert FAKE_NUMBER not in out.out and FAKE_NUMBER not in out.err
    assert any("-1728" in line for line in lines) and any("Automation" in line for line in lines)


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("execution error: contact not found (4101)", "contact not found"),
        ("execution error: no phone (4102)", "no phone"),
    ],
)
def test_contact_failures_print_only_the_reason(stderr, expected):
    lines: list[str] = []
    send = live(Recipient("contact", "Test Person"), lambda args, timeout: completed(1, stderr=stderr), lines)
    assert run_one_hold(send, lines) == 0
    assert lines[-1] == expected


def test_osascript_failure_prints_one_line_and_keeps_running():
    calls: list[list[str]] = []

    def runner(args, timeout):
        calls.append(args)
        return completed(1, stderr="execution error: Messages got an error (-1700)")

    lines: list[str] = []
    send = live(Recipient("handle", FAKE_NUMBER), runner, lines)
    api = FakeApi()
    n = Notifier(fetch=api, send=send, api_base=API, log=lines.append)
    n.poll_once()
    api.items = [handoff("pair-1")]
    for _ in range(5):
        n.poll_once()  # never raises, never retries the same hold
    assert len(calls) == 1
    assert sum("Send failed" in line for line in lines) == 1
    assert all(FAKE_NUMBER not in line for line in lines)


@pytest.mark.parametrize("exc", [subprocess.TimeoutExpired(cmd="osascript", timeout=60), FileNotFoundError()])
def test_osascript_timeout_or_missing_does_not_crash(exc):
    def runner(args, timeout):
        raise exc

    lines: list[str] = []
    send = live(Recipient("handle", FAKE_NUMBER), runner, lines)
    assert run_one_hold(send, lines) == 0
    assert lines and all(FAKE_NUMBER not in line for line in lines)


def test_live_send_passes_the_fixed_message():
    calls: list[list[str]] = []

    def runner(args, timeout):
        calls.append(args)
        return completed(0)

    lines: list[str] = []
    send = live(Recipient("handle", FAKE_NUMBER), runner, lines)
    assert run_one_hold(send, lines) == 1
    assert calls == [["osascript", str(notify.HANDLE_SCRIPT), FAKE_NUMBER, MESSAGES[HELD]]]
    assert all(FAKE_NUMBER not in line for line in lines)
