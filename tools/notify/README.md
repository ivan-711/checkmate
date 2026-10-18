# Registrar notifier (optional)

Author: Christian Flores (lead session)

A sidecar that sends the registrar's iPhone one iMessage when a kiosk check-in is held for registrar review. It is off unless someone starts it, and the demo works the same with or without it. Standard library only, Python 3.12, macOS for live sending.

## What it sends

Always this text, and nothing else:

> CheckMate: a kiosk check-in is waiting for registrar review.

The text is a fixed constant (`MESSAGE` in `notify.py`). No name, date of birth, id or record content is ever read into it. The notifier prints no phone number: not the handle you set and not the number Contacts resolves.

## How it detects a held check-in

Every 2 s it reads two frozen `GET` endpoints on the running API, and nothing else:

- `GET /api/v1/candidate-pairs?origin=FRONTDESK_HANDOFF&status=PROPOSED`: the pairs the identity gate created when it denied a new chart and handed the patient to the registrar. One check-in can create several pairs (one per blocking candidate), so it sends one message per intake session.
- `GET /api/v1/sessions/current`: the demo session id. A Reset creates a new one; the notifier then forgets what it sent, so the same scripted check-in after a Reset notifies again.

Holds already waiting when the notifier starts are not announced, so restarting it never re-buzzes. What it has sent lives in memory only. It never writes to the API.

## Run it

From the repository root. Dry run first (the default): it prints what it would send and sends nothing.

```bash
NOTIFY_DRY_RUN=1 uv run python -m tools.notify
```

Live, to a person in Contacts (the AppleScript looks the number up in Contacts at send time; it is never printed):

```bash
NOTIFY_DRY_RUN=0 NOTIFY_IMESSAGE_TO_CONTACT="Alejandro Barojas" uv run python -m tools.notify
```

Or live, to a handle (phone number or Apple ID) supplied at run time, never committed:

```bash
NOTIFY_DRY_RUN=0 NOTIFY_IMESSAGE_TO="<handle>" uv run python -m tools.notify
```

`python3 tools/notify/notify.py` works the same way. Ctrl-C stops it.

The first live send makes macOS ask once for Automation access: for Contacts (contact name only) and for Messages. Click Allow yourself. If the prompt is missed, that send fails with one line; do a Reset and check in again.

## Configuration (environment only)

| Variable | Default | Meaning |
|---|---|---|
| `CHECKMATE_API_BASE` | `http://127.0.0.1:8000` | The running API |
| `NOTIFY_DRY_RUN` | `1` | `0` sends; anything else only prints |
| `NOTIFY_IMESSAGE_TO_CONTACT` | unset | A Contacts name; the first mobile number, else the first number, receives the message |
| `NOTIFY_IMESSAGE_TO` | unset | A phone number or Apple ID. Set this or the contact name, not both |

## Failure handling

- API down or not answering: one line, then it retries quietly every 2 s.
- `osascript` fails (Messages not signed in, Automation not allowed): one line, and it keeps running. Each hold gets one attempt, so a failing send never repeats every 2 s. A missing contact prints only `contact not found`; a card with no number prints only `no phone`. `osascript` error output is never echoed, because it can contain the number.
- The recipient and the text reach `osascript` as arguments to `on run argv` (`send_handle.applescript`, `send_contact.applescript`); they are never spliced into script source.

## Tests

`tools/notify/tests/` runs under `uv run pytest -q` with a fake fetch and a fake `osascript` runner; nothing in the tests reads a real API or sends a message.
