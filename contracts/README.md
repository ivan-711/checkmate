# contracts/ — the frozen shared surface

Author: Christian Flores (lead session) · frozen at tag `contracts-v1`, 2026-10-17 · architecture v0.5.2 §0, §4, §5, §22.4; ADR-016.

Everything every lane builds against lives here: Pydantic models (the source of truth), the generated `openapi.json`, the FrontDesk tool schemas, the SQL migration, the `policy.decide` signature, and two placeholder fixtures. The frontend's typed client is generated from `openapi.json`; nobody hand-writes API types.

## The fork rule
A change here after the freeze is a fork.
- **Additive** (a new optional field, a new endpoint, a widened CHECK list): reversible. The lane proceeds and flags it in the PR. Both Macs pull after merge; open lanes rebase.
- **Altering or removing** a field: waits for Ivan. Post a GitHub issue labeled `fork`.
- Reviewers treat any diff under `contracts/` as a full-list review plus the harness.

## What is frozen
| Thing | Where |
|---|---|
| 12 endpoints (core spine + FrontDesk) | `api_spec.py`, `openapi.json` |
| Every glossary name (bands, statuses, events, reasons, actors) | `models/common.py`, `models/policy.py` |
| `policy.decide(action, candidates) -> PolicyDecision` and the 13-row table order | `models/policy.py` (body: lane Q1.1) |
| Three tool schemas `fd-tools/1` and the minimal ToolResult | `tools/` |
| Migration `0001_initial.sql` incl. `event_log` (TEXT + CHECK), `idempotency_record`, `actor_type`, three real-time continuous aggregates | `migrations/` |
| Version strings, timeouts, limits | `version.py` |
| Hero-shaped placeholder and one hard negative | `fixtures/` (rebuilt by `python -m contracts.fixtures.build_fixtures`) |

Other §5 endpoints (timeline, history, why-not, splits, alerts, events feed, explanations, eval runs, threshold-sets, restore) have models here already and land later by additive PR.

## Rules every lane follows
- JSON is camelCase; enums UPPER_SNAKE; prefix `/api/v1`; one error envelope `{error:{code,message,details?}}`; `X-Request-Id` on every response.
- `POST …/reviews`, `POST …/turns` (and later splits and intake steps) require `Idempotency-Key`, minted once per user intent.
- Every list takes `limit` (default 50, max 200, clamped) and an opaque `cursor`.
- Bands are cut on the raw score through `c_low`/`c_high`; Platt `p` is display-only. `auto_link_enabled = false`.
- Only a human creates `LINKED`. The agent's only path to a write is through `policy.decide`.
- `event_log.payload` never carries free text, full records or keys.

## Commands
```
make openapi-check      # snapshot current?
make test-contracts     # 17 contract tests
make migrate            # apply unapplied migrations (DATABASE_URL)
# contract test against a running API (CI, lane W5). Until every route is implemented the
# stubs answer 501, so the server-error check is excluded and a separate assertion requires
# zero `status=5` lines other than 501 in the request log:
uvx schemathesis run http://127.0.0.1:8000/openapi.json --checks all --exclude-checks not_a_server_error
```
