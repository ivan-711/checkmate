# CheckMate

CheckMate is check-in plus match. A front-desk intake agent checks patients in, in Spanish or English, behind a deterministic rules gate. An identity-resolution engine reconnects a patient's records that were filed under different identities. Every link needs a recorded human approval, and once the records are joined the app shows the safety fact that could not be seen while they were apart.

Author: Christian Flores (docs) · 2026-10-18

Built at HackGB 2026 (UW-Green Bay, October 17 to 18) by a team of two. **Not for clinical use. Synthetic data only.**

## How we used AI

We used coding and research agents, and we reviewed, integrated and evaluated what they produced. We disclose this in this section and on our commits: every commit we wrote carries the `[AI-assisted]` tag. The only commits on `main` without it are GitHub's initial commit and three merge commits that kept git's default message.

At build time:
- Coding agents built each lane in its own git worktree from a one-page build brief (`CLAUDE.md`, mirrored as `AGENTS.md`) and the lane's spec section.
- A paired adversarial reviewer agent reviewed lane pull requests: it ran the app and the acceptance script, wrote tests meant to fail, and posted PASS or BLOCK on the pull request.
- Codex, in a read-only sandbox, reviewed several pull requests. The build brief also called for GitHub Copilot code review, but it did not run on any merged pull request.
- The evaluation harness ran on most merges to `main` once CI landed and posted per-band precision and recall with n as a commit comment. A few runs were cancelled by a newer push or stopped on a failed job and posted nothing.
- A human clicked every merge until 17:15 CT on Saturday. After that, the lead orchestration session merged pull requests under the owner's standing authorization, normally once CI was green, the paired reviewer had posted PASS and a second review had passed. On the subset of pull requests Codex reviewed, that second review was Codex's cross-review; on others it was the lead session's own review. Two small pull requests on Sunday morning (the evaluation sweep and the never-say list) merged on green CI and the lead session's own reading of the diff, with the owner's approval. Either of us could still click merge.

Separately, the running app can use a model. In `LIVE` mode Gemini runs the intake conversation, the language handling and the tool arguments (`backend/frontdesk/gemini.py`). The API starts in `REPLAY` mode (`backend/app/config.py`, `docker-compose.yml`), where a committed transcript stands in for the model and plays through the real gate, matcher and database (`backend/frontdesk/replay.py`). That transcript is marked `AUTHORED`: the team wrote it from the call shapes a Gemini spike verified; it is not a recorded model run (`data/scenarios/hero/frontdesk_transcript.json`). In every mode, matching, the rules gate, the allergy rule and the approval are deterministic code or a human decision, so no language model is on the decision path.

All design documents (PRD, architecture, evaluation plan, UX spec) were written before the event and shown to the organizers' rule. Every line of code, every migration and every prompt file in this repository was written after 12:00 CT on 2026-10-17. We confirmed this arrangement with the organizers at the 11:00 opening.

## What it does

The app is one screen, the Desk at `/`: the patient kiosk on the left, the registrar's stage on the right (the records and the decision column), and an Activity strip with a Human reviews meter (`frontend/src/app/page.tsx`, `frontend/src/components/desk/DeskScreen.tsx`). The header shows a story stepper (Check-in, Rules gate, Compare, Link, Clinician flag), the mode badge, **Commands ⌘K** and **Reset demo** (`frontend/src/components/ui/Header.tsx`, `frontend/src/lib/desk.ts`). The kiosk also runs on its own at `/kiosk`. The Work queue is at `/queue`, opened from the command bar, and each row opens a Case page at `/queue/<pair id>`. The old `/frontdesk` address redirects to `/`.

### The kiosk: a bilingual check-in agent behind a rules gate

The patient kiosk takes a typed check-in (name, date of birth, phone, address) in English or Spanish; a language toggle switches the kiosk text and the check-in language (`frontend/src/components/frontdesk/KioskPane.tsx`, `copy.ts`). The agent has three tools: `search_patients`, `propose_new_chart` and `attach_history` (`contracts/tools/`). It never writes anything itself: every tool call goes first to a deterministic gate, policy `frontdesk-gate/1` (`backend/policy/`, `contracts/version.py`), which:

- validates the arguments and checks that every identity field the model filled is grounded in the patient's own words: the model must quote what the patient typed, and the value must agree with that quote after case and accent folding (`backend/policy/args.py`);
- finds candidate charts itself, from blocking keys recomputed from the arguments, and scores them with the same matcher and the same current thresholds the registrar sees; the model never supplies candidates (`backend/policy/gate.py`);
- answers `ALLOW`, or `DENY` with a reason code, from a 13-row decision table (`backend/policy/decide.py`);
- fails closed: if the matcher or the database fails, the turn degrades to a fixed template line in the session's language and nothing is written (`backend/policy/gate.py`, `backend/frontdesk/executor.py`, `backend/frontdesk/templates.py`).

