# CheckMate

Check-in plus match. A front-desk intake agent that checks patients in (Spanish or English) behind a deterministic policy gate, and an identity-resolution engine that reconnects a patient's records filed under different identities, requires recorded human approval for every link, and shows the safety fact that was invisible while the records were apart.

Built at HackGB 2026 (UW-Green Bay, October 17 to 18) by a team of two. **Not for clinical use. Synthetic data only.**

## How we used AI

We used coding and research agents; we reviewed, integrated, and evaluated what they produced. This use is disclosed per commit (every commit carries the `[AI-assisted]` tag) and here.

At build time:
- Coding agents built each lane in its own git worktree from a one-page build brief (`CLAUDE.md`, mirrored as `AGENTS.md`) and the lane's spec section.
- A paired adversarial reviewer agent reviewed every lane: it ran the app and the acceptance script, wrote tests meant to fail, and posted PASS or BLOCK on the pull request.
- Codex (read-only sandbox) and GitHub Copilot code review ran on every pull request.
- The evaluation harness ran on every merge to `main` and posts per-band precision and recall with n.
- A human clicked every merge. No agent merges.

At runtime, separately: Gemini runs the intake conversation, language handling and tool arguments. Matching, the policy gate, the allergy rule and the approval are deterministic code or a human decision. No language model sits on the decision path.

All design documents (PRD, architecture, evaluation plan, UX spec) were written before the event and shown to the organizers' rule; every line of code, every migration, and every prompt file in this repository was written after 12:00 CT on 2026-10-17. Confirmed with the organizers at the 11:00 opening.

## How to run

Requires Docker. From the repository root:

```sh
make up
```

`make up` builds and starts the database and the API (`Makefile`, `docker-compose.yml`); the API container applies the migrations before it starts (`backend/Dockerfile`), so the API can take a few seconds to answer after `make up` returns. Then open http://127.0.0.1:8000/api/v1/health and expect `"db":"UP"` (`backend/app/main.py`, `contracts/models/health.py`).

`POST /api/v1/sessions` with `{"scenarioId": "hero"}` starts a demo session (`backend/api/sessions.py`). Under `make up` it loads the placeholder fixture hero from `contracts/fixtures/scenario.json`: `CHECKMATE_HERO_SOURCE` defaults to `fixture` and `docker-compose.yml` does not set it (`backend/scenarios/loader.py`). The `corpus` source also needs the hero export under `data/scenarios/hero/`, which is not on `main` yet.

To load the synthetic corpus into the compose database (requires `uv`):

```sh
uv run python data/download.py
uv run python -m backend.ingest.cli load --seed 20261017
```

`data/download.py` fetches the Synthea November 2021 sample into the gitignored `data/raw` and stops if a file's SHA-256 differs from `data/HASHES.json`. The loader parses that sample, runs the corruption generator for the seed, and writes the records to the database at `DATABASE_URL` (default `127.0.0.1:5432`); loading the same seed again adds nothing (`backend/ingest/cli.py`).

To drop the synthetic database and start over:

```sh
make down-v
make up
```

`make down-v` removes the database volume (`Makefile`); the next `make up` recreates it and reapplies the migrations (`backend/Dockerfile`). The tables then hold only what the migrations seed until a session is reset (`backend/api/sessions.py`) or the loader runs again.

Compose publishes both ports on 127.0.0.1 only (`docker-compose.yml`). Routes whose lane has not merged answer `501 NOT_IMPLEMENTED` in the contract's error envelope (`contracts/api_spec.py`); the implemented ones are listed in `IMPLEMENTED` in `backend/app/main.py`.

## Architecture

What exists on `main` today. Components are added to this diagram only when their pull request merges.

```mermaid
flowchart LR
    contracts["contracts/<br/>Pydantic models, openapi.json,<br/>migrations, fixtures"]
    api["API process<br/>FastAPI, port 8000<br/>backend/app, backend/api"]
    engine["Matching and linking<br/>backend/core, backend/match,<br/>backend/link, backend/golden,<br/>backend/rule"]
    ingest["Loader CLI<br/>backend/ingest"]
    raw[("Synthea sample<br/>data/raw, gitignored")]
    db[("TimescaleDB<br/>event_log hypertable")]
    aggs["Continuous aggregates, real-time<br/>band_flow_1m<br/>review_outcomes_5m<br/>agent_gate_5m"]
    contracts -- "routes and models" --> api
    contracts -- "migrations" --> db
    api -- "match, link, rule" --> engine
    api -- "SQL over one pool" --> db
    raw --> ingest
    ingest -- "records" --> db
    db --> aggs
```

