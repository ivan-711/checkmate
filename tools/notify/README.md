# Patient check-in notifier (optional)

Author: Christian Flores (lead session)

A sidecar that texts the patient through iMessage at three check-in milestones. In the demo a stand-in contact (Alejandro Barojas, playing the patient) receives it; in production it would go to the number the patient typed at the kiosk. It is off unless someone starts it, and the demo works the same with or without it. Standard library only, Python 3.12, macOS for live sending.

## What it sends

One fixed text per milestone, at most once per check-in (intake session):

| Milestone | Text |
|---|---|
| Held for a registrar | CheckMate: Thanks for checking in. A registrar is confirming your record. Please stay nearby; we'll text you when it's done. |
| Confirmed by the registrar | CheckMate: You're checked in. A registrar confirmed your record. Please have a seat; someone will call your name. |
| New registration started | CheckMate: Thanks for checking in. We've started your registration; a registrar will finish it with you shortly. |

The texts are constants (`MESSAGES` in `notify.py`). No name, date of birth, id, record content or medical detail is ever read into them. The text carries no patient record data and travels through Apple's Messages service. The notifier prints no phone number: not the handle you set and not the number Contacts resolves.

## How it detects each milestone

Every 2 s it reads frozen `GET` endpoints on the running API, and nothing else:

- **Held:** `GET /api/v1/candidate-pairs?origin=FRONTDESK_HANDOFF&status=PROPOSED`. These are the pairs the identity gate creates when it denies a new chart and hands the check-in to the registrar.
- **Confirmed:** `GET /api/v1/candidate-pairs?origin=FRONTDESK_HANDOFF&status=LINKED`. The registrar approved a hand-off pair. This is the same signal that makes the intake session's registration `LINKED`.
- **New registration:** `GET /api/v1/intake-sessions/{id}` reports registration state `NEW_CHART`, meaning the gate allowed a new chart. Intake session ids come from `GET /api/v1/events` (`intakeSessionId`), read from the demo session's start and then from about 30 s before the newest event seen.
- `GET /api/v1/sessions/current`: a Reset creates a new demo session id. The notifier then forgets what it sent, so the same scripted check-in after a Reset texts again.

A check-in can produce several hand-off pairs (one per blocking candidate), so every text is keyed by intake session. A check-in that is already confirmed or has a new chart never gets a late "held" text. Milestones reached before the notifier first reads the API are not announced, so restarting it never re-texts. If the API was down when it started, every milestone it sees once the API answers is new. A poll that straddles a Reset is skipped. What it has sent lives in memory only. It never writes to the API.

## Run it

From the repository root. Dry run first (the default): it prints what it would send and sends nothing.

```bash
NOTIFY_DRY_RUN=1 uv run python -m tools.notify
```

Live, to the stand-in patient in Contacts. The AppleScript looks the number up in Contacts at send time, and the number is never printed:

```bash
NOTIFY_DRY_RUN=0 NOTIFY_IMESSAGE_TO_CONTACT="Alejandro Barojas" uv run python -m tools.notify
```

Or live, to a handle (phone number or Apple ID) supplied at run time and never committed:

```bash
NOTIFY_DRY_RUN=0 NOTIFY_IMESSAGE_TO="<handle>" uv run python -m tools.notify
```

`python3 tools/notify/notify.py` works the same way. Ctrl-C stops it.

The first live send makes macOS ask once for Automation access: for Contacts (contact name only) and for Messages. Click Allow yourself. If you miss the prompt, that send fails with one line. Do a Reset and check in again.

## Configuration (environment only)

| Variable | Default | Meaning |
|---|---|---|
| `CHECKMATE_API_BASE` | `http://127.0.0.1:8000` | The running API |
| `NOTIFY_DRY_RUN` | `1` | `0` sends; anything else only prints |
| `NOTIFY_IMESSAGE_TO_CONTACT` | unset | A Contacts name. The message goes to the first mobile number, or else the first number |
| `NOTIFY_IMESSAGE_TO` | unset | A phone number or Apple ID. Set this or the contact name, not both |

## Failure handling

- API down or not answering: one line, then it retries quietly every 2 s.
- `osascript` fails (Messages not signed in, Automation not allowed): one line, and it keeps running. Each milestone gets one attempt, so a failing send never repeats every 2 s. A send waits up to 60 s for the one-time Automation prompt, and polling pauses meanwhile. A missing contact prints only `contact not found`; a card with no number prints only `no phone`. `osascript` error output is never echoed, because it can contain the number.
- The recipient and the text reach `osascript` as arguments to `on run argv` (`send_handle.applescript`, `send_contact.applescript`). They are never spliced into script source.

## Tests

`tools/notify/tests/` runs under `uv run pytest -q` with a fake fetch and a fake `osascript` runner. Nothing in the tests reads a real API or sends a message.