When an existing chart scores REVIEW or higher, the gate denies a new chart. If a candidate in the `REVIEW` or `AUTO_LINK` band has not been linked or rejected by a person, `propose_new_chart` is denied with `CANDIDATE_IN_REVIEW_OR_HIGHER` (`backend/policy/decide.py`) and no chart is created. The check-in is recorded as an intake record, and for each blocking candidate the executor writes a candidate pair with origin `FRONTDESK_HANDOFF` and a `PROPOSED` decision, which hands the check-in to a registrar (`backend/frontdesk/executor.py`, `backend/chart_store/writes.py`). The check-in's registration state then reads `PENDING_REGISTRAR`, derived from the database on every read (`backend/frontdesk/registration.py`).

On screen, the kiosk lists what FrontDesk did in the turn and ends with the gate's result. A denied new chart shows the amber gate card, "A chart may already be yours" (label "Identity gate · denied"), with the candidate's display score. Under **Details** it shows the candidate's band, up to five evidence rows, a Rule result tag and a masked candidate (no name, date, address or phone of the other chart). The denied tool and the policy id are carried on the card's data attributes (`frontend/src/components/frontdesk/GateCard.tsx`). The kiosk then tells the patient "Held for a registrar. Please have a seat; they'll confirm it with you." (`frontend/src/components/frontdesk/copy.ts`). **Start over** in the kiosk runs the same full demo reset as **Reset demo** (`frontend/src/components/frontdesk/KioskPane.tsx`).

Other guards on the agent:
- Agent text that contains a never-say phrase, or claims a chart was created when no chart was, is replaced by the template line (`backend/frontdesk/loop.py`, `backend/frontdesk/prompts/never-say.txt`, `backend/frontdesk/prompts/effect-claims.txt`).
- Limits per turn and session: a 10 s timeout per model call, a 25 s budget per typed turn, at most 6 tool calls per turn and 12 turns per session; after 2 degraded turns in a row the session answers with the template without calling the model (`contracts/version.py`, `backend/frontdesk/loop.py`).
- Every gate decision writes an `agent_tool_call` audit row and an `AGENT_TOOL_CALLED` event (`backend/frontdesk/executor.py`). `GET /api/v1/metrics/tiles` reads allowed and denied counts from the `agent_gate_5m` continuous aggregate (`backend/api/tiles.py`). The Desk does not show that tile; its Activity strip lists the latest events (`frontend/src/components/desk/ActivityStrip.tsx`).

### The registrar decides, and the flag appears after approval