| Node | Files |
|---|---|
| contracts | `contracts/README.md`, `contracts/api_spec.py`, `contracts/openapi.json`, `contracts/models/`, `contracts/migrations/`, `contracts/fixtures/` |
| API process | `backend/app/main.py`, `backend/app/db.py`, `backend/app/config.py`, `backend/api/`, `backend/events/writer.py` |
| Matching and linking | `backend/core/` (normalize, block, features, score, band), `backend/match/seam.py`, `backend/link/` (union-find links), `backend/golden/` (golden record and timeline), `backend/rule/bl_amox_01.py` |
| Loader CLI | `backend/ingest/cli.py`, `data/download.py`, `data/HASHES.json` |
| TimescaleDB | `docker-compose.yml`, `contracts/migrations/0001_initial.sql`, `contracts/migrations/0002_provisional_thresholds.sql` |
| Continuous aggregates | `contracts/migrations/0001_initial.sql` (`materialized_only = false` on all three) |

## Repository layout

| Directory | Owner lanes (`CLAUDE.md`) | Contents on `main` |
|---|---|---|
| `contracts/` | lead session | The frozen contract, tag `contracts-v1`, plus additive routes (`contracts/README.md`) |
| `backend/` | W1, W2, W3a, W3b and wave 2 | API routes (`backend/api/`), matching core (`backend/core/`), links, golden record, timeline and rule (`backend/link/`, `backend/golden/`, `backend/rule/`), event writer (`backend/events/`), loader (`backend/ingest/`), scenario loading (`backend/scenarios/`), tests (`backend/tests/`) |
| `frontend/` | W4 and wave 2 UI lanes | Empty until W4 merges |
| `eval/` | W5, Q2, Q5 | Empty until W5 merges |
| `data/` | W1, W5 | `data/download.py` and `data/HASHES.json`; raw data stays gitignored |
| `docs/` | D1, D2, D3 | `docs/LICENSES.md`, `docs/devpost-outline.md` |
| `tools/` | Q15 | Empty |
| `.github/` | W5 | Empty until W5 merges |

## Data provenance

| Source | Use | Terms | Files |
|---|---|---|---|
| Synthea synthetic patients, November 2021 sample | Demo and development records | Apache-2.0 | Raw files are never committed (`.gitignore`: `data/synthea/`) |
| b.well public synthetic patient-matching benchmark, derived from ONC challenge data | Evaluation only, never committed or displayed | Described by the test-set authors as synthetic; terms not located | Never committed (`.gitignore`: `data/onc/`, `data/benchmark/`) |

Third-party code licenses are listed in `docs/LICENSES.md`.

## Not for clinical use

CheckMate is a synthetic-data prototype for identity reconciliation and evidence display. Flags are rule-based, cite their sources, are shown only after a person approves an identity link, and do not direct treatment. Not for clinical use. No clinician has reviewed the rule, the class table or the wording. Absence of a flag does not mean absence of a conflict.

The contract's default flag footer, `CARD_FOOTER` in `contracts/models/alerts.py`, names what the rule does not check. It also says that absence of a flag is not evidence that no conflict exists, and that no clinician reviewed the rule or its wording.

## Known limits and non-goals

- **Synthetic data only.** The database holds only synthetic records and is dropped with one command (`docker-compose.yml`, `Makefile`); source datasets are never committed (`.gitignore`).
- **Two sources at the core path:** an ER FHIR record and a clinic CSV row (`contracts/fixtures/scenario.json`).
- **Thresholds are evaluation thresholds, not clinical ones.** The current threshold set on `main` is the hand-set `provisional-1`, with no source run; it replaced the placeholder `provisional-0` (`contracts/migrations/0002_provisional_thresholds.sql`). Thresholds fit on the synthetic labeled set, reported with n, replace it as a new row. Auto-link stays off (`contracts/models/thresholds.py`).
- **No authentication.** A registrar name is a recorded label, not an authenticated identity (`contracts/models/reviews.py`).
- **One process on one laptop, bound to localhost** (`docker-compose.yml`, `Makefile`).
- **The live agent depends on the Gemini API,** with a labeled REPLAY fallback; the API starts in REPLAY (`FRONTDESK_AGENT_MODE` in `docker-compose.yml`, `backend/app/config.py`, `contracts/models/health.py`).
