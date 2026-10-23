# Verification record

Author: Christian Flores (docs) · 2026-10-23

GitHub Actions logs for this repository can be read only by a signed-in GitHub user, and GitHub deletes them after the retention period (90 days by default for a public repository, so the last `main` run's log expires around 2027-01-17). This file copies the summary lines that the README's numbers rest on, names where each one came from, and gives the command that reproduces it. Every quoted line is copied from the log or the file named next to it. The data is synthetic throughout.

Commit messages on `main` were edited on 2026-10-23 (wording only; no file changed). Commit IDs from the merge of pull request #2 (2026-10-17 15:50 CDT) onward changed, so CI runs, pull requests and comments from before 2026-10-23 show the old IDs. Each old commit has the same file tree as its new one. Where this file names a changed commit, it gives both IDs.

## The last CI run on `main`

Run #197, [run 39340754421](https://github.com/ivan-711/checkmate/actions/runs/39340754421), push to `main` at the commit of pull request #71 (`ef27ae5`; the run page shows the old ID `b24d455`), 2026-10-19 23:18:33 to 23:21:41 UTC. Conclusion: success.

| Job | Result |
|---|---|
| mirror, ruff, openapi snapshot, pytest | success |
| schemathesis against the running API | success |
| hero selector regenerates the export through the product; fixture_check | success |
| acceptance script type-checks and lists | success |
| frontend build (when frontend/package.json exists) | success |
| gitleaks | success |
| harness (fast) on merge to main | success |
| G16 acceptance script against the running app | skipped (runs only when the repository variable `ACCEPTANCE_CI` is set) |
| protected expectations unchanged unless the PR is a fork | skipped (runs on pull requests only) |

### pytest

Log line (job "mirror, ruff, openapi snapshot, pytest"):

```
1515 passed, 5 skipped, 1 xfailed, 21 warnings in 43.77s
```

- The suite collects 1,521 tests (`uv run pytest --collect-only -q`). In CI it runs against a TimescaleDB service container, so the database tests count toward the 1,515.
- The 5 skips are one parametrized test in `backend/tests/core/test_core_r2.py` ("scorer_version was bumped; these golden values belong to handset-0"). The 1 expected failure is the non-strict `xfail` in `backend/tests/frontdesk/test_replay_network_off.py`.
- The same job printed `All checks passed!` for ruff, and the CLAUDE.md/AGENTS.md mirror check and the OpenAPI snapshot check passed.

### Schemathesis contract test

Schemathesis v4.31.1, `--checks all` with `not_a_server_error` excluded, because contract routes whose lane has not merged answer `501 NOT_IMPLEMENTED` by design (`.github/workflows/ci.yml`). It runs twice:

| Run | Operations | Log line |
|---|---|---|
| 1: every operation except the 7 that answer 422 by design | 11 selected / 18 total | `1637 generated, 1637 passed` |
| 2: the 7 designed-422 operations, with `positive_data_acceptance` also off | 7 selected / 18 total | `1912 generated, 1912 passed` |

The next step reads the API's own request log and fails on any 5xx other than 501. Its log line:

```
request log: 3554 requests, no non-501 5xx
```

3,554 counts request-log lines, which is slightly more than the 3,549 generated test cases. The same log also warns "Missing test data: 4 operations repeatedly returned 404" (3 in run 2): operations that need an existing id were exercised mostly on their not-found path.

### Evaluation harness on merge

The job compared this run with the baseline from run 39146781578 and printed:

```
note: blocking.recall: 0.9294 -> 0.9294 (+0.00 pp) inside tolerance
note: recall.lenient.end_to_end: 0.8831 -> 0.8831 (+0.00 pp) inside tolerance
note: gate_suite.duplicates_denied: not measured on both sides; skipped
note: review_burden: 0.7280 -> 0.7280 (+0.00 pp) inside tolerance
inside tolerance
```

These are the per-merge `--fast` numbers (development components only), not the held-out numbers below.

## Frontend unit tests

CI builds the frontend but does not run Vitest. Run locally on 2026-10-23 from the tree of pull request #71 (`ef27ae5`), with `npx vitest run` in `frontend/`:

```
Test Files  42 passed (42)
     Tests  357 passed (357)
```

`npm run typecheck`, `npm run lint` and `npm run build` were also clean in a local run that day.

## Database schema

`contracts/migrations/0001_initial.sql` creates 20 tables: 19 domain tables plus the `schema_migration` bookkeeping table. It declares 29 CHECK constraints.

## Held-out evaluation

Harness run 1c3f8f96, committed copy `docs/eval/run-1c3f8f96-metrics.json`; seed 20261017, scorer `handset-1`, threshold row `provisional-1`. Intervals are 95% percentile bootstrap intervals over dependency components, 1,000 resamples.

| Key | Value | 95% interval | n pairs | n components |
|---|---|---|---|---|
| `test.band.review.precision` | 0.903226 | 0.839791 to 0.962991 | 186 | 111 |
| `test.recall.lenient.end_to_end` | 0.847222 | 0.783542 to 0.905025 | 216 | 125 |

Re-run from a fresh clone on 2026-10-23, every non-withheld `test.*` value matched the committed copy exactly.

## Build timeline

- 199 commits on `main` up to and including pull request #71 (`ef27ae5`, old ID `b24d455`). 198 of them have author and committer times inside the event window, 2026-10-17 12:00 to 2026-10-18 12:00 CDT. The one after it is `ef27ae5` itself, the README rewrite of 2026-10-19.
- Pull requests #1 to #71: 61 opened, 59 merged, 2 closed without merging (#44, #59). 58 of the 59 merged inside the window; #71 merged 2026-10-19 23:18 UTC. All 59 merges are under the `ivan-711` account. Later pull requests are post-event documentation and are not counted here.
- The contract freeze is the annotated tag `contracts-v1` on commit `3585a52`. The commit and the tag are both timestamped 2026-10-17 13:21:18 CDT, 81 minutes after the 12:00 start (the build brief's planned freeze time was 13:15).

## Commands to reproduce

Without a database (Python 3.12 and [uv](https://docs.astral.sh/uv/); Node 20 or later):

```sh
uv sync --frozen
uv run ruff check .
uv run python -m contracts.build_openapi --check
uv run pytest --collect-only -q | tail -1
cd frontend && npm ci && npx vitest run && cd ..
grep -c '^CREATE TABLE' contracts/migrations/0001_initial.sql
grep -o 'CHECK *(' contracts/migrations/0001_initial.sql | wc -l
uv run python data/download.py
uv run python -m eval.harness.run --test-pass --seed 20261017 --out eval/runs
```

The harness writes the held-out values as the `test.*` keys of `eval/runs/<run_id>/metrics.json`.

With the database (Docker), the full pytest suite as the README's test table describes:

```sh
make db
make test-db
make test-backend
```

The repository history and pull requests, with `git` and the GitHub CLI:

```sh
git rev-list --count ef27ae5
git log --format='%at %ct' ef27ae5 | awk '$1>=1792256400 && $1<1792342800 && $2>=1792256400 && $2<1792342800' | wc -l
gh pr list --repo ivan-711/checkmate --state merged --limit 200 --json number,mergedAt,mergedBy \
  --jq '[.[] | select(.number <= 71)] | {merged: length, inside_window: ([.[] | select(.mergedAt >= "2026-10-17T17:00:00Z" and .mergedAt < "2026-10-18T17:00:00Z")] | length), merged_by: ([.[].mergedBy.login] | unique)}'
git cat-file -p contracts-v1
```

The two epoch values are 2026-10-17 17:00 UTC and 2026-10-18 17:00 UTC (12:00 CDT each day).