The right side of the Desk is the registrar's stage. When the gate holds a check-in, the decision column reads "Why the gate held this check-in" and offers **Resolve identity** (`frontend/src/components/desk/DecisionColumn.tsx`). Resolve identity starts a match run, `POST /api/v1/match-runs`, which blocks, scores and bands the loaded records. The hero's ER and Clinic pair then appears with its band, the evidence rail (each feature's contribution to the score) and **Approve link** / **Reject** (`frontend/src/components/case/EvidenceRail.tsx`, `frontend/src/components/case/ReviewPanel.tsx`). The demo hero hands off two pairs: the new check-in against the ER chart and against the Clinic chart (`frontend/e2e/frontdesk.api.spec.ts`).

- **Approve link** opens "Link these two records?" with the registrar's name, an optional note and **Also attach the kiosk check-in**, ticked by default. **Confirm link** records the link and, with that box ticked, a second approval that attaches the held check-in (`frontend/src/components/case/ReviewPanel.tsx`, `frontend/e2e/decision.api.spec.ts`).
- A decision goes through the review endpoint, `POST /api/v1/candidate-pairs/{pair_id}/reviews`, the same one the Case page uses, with an `Idempotency-Key`, and appends a new decision version; decisions are never edited in place (`backend/api/reviews.py`).
- The registrar picks a name from a fixed list; it is recorded as a label, not an authenticated identity (`contracts/version.py`, `contracts/models/reviews.py`).
- A reject needs a reason. `DIFFERENT_PERSON` writes a `not_a_match` row, and an approval of another pair that would put those two records in one entity is refused with `CANNOT_LINK_CONFLICT`; `INSUFFICIENT_EVIDENCE` writes none (`backend/api/reviews.py`).
- An approval links the records into one entity and builds the golden record at read time, with a crosswalk to the source of every value (`backend/link/`, `backend/golden/`). Rule BL-AMOX-01 then runs on the linked entity (`backend/rule/bl_amox_01.py`): it looks for a penicillin-class allergy and an active penicillin-class order on the same patient. Only the approval that brings the allergy and the order into one entity raises the flag (`frontend/e2e/decision.api.spec.ts`).
- On the Desk, the two records then join into one record that names the other sources' spellings ("Also recorded as …"), the decision column shows the timeline, and the flag rises from the join. The kiosk tells the patient "You're checked in" (`frontend/src/components/record/Joined.tsx`, `frontend/src/components/record/Notice.tsx`, `frontend/src/components/frontdesk/KioskPane.tsx`).

The flag is neutral by design: it says "Flagged for clinician review", carries the rule id and version, a "constructed scenario" chip when the allergy and order were added for the demo, a Rule result tag, and a **Details** section with the card text, the drug-label citation when the flag has one, and the rule's limits. It has no alert role (`frontend/src/components/record/Notice.tsx`, `frontend/src/components/case/FlagCard.tsx`). The rule runs only after an approval: on the Desk a rejected pair reads "Kept apart" (`frontend/src/components/desk/DecisionColumn.tsx`), and on the Case page a rejected link shows "No safety check ran" (`frontend/src/lib/flagState.ts`).

### Work queue and Case page

The Work queue at `/queue` lists every scored candidate pair, filterable by band and decision status; after Resolve identity it shows the match run's funnel (`frontend/src/components/queue/WorkQueue.tsx`). Each row opens a Case page at `/queue/<pair id>` with the two source records, **Resolve identity**, the evidence rail and the review controls. After an approval the two cards collapse into one golden record with crosswalk chips, the timeline shows events from both sources, and the flag card appears (`frontend/src/components/case/CaseScreen.tsx`).

How the engine scores (`backend/core/`):
- Blocking: phonetic surname plus birth year, exact date of birth, swapped day and month, phone last 7 digits, ZIP plus initial; placeholder values never form a key (`backend/core/block.py`, `backend/core/placeholders.py`).
- Features: name similarities with and without accents, a nickname table, date-of-birth transposition and one-digit edits, sex, phone, address and ZIP (`backend/core/features.py`).
- Score: a logistic scorer whose evidence is each feature's contribution in logit units. **The demo weights are hand-set**, scorer version `handset-1` (`backend/core/score.py`, `backend/core/weights/handset-1.json`). They are not trained and not calibrated; `is_calibrated` is false on every score. A training script exists (`backend/core/train.py`), but no trained weights are committed and the app does not use one.
- Bands are cut on the raw score `s`: below `c_low` `KEEP_SEPARATE`, from `c_low` to below `c_high` `REVIEW`, at or above `c_high` `AUTO_LINK` (`backend/core/band.py`). The current threshold row is `provisional-1`, hand-set at `c_low` 0.0 and `c_high` 4.0, with auto-link disabled (`contracts/migrations/0002_provisional_thresholds.sql`). Negative rules (sex conflict, birth-year gap over 2, twin, parent and child, generation suffix, placeholder name or date) can only demote `AUTO_LINK` to `REVIEW` (`backend/core/band.py`).
- The score shown on the gate card and in the decision column is the display-only `p`. With no Platt map fitted, `p` is the plain sigmoid of the raw score; it is not a calibrated probability (`backend/core/score.py`).
- The demo hero pair scores a raw `s` of 2.15, band `REVIEW` (`data/scenarios/hero/hero.json`).

Resets, match runs, scored pairs, decisions, alerts and agent actions are appended to `event_log`, a TimescaleDB hypertable. `GET /api/v1/metrics/tiles` reads real-time continuous aggregates over it: `band_flow_1m`, `review_outcomes_5m`, `agent_gate_5m` (`contracts/migrations/0001_initial.sql`, `backend/api/tiles.py`).

## The demo, in order

Run the demo setup under [How to run](#how-to-run) first, then open http://127.0.0.1:3000/ (the Desk).

1. **Reset demo** (top right). The API clears the demo state, reloads the hero scenario and records `DEMO_RESET`; the event log is kept (`backend/api/sessions.py`). The kiosk holds Send and "Use this" until the reset has finished (`frontend/e2e/frontdesk.api.spec.ts`).
2. **Use this**. Under "Demo line", the kiosk offers the hero's check-in from the replay transcript; **Use this** puts it in the message box (`frontend/src/data/demoScript.ts`). Switch the kiosk to Español first for the Spanish line ("Usar este").
3. **Send**. FrontDesk reads the check-in and asks to create a new chart. The gate checks the hero's existing charts and holds the request. The story stepper moves to Rules gate.
4. The kiosk shows the amber card "A chart may already be yours": `propose_new_chart` was denied by the identity gate, with the top existing chart's score, and "Held for a registrar". **Details** shows its band, the evidence rows and a Rule result tag. The top chart is the ER chart. The shipped scorer gives it a raw `s` of exactly 4.0, which equals `c_high`, so it is in `AUTO_LINK` and the card shows 0.98 and AUTO-LINK; the Clinic chart scores 0.65, in `REVIEW` (`backend/core/band.py`). `AUTO_LINK` counts as REVIEW or higher, so the gate denies the new chart with `CANDIDATE_IN_REVIEW_OR_HIGHER` (`backend/policy/decide.py`). Auto-link is off in the demo, so no link is made. The decision column now reads "Why the gate held this check-in", with two possible existing charts to decide.
5. **Resolve identity** (right side). The match run scores the loaded records; the hero's ER and Clinic pair appears in `REVIEW` with the evidence rail.
6. **Approve link**. In "Link these two records?", leave **Also attach the kiosk check-in** ticked, optionally add a note, then click **Confirm link** once.
7. The two records join into one record, the decision column shows the timeline, and the flag reads "Flagged for clinician review", rule `BL-AMOX-01`, with the constructed-scenario chip. **Details** shows the card text, the drug-label citation and the rule's limits. The kiosk reads "You're checked in".

For another run, press **Reset demo**, or **Start over** in the kiosk, which runs the same reset.

In `REPLAY` mode the agent's replies come only from the transcript: a typed message must match a scripted line (case, accents and spacing ignored), and anything else gets the template line (`backend/frontdesk/replay.py`).

## How to run

Requires Docker, [uv](https://docs.astral.sh/uv/) (Python 3.12, `pyproject.toml`) and Node 20 or later (`frontend/package.json`). The API and UI processes on the host bind to 127.0.0.1 (`Makefile`, `frontend/package.json`). Inside Docker the API container listens on 0.0.0.0 (`backend/Dockerfile`), and `docker-compose.yml` publishes the database and API ports only on 127.0.0.1.

### The demo setup: database in Docker, API and UI on the host

```sh
make db
DATABASE_URL=postgresql://checkmate:checkmate@127.0.0.1:5432/checkmate make migrate
uv run python data/download.py
CHECKMATE_HERO_SOURCE=corpus make api
```

- `make db` starts only the TimescaleDB container on port 5432 (`Makefile`, `docker-compose.yml`).
- `make migrate` applies the migrations; it reads `DATABASE_URL` and stops if it is not set (`contracts/migrations/apply.py`).
- `data/download.py` fetches the Synthea November 2021 sample into the gitignored `data/raw` and stops if a file's SHA-256 differs from `data/HASHES.json`.
- `make api` runs the API on http://127.0.0.1:8000 with reload (`Makefile`). `CHECKMATE_HERO_SOURCE=corpus` makes **Reset demo** load the synthetic corpus built from that sample, with the hero chosen by the hero export in `data/scenarios/hero/` and its constructed allergy and order applied (`backend/scenarios/loader.py`). The agent mode defaults to `REPLAY` (`backend/app/config.py`). The replay checks each recorded tool result's hash, and those results come from the corpus hero, so the kiosk replay needs the corpus source (`data/scenarios/hero/frontdesk_transcript.json`, `backend/frontdesk/replay.py`).

Check http://127.0.0.1:8000/api/v1/health: expect `"db":"UP"` and `"agent":"REPLAY"`. The agent field reads `DOWN` when the transcript does not load or its pins (scorer, threshold set, hero file) differ from the running engine (`backend/frontdesk/replay.py`).

Then, in a second terminal:

```sh
cd frontend
npm ci
NEXT_PUBLIC_CHECKMATE_SOURCE=api npm run dev
```

`npm run dev` first regenerates the typed API client from `contracts/openapi.json` (`predev`), then serves http://127.0.0.1:3000 (`frontend/package.json`). With `NEXT_PUBLIC_CHECKMATE_SOURCE=api` the browser calls `/api/v1` on its own origin and Next forwards it to `CHECKMATE_API_ORIGIN`, default http://127.0.0.1:8000 (`frontend/src/data/DataSourceProvider.tsx`, `frontend/next.config.ts`); the mode badge reads `LOCAL`. For a production build, set the same variable for `npm run build`, then `npm run start`.

### Other ways to run

- **UI only, no API.** `npm run dev` without `NEXT_PUBLIC_CHECKMATE_SOURCE` plays the placeholder fixture `contracts/fixtures/scenario.json` in the browser; the mode badge reads `REPLAY` and nothing is written anywhere (`frontend/src/data/fixtureSource.ts`).
- **API in Docker.** `make up` builds and starts the database and the API container; the container applies the migrations before it starts (`Makefile`, `backend/Dockerfile`). The image holds only `contracts/` and `backend/` (`backend/Dockerfile`), so Reset demo loads the fixture hero and the replay transcript is absent: `/health` reports the agent `DOWN` and kiosk turns answer with the template line. Use the demo setup above for the kiosk. `make up` and `make api` both use port 8000: run one or the other.
- **Live agent.** Put `FRONTDESK_AGENT_MODE=LIVE`, `GEMINI_API_KEY` and `GEMINI_MODEL_ID` in a `.env` file at the repository root (gitignored; read by `backend/app/config.py`) and restart the API. Without a key or a model id, live turns degrade to the template line. `AUTO` uses the live model only when a key and a model id are set and a probe answers, and `REPLAY` otherwise (`backend/frontdesk/adapters.py`). The demo runs in `REPLAY`.
- **Load the corpus without the UI.** `uv run python -m backend.ingest.cli load --seed 20261017` writes the corpus records to the database at `DATABASE_URL` (default 127.0.0.1:5432); loading the same seed again adds nothing (`backend/ingest/cli.py`).
- **Rebuild the database.** `make down-v` removes the database volume (`Makefile`); run `make db` and `make migrate` again. The data is synthetic and rebuilt from the seed.

### Tests and checks

| Command | What it runs |
|---|---|
| `make lint` | ruff over `contracts` and `backend` |
| `make openapi-check` | `contracts/openapi.json` matches the Pydantic models |
| `make test-contracts` | contract tests |
| `make test-db`, then `make test-backend` | backend tests on a throwaway test database created on the running compose database server |
| `npm run lint`, `npm run typecheck`, `npm test` (in `frontend/`) | ESLint, TypeScript, Vitest |
| `npm run e2e` (in `frontend/`) | Playwright on the fixture build. It reuses any server already on port 3000 and its specs press Reset demo, so never run it while the demo setup is serving port 3000 (`frontend/playwright.config.ts`, `frontend/e2e/smoke.spec.ts`) |
| `npm run e2e:api` (in `frontend/`) | Playwright against a running API named by `CHECKMATE_API_ORIGIN`; it presses Reset demo on that API (`frontend/playwright.api.config.ts`) |
| `npm test` (in `eval/acceptance/`) | The G16 acceptance path against the running UI and API: reset, resolve, reject, resolve, approve, flag card, event counts, review tile; it presses Reset demo (`eval/acceptance/README.md`) |

CI runs ruff, the OpenAPI snapshot check, pytest, a schemathesis contract test against an API it starts, the protected-paths check, the hero-export regeneration and fixture check, the acceptance script's type check, the frontend build and a secret scan. On every merge to `main` it also runs the evaluation harness (`.github/workflows/ci.yml`). CI and agents use only the `REPLAY` adapter; no key exists in CI.

## Evaluation

The harness measures the code the app runs: the synthetic corpus built from the Synthea sample with its hidden truth table, and the engine with the shipped `handset-1` weights, banded at the app's current threshold row (`eval/harness/product.py`, `eval/harness/current_thresholds.py`). These are descriptive numbers on synthetic data, not guarantees.

### Held-out test partition

Source: harness run 1c3f8f96, with a committed copy of the run's metrics in `docs/eval/run-1c3f8f96-metrics.json`. In that copy every cell the harness flags "do not read" has its value withheld (null). The run directory itself is in the gitignored `eval/runs/`; reproduce the run with the eval command below.

A separate gate ablation (300 scripted kiosk check-ins, gate on and off) is written up in `docs/eval/gate-ablation-300.md`, with its selection caveats.

- The run scored the development partition out of fold, then scored the test partition once. The test partition holds 144 of the 500 dependency components. They are kept out of the development scoring and the cutoff selection (manifest `regime`: "development + single test pass"; split rules in `eval/expectations/splits.json`).
- Settings: seed 20261017, scorer `handset-1`, threshold row `provisional-1` (`c_low` 0.0, `c_high` 4.0). Every band number is computed at that row; auto-link is off in the app, so the `AUTO_LINK` rows describe the band only.
- The top-level `thresholds` block in the metrics copy (`c_low` -0.35, `c_high` 0.44375, id `oof-4dc28f256de9`) is the harness's out-of-fold proposal, recorded as descriptive; this run did not use it and banded every pair at `provisional-1` (`c_low` 0.0, `c_high` 4.0), as the run manifest records.
- The run was made at commit `95be994`, an ancestor of `main`. `backend/core`, `backend/ingest` and `eval/harness` are unchanged since then, and the engine hash recorded in the run equals the hash of `backend/core` on `main`.
- Intervals are 95% percentile bootstrap intervals over dependency components, with 1000 resamples.
- A number is not reported when the harness flags it "do not read": under 30 components or under 100 pairs (`eval/harness/metrics.py`).
- The five held-out corruption families (C3, D5, L4, N5, S4) have no numbers in this run.

| Number | Value | 95% interval | n pairs | n components |
|---|---|---|---|---|
| AUTO_LINK precision | not reported (n = 15, below the reporting floor) | n/a | 15 | 11 |
| AUTO_LINK recall (STRICT, end to end) | 0.069444 | 0.031094 to 0.118489 | 216 | 125 |
| REVIEW precision | 0.903226 | 0.839791 to 0.962991 | 186 | 111 |
| REVIEW share of true pairs | 0.865979 | 0.795803 to 0.924267 | 194 | 120 |
| LENIENT recall (end to end) | 0.847222 | 0.783542 to 0.905025 | 216 | 125 |
| KEEP_SEPARATE precision | not reported (n = 72, below the reporting floor) | n/a | 72 | 33 |
| False-merge rate (auto-links) | not reported (n = 15, below the reporting floor) | n/a | 15 | 11 |
| Review burden | 0.681319 | 0.567974 to 0.794252 | 273 | 122 |
| Blocking recall | 0.898148 | 0.845794 to 0.946433 | 216 | 125 |

The STRICT row follows from the design. Auto-linking is meant to be rare: the high cutoff is chosen false-merge first, and auto-link is off in the demo (`auto_link_enabled = false`, `contracts/models/thresholds.py`), so no link is ever made without a person. The thresholds send most true pairs to a registrar (REVIEW share of true pairs 0.865979). STRICT counts only the pairs the system would link with no human, while LENIENT recall (0.847222) counts the pairs a registrar is shown. The weights are hand-set (`handset-1`) and not trained, so these are demo numbers, not a claim about a trained matcher.

What the rows mean (`eval/harness/metrics.py`):
- Strict recall counts true pairs that land in `AUTO_LINK`. Lenient recall counts true pairs that land in `AUTO_LINK` or `REVIEW`. Both are taken over all true pairs, including pairs that blocking missed.
- Review burden is the share of scored pairs that go to `REVIEW`.
- Blocking recall is the share of true pairs that blocking puts forward as candidate pairs: 194 of 216. The run itself notes that the keys were built after reading the corruption taxonomy, so this number is partly true by construction.

### Parallel evaluation sweep

`eval/sweep/` runs the harness over several seeds in parallel and reports each metric's mean and 95% interval across seeds, except a metric the harness marks do-not-read on any seed, which prints as not reported with no mean or interval; the interval is a two-sided Student t interval on the per-seed values, clipped to 0 to 1 for rates (`eval/sweep/results.py`). `--executor` chooses where the runs happen: `local` is a process pool on this machine, `modal` is Modal and needs a token from `uvx modal token new`, and `auto`, the default, uses Modal when a token is configured and the local pool otherwise (`eval/sweep/executors.py`).

```sh
uvx modal token new
uv run modal volume create checkmate-synthea-raw
uv run modal volume put checkmate-synthea-raw data/raw/zips /zips
uv run python -m eval.sweep --seeds 20261017 20261018 20261019 20261020 20261021 --scorer-versions handset-1 --tiers synthea --executor modal
```

The Modal volume holds the Synthea archives that `data/download.py` leaves in `data/raw/zips`. With `--executor local` the same sweep runs on the local pool and needs neither the token nor the volume. Each sweep writes `eval/runs/sweeps/<utc>-<sha12>/sweep.json`.

Development pass, five seeds (20261017 to 20261021), scorer `handset-1`, executor Modal, held-out families excluded; not the held-out test pass above.

| Number | Mean across seeds | 95% interval across seeds |
|---|---|---|
| AUTO_LINK precision | not reported (harness floor) | n/a |
| REVIEW precision | 0.901 | 0.864 to 0.939 |
| LENIENT recall (end to end) | 0.889 | 0.874 to 0.904 |
| KEEP_SEPARATE precision | not reported (harness floor) | n/a |
| False-merge rate (auto-links) | not reported (harness floor) | n/a |
| Review burden | 0.747 | 0.722 to 0.771 |
| Blocking recall | 0.925 | 0.913 to 0.937 |

Every seed uses the same 555-patient Synthea sample, so the interval measures variation between generated corpora only. Modal and the local pool gave identical numbers on all five seeds.

### Running the harness

The harness has no Makefile target; run it with `uv`. It needs the Synthea sample from `data/download.py`.

```sh
uv run python data/download.py
uv run python -m eval.harness.run --test-pass --seed 20261017 --out eval/runs
```

`--test-pass` adds the single test-partition pass; the held-out numbers are the `test.*` keys in `eval/runs/<run_id>/metrics.json` (`eval/harness/run.py`). On every merge to `main`, CI runs the per-merge configuration instead: `--fast`, with P0 corruption families, one seed, development components only and no test pass. CI posts that table as a commit comment (`.github/workflows/ci.yml`, `eval/expectations/config.json`). `uv run python -m eval.harness.summary eval/runs/<run_id>` renders the development numbers only.

Not measured yet: the gate suite, the injection suite and the BL-AMOX-01 case list in `eval/expectations/` are placeholders with no cases (`eval/expectations/gate_suite.json`, `injection_strings.json`, `rule_tests.json`). The rule's unit tests are in `backend/tests/rule/`.

## Architecture

The diagram shows what exists on `main` today; a component is added to it only when its pull request merges.

```mermaid
flowchart LR
    browser["Browser<br/>Next.js UI, port 3000<br/>frontend/"]
    api["API process<br/>FastAPI, port 8000<br/>backend/app, backend/api"]
    agent["FrontDesk agent loop<br/>backend/frontdesk"]
    model["Model adapter<br/>LIVE: Gemini<br/>REPLAY: committed transcript"]
    gate["Rules gate<br/>frontdesk-gate/1<br/>backend/policy"]
    writes["Chart-store writes<br/>backend/chart_store"]
    engine["Matching and linking<br/>backend/core, backend/match,<br/>backend/link, backend/golden,<br/>backend/rule"]
    ingest["Corpus loader<br/>backend/ingest, backend/scenarios"]
    raw[("Synthea sample<br/>data/raw, gitignored")]
    db[("TimescaleDB<br/>event_log hypertable")]
    aggs["Continuous aggregates, real-time<br/>band_flow_1m<br/>review_outcomes_5m<br/>agent_gate_5m"]
    contracts["contracts/<br/>Pydantic models, openapi.json,<br/>migrations, fixtures, tool schemas"]
    browser -- "/api/v1, same origin" --> api
    api -- "intake turns" --> agent
    agent -- "next step" --> model
    agent -- "every tool call" --> gate
    gate -- "candidates, scores" --> engine
    agent -- "effect, with the gate's token" --> writes
    api -- "match runs, reviews, golden record, rule" --> engine
    api -- "SQL over one pool" --> db
    writes --> db
    raw --> ingest
    ingest -- "records" --> db
    db --> aggs
    contracts -- "routes, models, migrations" --> api
```

| Node | Files |
|---|---|
| Browser | `frontend/src/app/` (the Desk at `/`, the kiosk at `/kiosk`, the Work queue and Case pages under `/queue`), `frontend/src/components/`, `frontend/src/data/` (API and fixture sources), `frontend/next.config.ts` (the `/api/v1` rewrite) |
| API process | `backend/app/main.py`, `backend/app/db.py`, `backend/app/config.py`, `backend/api/`, `backend/events/writer.py` |
| FrontDesk agent loop | `backend/frontdesk/loop.py`, `backend/frontdesk/executor.py`, `backend/frontdesk/registration.py`, `backend/frontdesk/templates.py`, `backend/frontdesk/prompts/` |
| Model adapter | `backend/frontdesk/adapters.py`, `backend/frontdesk/gemini.py` (the only module that imports the Gemini SDK), `backend/frontdesk/replay.py`, `data/scenarios/hero/frontdesk_transcript.json` |
| Rules gate | `backend/policy/args.py`, `backend/policy/gate.py`, `backend/policy/decide.py`, `backend/policy/tokens.py` |
| Chart-store writes | `backend/chart_store/writes.py`; only `backend/frontdesk/executor.py` imports it, and each write needs a token issued by the gate's decision (`backend/policy/tokens.py`) |
| Matching and linking | `backend/core/` (normalize, block, features, score, band), `backend/match/seam.py`, `backend/link/` (union-find links), `backend/golden/` (golden record and timeline), `backend/rule/bl_amox_01.py` and its offline cache `backend/rule/cache/` |
| Corpus loader | `backend/ingest/`, `backend/scenarios/loader.py`, `data/download.py`, `data/HASHES.json`, `data/scenarios/hero/` |
| TimescaleDB | `docker-compose.yml`, `contracts/migrations/0001_initial.sql`, `contracts/migrations/0002_provisional_thresholds.sql` |
| Continuous aggregates | `contracts/migrations/0001_initial.sql` (`materialized_only = false` on all three) |
| contracts | `contracts/README.md`, `contracts/api_spec.py`, `contracts/openapi.json`, `contracts/models/`, `contracts/migrations/`, `contracts/fixtures/`, `contracts/tools/` |

Contract routes whose lane has not merged answer `501 NOT_IMPLEMENTED` in the contract's error envelope (`contracts/api_spec.py`); the implemented ones are listed in `IMPLEMENTED` in `backend/app/main.py`.

## Repository layout

| Directory | Owner lanes (`CLAUDE.md`) | Contents on `main` |
|---|---|---|
| `contracts/` | lead session | The frozen contract, tag `contracts-v1`, plus additive routes (`contracts/README.md`) |
| `backend/` | W1, W2, W3a, W3b and wave 2 | API routes (`backend/api/`), FrontDesk agent loop (`backend/frontdesk/`), rules gate (`backend/policy/`), chart-store writes (`backend/chart_store/`), matching core (`backend/core/`), links, golden record, timeline and rule (`backend/link/`, `backend/golden/`, `backend/rule/`), event writer (`backend/events/`), loader (`backend/ingest/`), scenario loading (`backend/scenarios/`), tests (`backend/tests/`) |
| `frontend/` | W4 and wave 2 UI lanes | Next.js app: the Desk, the standalone kiosk, the Work queue and Case pages (`frontend/src/`), design rules (`frontend/DESIGN.md`), unit tests beside the code, Playwright specs (`frontend/e2e/`) |
| `eval/` | W5, Q2, Q5 | Evaluation harness (`eval/harness/`), protected expectations (`eval/expectations/`), the G16 acceptance script (`eval/acceptance/`), the parallel seed sweep (`eval/sweep/`), tests (`eval/tests/`, `eval/tests_r5/`) |
| `data/` | W1, W5 | `data/download.py` and `data/HASHES.json`; hero selector and export (`data/hero_select.py`, `data/hero_export.py`, `data/hero_overlay.py`), `data/fixture_check.py`, and the exported hero with the replay transcript in `data/scenarios/hero/`; raw data stays gitignored |
| `docs/` | D1, D2, D3 | `docs/LICENSES.md`, `docs/devpost-outline.md`, the committed metrics of the held-out run (`docs/eval/run-1c3f8f96-metrics.json`) |
| `tools/` | Q15, notify-imessage | The optional registrar notifier (`tools/notify/`, off unless started) |
| `.github/` | W5 | CI workflow `.github/workflows/ci.yml` |

## Data provenance

| Source | Use | Terms | Files |
|---|---|---|---|
| Synthea synthetic patients, November 2021 sample | Demo and development records | Apache-2.0 | Raw files are never committed (`.gitignore`: `data/raw/`, `data/synthea/`) |
| Constructed allergy and order on the hero's two records | The BL-AMOX-01 demo scenario | Added by the team, not produced by Synthea; labeled constructed on screen | `data/scenarios/hero/scenario_manifest.json`, `data/scenarios/hero/hero.json` |
| RxNav RxClass penicillin-class members and RxNorm ingredient lookups | The rule's drug class table, an offline snapshot fetched 2026-10-17; the runtime makes no network call | Not yet recorded: `docs/LICENSES.md` holds a placeholder for the NLM statement | `backend/rule/cache/penicillin_class.json`, `backend/rule/cache/scd_to_ingredient.json` |
| DailyMed label excerpts | The citation on a flag | Not yet recorded | `backend/rule/cache/labels/` |
| b.well public synthetic patient-matching benchmark, derived from ONC challenge data | Evaluation only, never committed or displayed | Described by the test-set authors as synthetic; terms not located | Never committed (`.gitignore`: `data/onc/`, `data/benchmark/`) |

Third-party licenses are listed in `docs/LICENSES.md`: every package in `uv.lock`, the direct dependencies of `frontend/` and `eval/acceptance/`, the container images, and the data sources.

CheckMate's own code is released under the MIT License; see `LICENSE`. The data sources above keep their own terms.

## Not for clinical use

CheckMate is a synthetic-data prototype for identity reconciliation and evidence display. Flags are rule-based, name their sources, are shown only after a person approves an identity link, and do not direct treatment. Not for clinical use. No clinician has reviewed the rule, the class table or the wording. Absence of a flag does not mean absence of a conflict.

The contract's default flag footer, `CARD_FOOTER` in `contracts/models/alerts.py`, names what the rule does not check: cephalosporin cross-reactivity, intolerances, dose and free-text allergies. It also says that absence of a flag is not evidence that no conflict exists, and that no clinician reviewed the rule or its wording.

## Known limits and non-goals

- **Synthetic data only.** The database holds only synthetic records and is dropped with one command (`docker-compose.yml`, `Makefile`); source datasets are never committed (`.gitignore`).
- **Optional notifier.** `tools/notify` can send the registrar a generic iMessage ("CheckMate: a kiosk check-in is waiting for registrar review.") when a check-in is held. The text carries no patient data, travels through Apple's Messages service, and nothing is sent unless someone starts the notifier.
- **Hand-set scorer and thresholds.** The weights (`handset-1`) and the threshold row (`provisional-1`) are set by hand, not trained or calibrated (`backend/core/score.py`, `contracts/migrations/0002_provisional_thresholds.sql`). Thresholds are evaluation thresholds, not clinical ones. Auto-link stays off (`contracts/models/thresholds.py`).
- **The hero is provisional.** The hero export is marked `provisional` and not `qualified`: two of its required selection criteria are unmet, `change_birth_year_keep_separate` and `swap_dob_day_month_robust` (`data/scenarios/hero/hero.json`).
- **REPLAY is scripted.** The replay transcript was written by the team, not recorded from a model run, and answers only its scripted lines (`data/scenarios/hero/frontdesk_transcript.json`, `backend/frontdesk/replay.py`).
- **The live agent depends on the Gemini API.** Without a key and a model id, live turns degrade to the template line (`backend/frontdesk/adapters.py`).
- **Two sources at the core path:** an ER FHIR record and a clinic CSV row (`data/scenarios/hero/hero.json`).
- **No undo of an approved link.** The review endpoint takes `APPROVE` or `REJECT` only, and a reject of a linked pair is refused (`contracts/models/common.py`, `backend/api/reviews.py`); Reset demo clears every decision. Undo of a reset is not available through the API (`frontend/src/data/apiSource.ts`).
- **Not on `main`:** the what-if route and the entity history route answer `501` (`backend/app/main.py`, `contracts/api_spec.py`).
- **No authentication.** A registrar name is a recorded label, not an authenticated identity (`contracts/models/reviews.py`).
- **One process on one laptop, reachable only from localhost** (`docker-compose.yml`, `Makefile`, `frontend/package.json`).
