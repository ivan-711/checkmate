# CheckMate build brief (read this, then your own spec section; not the whole PRD)

Author: Christian Flores (lead session) · 2026-10-17 · `CLAUDE.md` is canonical; `AGENTS.md` is a byte-for-byte mirror for Codex.

CheckMate = **FrontDesk** (a Gemini intake agent behind a deterministic policy gate) + **ChartGuard** (an identity-resolution engine with human-approved links and one cited safety rule). Product name on screen, README, Devpost: CheckMate. Internal names stay in code. Synthetic data only. Not for clinical use. API bound to 127.0.0.1.

## Standing rules for every lane agent
1. Every task comes with how to check it. Run that check before you say you are done: the acceptance script or a Playwright run against the running app for UI and API lanes; the named unit or harness tests for core lanes.
2. Review each of your own commits (code-review skill, or Codex read-only) and fix until clean **before** opening a PR. Then the PR goes to the paired reviewer, Codex and Copilot.
3. Build only in your own worktree (`.worktrees/<lane>` on branch `lane/<lane>`). Push only your own `lane/*` branch. Never push to `main`. Never merge. The lead session merges a PR once every gate below is green (Ivan's standing authorization, 2026-10-17 17:15); Ivan or Alejandro Barojas may also click merge.
4. Reuse the running dev server and database. Do not start new ones. The database is synthetic and rebuilt from the seed with one command (`docker compose down -v && docker compose up`).
5. Never edit `eval/acceptance/` or `eval/expectations/` once W5 has written them. From 20:00, never edit `data/scenarios/hero/`. A change there is a fork for Ivan.
6. The Gemini key lives only in the gitignored `.env`. Never print it, log it or copy it into a tracked file. CI and agents use only the Replay adapter; no key exists in CI.
7. Denied on both Macs (`.claude/settings.json`): force push, push to `main`, `gh pr merge`, `rm -rf`, `docker volume rm`, `docker system prune`, `DROP`/`TRUNCATE` from the shell.
8. Never write a camera frame to the repo, `event_log`, Postgres or a log line. Card images go only to `CHARTGUARD_CAPTURE_DIR` outside the work tree, after the local QR check passes.
9. `contracts/` is frozen at 13:15 (tag `contracts-v1`). An additive change (new optional field, new endpoint) is a reversible fork: proceed and flag it in the PR. A change that alters or removes a field waits for Ivan.
10. A fork is any choice that changes what a judge sees or what the contracts say. Post it as a GitHub issue labeled `fork`: question, option A, option B, your recommendation, cost of each. Do not decide it yourself.
11. Author convention on documents: "Christian Flores (role)". No AI model or vendor name appears as an author anywhere. Every commit message ends with `[AI-assisted]`, e.g. `feat(policy): deny new chart at REVIEW or higher [AI-assisted]`.
12. If you die, the lead session restarts you in the same worktree from this brief, your PR description and your last commit. Keep the PR description current.

## Canonical names (architecture §0; the glossary wins over every other document)
- Bands `AUTO_LINK`, `REVIEW`, `KEEP_SEPARATE`. Thresholds `c_low`, `c_high` on the raw score `s` decide bands; Platt `p` is display-only. `auto_link_enabled = false` in the demo.
- Decision status `PROPOSED`, `LINKED`, `REJECTED`, `REVOKED`. Reject/split reasons `DIFFERENT_PERSON` (writes `not_a_match`), `INSUFFICIENT_EVIDENCE` (no suppression).
- Negative rules `SEX_CONFLICT`, `BIRTH_YEAR_GAP_GT_2`, `TWIN`, `PARENT_CHILD`, `GENERATION_SUFFIX_MISMATCH`, `PLACEHOLDER_NAME`, `PLACEHOLDER_DOB`. They demote AUTO_LINK to REVIEW only.
- What-ifs `REMOVE_ADDRESS`, `CHANGE_BIRTH_YEAR`, `SWAP_DOB_DAY_MONTH`, `ACCENT_HYPHEN_SURNAME`. Rule `BL-AMOX-01` (spec lives only in the evaluation doc §5). Modes `LIVE`, `LOCAL`, `REPLAY`.
- FrontDesk tools `search_patients`, `propose_new_chart`, `attach_history`. Gate outcomes `ALLOW`, `DENY`; reasons `UNKNOWN_TOOL`, `SESSION_CLOSED`, `INVALID_ARGUMENTS`, `UNGROUNDED_FIELD`, `LOOP_GUARD`, `INCOMPLETE_DEMOGRAPHICS`, `INTAKE_ALREADY_RECORDED`, `ALREADY_LINKED`, `CANDIDATE_IN_REVIEW_OR_HIGHER`, `NO_INTAKE_RECORD`. Policy version `frontdesk-gate/1`.
- Registration `NONE`, `NEW_CHART`, `PENDING_REGISTRAR`, `LINKED`, `RELEASED`. Pair origin `MATCH_RUN`, `FRONTDESK_HANDOFF`. Turn status `IN_PROGRESS`, `COMPLETED`, `FAILED`.
- Actors: `actor_type` in `AGENT`, `REGISTRAR`, `PATIENT`, `SYSTEM`; `actor` label `agent:frontdesk`, `registrar:<label>`, `patient:kiosk`, `system:<component>`.
- `event_type` is TEXT with a CHECK constraint (not an enum), stored UPPER_SNAKE exactly as `contracts/models/common.py` `EventType` lists them: `RECORD_INGESTED`, `MATCH_RUN_COMPLETED`, `PAIR_SCORED`, `LINK_APPROVED`, `LINK_REJECTED`, `LINK_REVOKED`, `ENTITY_MERGED`, `ENTITY_SPLIT`, `ALERT_RAISED`, `ALERT_RETRACTED`, `WHATIF_APPLIED`, `DEMO_RESET`, `DEMO_RESTORED`, `EXPLANATION_GENERATED`, `EXTERNAL_CALL`, `EVAL_RUN_STARTED`, `EVAL_RUN_FINISHED`, `INTAKE_STARTED`, `AGENT_TOOL_CALLED`, `INTAKE_HANDOFF_CREATED`, `AGENT_TURN_DEGRADED`. Migration `0003_frontdesk_steps` widens the list after 16:00 (0002 is the provisional threshold row, fork #12); `EventType` in `contracts/models/common.py` widens in the same change.
- Aggregates `band_flow_1m`, `review_outcomes_5m`, `agent_gate_5m` (tile `AGENT_GATE`), later `frontdesk_board_1m`; all `materialized_only = false`.
- Errors: `{error:{code,message,details?}}`; `VALIDATION_ERROR` 422, `NOT_FOUND` 404, `CANNOT_LINK_CONFLICT` 409, `IDEMPOTENCY_MISMATCH` 422, `DECISION_NOT_PENDING` 409, `TURN_IN_PROGRESS` 409, `SESSION_CLOSED` 409, `UPSTREAM_UNAVAILABLE` 503, `INTERNAL` 500. `X-Request-Id` on every response.
- JSON is camelCase, enums UPPER_SNAKE, `/api/v1`. Board column reads "Needs registrar", never "Flagged". UI has no red anywhere; the gate card is amber; the allergy card is neutral ("flagged for clinician review"), no `role="alert"`.

## Layout and ownership
| Directory | Owner lanes |
|---|---|
| `contracts/` | lead session; frozen 13:15 |
| `backend/` (`policy/`, `frontdesk/`, `frontdesk/steps/`) | W1 W2 W3a W3b, Q1.1 Q1.2 Q1.4 Q3.1 Q4.1 Q4.2 Q6, Q3a.0 Q3a.1 Q4a.1 Q5a.1 Q6a.1 Q6b.1 |
| `frontend/` | W4, Q1.3, Q2.1 UI, Q3, Q4 UI, `ui-camera` (Q3a.2, Q15.2), `ui-steps` (Q4a.2 Q5a.2 Q6a.2 Q6b.2) |
| `eval/` | W5, Q2, Q5 |
| `data/` | W1, W5; Q3a.1 for `data/scenarios/cards/` |
| `tools/vitals-probe/` | Q15 only, own venv, nothing in the backend lockfile |
| `docs/` | D1 D2 D3 |
| `.github/` | W5 |

The frontend never imports from the backend. The backend never renders HTML. The typed frontend client is generated from the frozen OpenAPI; nobody hand-writes API types. `core/` never imports `frontdesk/`. Only `backend/frontdesk/gemini.py` imports the Gemini SDK. Only `backend/frontdesk/executor.py` imports `chart_store.writes`. No intake step module is imported by the gate, scorer, bands, review, cluster, rule or agent. Alejandro Barojas's lanes never edit `backend/`, `data/`, `eval/`, `tools/` or `contracts/`.

## Wave 1 (13:15–15:30) — done when
| Lane | Builds | Done when |
|---|---|---|
| W1 ingest + corruptor | Synthea FHIR and CSV loaders (Patient, AllergyIntolerance, MedicationRequest, Encounter; appended name digits stripped), corruption generator core rows with hidden truth table and seed-chosen held-out families, hard negatives (grafted) | loader and generator tests pass; truth table reproducible from the seed; loading twice gives the same records and pairs |
| W2 features + scorer | blocking (Double Metaphone surname + birth year, exact DOB, swapped DOB, phone last 7, ZIP5 + initial; placeholder values never block; blocks > 100 records skipped in match runs, never in the gate), features incl. day/month transposition and one-digit DOB edit, logistic scorer with per-feature contributions, `is_calibrated = false` | feature unit tests pass; out-of-fold metrics written by the harness |
| W3a bands + review + hypertable | three bands with negative rules, thresholds from the target false-merge rate on held-out seeded data, review endpoint with reason code, note and frozen evidence snapshot, `Idempotency-Key` required, `SELECT … FOR UPDATE` on the pair, `event_log` writer, continuous aggregates, request middleware writing one structured log line per request (never whole records) | review and event tests pass; aggregate tiles return rows |
| W3b link + rule | union-find over LINKED edges, read-time golden record with crosswalks, timeline, rule BL-AMOX-01 with its 18 tests, the reject case (rule silent) | rule tests pass, including the reject case |
| W5 harness + hero + CI | harness core (per-band precision and recall with n, held-out); GitHub Actions: lint, tests, `schemathesis` against `/openapi.json`, fixture check, frontend build, harness on merge to `main`, secret scan, installs from lock files only; Playwright acceptance script for the G16 path under `eval/acceptance/` by 15:30; automated hero selector | harness posts numbers on each merge; selector returns a hero or a reasoned failure |
| W4 frontend scaffold (Alejandro Barojas) | source cards, candidate pair with evidence rail, Approve and Reject with reason and note, collapse to one golden record with crosswalk chips (basic CSS transition), timeline, neutral flag card with the constructed-scenario chip, mode badge, reset; FrontDesk shell with empty chat pane and gate-tile slot | renders from `scenario.json`; build green |
| S0 Gemini spike | throwaway worktree, never merged: one function-calling round trip with the three tool schemas in EN and ES; notes to `docs/spikes/gemini.md` | notes written |
| D1 docs (Alejandro Barojas) | README skeleton (AI disclosure first), architecture diagram from the contracts, license inventory, known-limits list | first draft committed |

Merge order for wave 1: W1, W2, W3a, W3b, W5, W4. 14:30 walking-skeleton check (two cards, Approve, flag card over the real API). 15:30 scorer checkpoint. 16:00 integration gate G16 on Alejandro Barojas's fresh clone; wave 2 starts only when G16 passes. The G16 steps and the wave 2 ranked queue (Q1 FrontDesk gate/agent/UI/replay, Q2 evaluation tab + ONC, Q3 what-ifs + why, Q3a card capture, Q4 third source + split + why-not, Q4a reason, Q5 Platt + injection suite, Q5a consent, Q6 note extraction, Q6a lookup, Q6b board, Q8 gate latency tile, Q13 Modal, Q15 vitals, Q16 mirror) arrive in each lane's prompt. Check-in desk lanes merge with their flag (`FRONTDESK_STEPS`, `VITALS_ENABLED`) off; the lead session turns a flag on only when the lane is green. Feature merge cutoff 19:45; freeze 20:00 (tag `freeze-20`); `main` freezes Sunday 11:30.

## Review lane (every PR; Ivan is not a reviewer)
1. Paired reviewer agent, started with the builder, given the spec section, the contracts and the tests, never the builder's reasoning. It runs the app in `.worktrees/review-<lane>` and the acceptance script, writes tests that should fail, checks every on-screen string against the say/never-say list, checks contract conformance, and posts PASS or BLOCK with numbered findings. It may add failing tests on `review/<lane>`; it never pushes to the builder's branch.
2. Codex, read-only sandbox, on the diff; blocking findings fixed or answered.
3. Copilot code review; each comment fixed or replied to.
4. Harness on every merge to `main`; a drop beyond `eval/expectations/tolerance.json` opens a revert PR automatically.

A PR merges only when: CI green (until W5's CI is on `main`, the lead's integration run stands in); reviewer PASS; Codex blocking findings closed; Copilot comments answered; the description names the lane, links test evidence, carries `[AI-assisted]`, names the owner (Ivan for his Mac's lanes, Alejandro Barojas for his) and opens with one line of product impact. Over about 400 changed lines (generated and lock files excluded): split before review. Demo-path lanes also get a two-minute manual click-through on localhost before the merge.

## Reviewer checklist (verbatim, in order)
Size first: copy and CSS get a spot check plus a green build; a standard lane gets the full list plus the acceptance script; scorer, thresholds, gate, allergy rule and contracts get the full list plus the harness, and any threshold or contract change is a fork for Ivan.

Code: 1 one job per function. 2 no magic numbers (thresholds, band cut-offs, timeouts are named constants from config). 3 built-ins and chosen libraries, no reinvented helpers. 4 every new branch has a unit test; anything the demo depends on has a test that fails if it breaks. 5 comments say why. 6 formatter and linter clean.
Design: 7 the query matches how the screen reads the data and an index backs it. 8 failure modes: Gemini, matcher or database down; the gate fails closed. 9 Postgres is the source of truth, nothing caches patient data, decisions are append-only. 10 smallest change that does the job, additive to the contract. 11 logged, latency measured, visible when it fails.
Security: 12 approval, split and chart creation only through their endpoints; the agent has no path past the gate; missing authentication is a stated limit. 13 never trust the client or the model: Pydantic at the boundary, the gate recomputes candidates itself, parameters bound everywhere. 14 rate limiting n/a on localhost; 8 s model timeout bounds a turn. 15 installs only from lock files; every new dependency named in the PR. 16 errors and gate denials logged; never full records or keys. 17 no `.env`, keys or tokens in the diff. 18 backups n/a; the database rebuilds from the seed.

## Skills each lane loads (and no more)
- Builders: `superpowers:test-driven-development`, `superpowers:verification-before-completion`.
- Reviewers: `code-review` (and Codex in its read-only sandbox).
- UI lanes load `impeccable`, the accessibility pass and Context7 docs from 19:20 (Ivan, design squad on Alejandro Barojas's machine); every change is still a reviewed PR, and the G16 path and its `data-testid`s stay as they are.
- Nobody loads brainstorming or planning skills inside a lane; the plan is done.

## Process rules that save time
- One FastAPI process, sync endpoints, one pool (`pool_size=10`, `max_overflow=5`, `pool_timeout=5`, `pool_pre_ping=True`), `statement_timeout = 5s`; a connection is never held across a model call or a poll wait. No module-level mutable domain state.
- Same origin: the browser calls `/api/v1` on the Next.js origin, rewritten to FastAPI. CORS allow-list from `CORS_ORIGINS` (default `http://localhost:3000,http://127.0.0.1:3000`), never `*`, headers `Content-Type, Idempotency-Key, Authorization`, exposed `X-Request-Id`.
- SQL values are bound parameters; identifiers come from closed maps in code.
- Every list endpoint takes `limit` (default 50, max 200; a larger value is a 422 at the boundary, as the frozen schema says) and an opaque keyset `cursor`, returns `nextCursor`.
- Gemini: schema-only function declarations, automatic function calling off, temperature 0, 8 s timeout, SDK retries off, one retry only on timeout/429/5xx; two degraded turns in a row switch the session to the template; a turn still `IN_PROGRESS` 40 s after its claim is marked FAILED.
- Phonetics install order: `metaphone` 0.6, then `phonetics` 1.0.5, then jellyfish `metaphone`+`nysiis`. scikit-learn ≥ 1.6 pinned.
