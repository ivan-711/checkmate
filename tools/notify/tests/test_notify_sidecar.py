"""Unit tests for the optional registrar notifier. The HTTP fetch and the osascript runner are fakes:
nothing here reads a real API or sends a message."""

from __future__ import annotations

import socket
import subprocess

import pytest

from tools.notify import notify
from tools.notify.notify import (
    MESSAGE,
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
    """Serves /sessions/current and /candidate-pairs from in-memory state; can be switched off."""

    def __init__(self) -> None:
        self.session_id: str | None = "session-1"
        self.items: list[dict] = []
        self.down = False
        self.urls: list[str] = []

    def __call__(self, url: str) -> object:
        self.urls.append(url)
        if self.down:
            raise ApiUnavailable("ConnectionRefusedError")
        if url == API + SESSION_PATH:
            if self.session_id is None:
                raise notify.NotFound(url)
            return {"id": self.session_id, "scenarioId": "hero"}
        if url.startswith(API + PAIRS_PATH + "?"):
            return {"items": list(self.items), "nextCursor": None}
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


def test_new_handoff_sends_once():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    assert n.poll_once() == 0  # baseline: nothing waiting
    api.items = [handoff("pair-1")]
    assert n.poll_once() == 1
    assert rec.sent == [MESSAGE]
    assert any("origin=FRONTDESK_HANDOFF" in u and "status=PROPOSED" in u for u in api.urls)


def test_same_handoff_does_not_resend():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    # one check-in held against two blocking candidates: two pairs, one intake session, one notice
    api.items = [handoff("pair-1", "intake-1"), handoff("pair-2", "intake-1")]
    for _ in range(5):
        n.poll_once()
    assert rec.sent == [MESSAGE]


def test_second_checkin_sends_again():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    api.items = [handoff("pair-1", "intake-1")]
    n.poll_once()
    api.items.append(handoff("pair-3", "intake-2"))
    n.poll_once()
    assert rec.sent == [MESSAGE, MESSAGE]


def test_after_reset_the_same_scripted_checkin_sends_again():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    api.items = [handoff("pair-1", "intake-1")]
    n.poll_once()
    # Reset: a new demo session, state truncated, then the same scripted check-in is held again.
    # Even if the ids came back identical, the new session makes it a new hold.
    api.session_id, api.items = "session-2", []
    n.poll_once()
    api.items = [handoff("pair-1", "intake-1")]
    n.poll_once()
    n.poll_once()
    assert rec.sent == [MESSAGE, MESSAGE]


def test_holds_already_waiting_at_start_are_not_announced():
    api, rec = FakeApi(), Recorder()
    api.items = [handoff("pair-1")]
    n = make_notifier(api, rec)
    n.poll_once()
    n.poll_once()
    assert rec.sent == []


def test_decided_or_match_run_pairs_never_notify():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    linked = handoff("pair-1", "intake-1", status="LINKED")
    match_run = handoff("pair-2", None) | {"origin": "MATCH_RUN"}
    api.items = [linked, match_run]
    n.poll_once()
    assert rec.sent == []


def test_api_down_does_not_crash_and_recovers():
    api, rec = FakeApi(), Recorder()
    api.down = True
    n = make_notifier(api, rec)
    for _ in range(5):
        assert n.poll_once() == 0
    assert sum("not reachable" in line for line in rec.lines) == 1  # quiet: one line, not one per poll
    api.down = False
    n.poll_once()  # baseline once the API is back
    api.items = [handoff("pair-1")]
    assert n.poll_once() == 1


def test_no_session_yet_is_not_an_outage():
    api, rec = FakeApi(), Recorder()
    api.session_id = None
    n = make_notifier(api, rec)
    n.poll_once()
    api.items = [handoff("pair-1")]
    assert n.poll_once() == 1


def test_malformed_payload_is_treated_as_unavailable():
    rec = Recorder()

    def fetch(url: str) -> object:
        return {"id": "s"} if url.endswith(SESSION_PATH) else {"unexpected": True}

    n = Notifier(fetch=fetch, send=rec.send, api_base=API, log=rec.log)
    assert n.poll_once() == 0
    assert rec.sent == []


def test_real_http_get_against_a_closed_port_raises_api_unavailable():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with pytest.raises(ApiUnavailable):
        http_get_json(f"http://127.0.0.1:{port}{SESSION_PATH}")


def test_dry_run_never_calls_osascript():
    def runner(args, timeout):
        raise AssertionError("osascript must not run in dry run")

    lines: list[str] = []
    for recipient in (None, Recipient("handle", FAKE_NUMBER), Recipient("contact", "Test Person")):
        send = make_sender(Config(API, True, recipient), runner=runner, log=lines.append)
        send(MESSAGE)
    assert len(lines) == 3 and all(MESSAGE in line for line in lines)
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


def test_message_text_contains_no_field_from_the_record():
    api, rec = FakeApi(), Recorder()
    n = make_notifier(api, rec)
    n.poll_once()
    item = handoff("3f1c9e1a-0000-4000-8000-000000000001", "9a7b6c5d-0000-4000-8000-000000000002")
    api.items = [item]
    n.poll_once()
    assert rec.sent == [MESSAGE]

    def values(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                yield from values(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from values(v)
        elif obj is not None:
            yield str(obj)

    for value in values(item):
        if value not in ("REVIEW", "PROPOSED", "FRONTDESK_HANDOFF"):  # enum words, not record content
            assert value not in rec.sent[0]
    assert "FRONTDESK_HANDOFF" not in MESSAGE and "PROPOSED" not in MESSAGE


def test_recipient_and_text_are_passed_as_argv():
    for recipient, script in (
        (Recipient("handle", FAKE_NUMBER), notify.HANDLE_SCRIPT),
        (Recipient("contact", "Test Person"), notify.CONTACT_SCRIPT),
    ):
        assert osascript_args(recipient, MESSAGE) == ["osascript", str(script), recipient.value, MESSAGE]
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
    assert calls == [["osascript", str(notify.HANDLE_SCRIPT), FAKE_NUMBER, MESSAGE]]
    assert all(FAKE_NUMBER not in line for line in lines)
