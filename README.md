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

## Status

Repository bootstrapped 2026-10-17 12:55 CT. The contract freeze (`contracts/`, tag `contracts-v1`) follows at 13:15. "How to run", the architecture diagram, data provenance, decisions and the known-limits list land through the docs lane and are filled from frozen run manifests, never estimated.

## Repository layout

| Directory | Contents |
|---|---|
| `contracts/` | Pydantic models, OpenAPI spec, SQL migrations, policy signature, tool schemas, fixtures. Frozen at 13:15; any later change is a recorded fork |
| `backend/` | FastAPI on 127.0.0.1: ingestion, blocking, features, scorer, bands, clustering, golden record, timeline, rule, event writer, what-ifs; `backend/policy/` the gate; `backend/frontdesk/` the intake agent, replay and steps |
| `frontend/` | Next.js kiosk and registrar screens; talks only to the API described in `contracts/` |
| `eval/` | Evaluation harness, acceptance script, scripted intakes, run manifests |
| `data/` | Download scripts with hashes, corruption generator, hero selector, scenario export. Raw datasets are never committed |
| `docs/` | README sources, architecture diagram, Devpost text, video script, spikes |
| `tools/` | Isolated local processes (vitals probe), separate from the backend lockfile |
| `.github/` | CI: lint, tests, contract test, fixture check, frontend build, harness on merge, secret scan |

## Known limits and non-goals

Filled from the PRD known-limits list at the docs lane. Standing items: synthetic data only; no authentication (a reviewer or registrar name is a recorded label, not an authenticated identity); one process on one laptop bound to localhost; the live agent depends on the Gemini API, with a labeled REPLAY as the fallback.

## License and data

Code license to be set at the docs lane. Synthea sample data is Apache-2.0. The b.well public synthetic patient-matching benchmark derived from ONC challenge data is described by the test-set authors as synthetic; its terms were not located, so it is used for evaluation only, never committed or displayed.
