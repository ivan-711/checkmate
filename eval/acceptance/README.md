# eval/acceptance/ — the G16 acceptance script

Author: Christian Flores (evaluation harness, lane W5). Protected: lane agents never edit this directory once
W5 has written it (CLAUDE.md rule 5); a change is a fork for Ivan.

`g16.spec.ts` is the Playwright script for the G16 demo path. It runs against the running UI on
`http://127.0.0.1:3000` with the API on `http://127.0.0.1:8000` (override with `CHECKMATE_UI_BASE`
and `CHECKMATE_API_BASE`). It never starts servers (CLAUDE.md rule 4).

```
cd eval/acceptance
npm ci                      # pinned, from package-lock.json only
npx playwright install chromium
npm run typecheck           # tsc --noEmit
npm test                    # playwright test
```

In CI the run is gated by the repository variable `ACCEPTANCE_CI=1` (the merge captain sets it once
the G16 path is live) and then asserts zero non-501 5xx lines in the API request log.

## Steps the script asserts

1. Reset, then two source cards render (`ER_FHIR` and `CLINIC_CSV`), each showing that source's given and
   family name from `data/scenarios/hero/hero.json` (override with `CHECKMATE_HERO`). Names match case-,
   accent-, space- and punctuation-insensitively (NFKD, combining marks stripped).
2. Resolve shows the hero pair in `REVIEW` with the evidence rail.
3. Reject with reason `INSUFFICIENT_EVIDENCE` and a note: no flag card; an event row `link_rejected`.
4. Resolve again, Approve with a note (and the reason control if shown).
5. Cards collapse into one golden record (showing the hero's given name and one of the two source family
   names; survivorship is W3b's) with crosswalk chips; the timeline shows both sources.
6. The neutral flag card carries `BL-AMOX-01`, the constructed-scenario chip, the words
   "flagged for clinician review", no `role="alert"`, none of the never-say words.
7. `GET /api/v1/events?since=<API clock>` has one row per action, as deltas against a snapshot taken
   before the run (`demo_reset` +1, `match_run_completed` +2, `link_rejected` +1, `link_approved` +1,
   `alert_raised` +1). The clock is the `Date` header of `GET /health` with an explicit UTC offset; the
   same `since` goes on every page; the feed is read in full through `nextCursor` up to 250 pages of 200
   and fails loudly beyond that; event types are compared case-insensitively.
8. The human-review tile is non-zero in `GET /api/v1/metrics/tiles` (`HUMAN_REVIEW.total`) and on screen.
9. No API response seen by the page has a 5xx status.

## data-testid contract for lane W4

Stable names; add them exactly. Attributes in parentheses are read by the script.

| data-testid | Element | Notes |
|---|---|---|
| `app-mode-badge` | mode badge (`LIVE`/`LOCAL`/`REPLAY`) | visible on load |
| `reset-button` | Reset control | calls `POST /api/v1/sessions` with `scenarioId: "hero"` |
| `source-card` | each source card (`data-source-system="ER_FHIR"` or `"CLINIC_CSV"`) | exactly two after reset; zero after the collapse |
| `resolve-button` | Resolve control | calls `POST /api/v1/match-runs` |
| `candidate-pair` | the hero pair panel | |
| `pair-band` | band label inside the pair panel | text contains `REVIEW` |
| `evidence-rail` | evidence rail container | |
| `evidence-feature-row` | one row per feature contribution | at least one |
| `reject-button` | opens the reject dialog | |
| `approve-button` | opens the approve dialog | |
| `review-reason-select` | `<select>` with values `DIFFERENT_PERSON`, `INSUFFICIENT_EVIDENCE` | required for reject; optional for approve |
| `review-note-input` | note field (max 500) | |
| `review-submit-button` | submits the review with a fresh `Idempotency-Key` | |
| `golden-record` | the collapsed golden record | |
| `crosswalk-chip` | one chip per crosswalk source | at least one |
| `timeline` | timeline container | |
| `timeline-event` | one row per timeline event (`data-source-system`) | both systems present after approve |
| `flag-card` | the neutral "flagged for clinician review" card | absent after reject; no `role="alert"`; never red |
| `flag-card-rule-id` | the rule id text inside the card | exactly `BL-AMOX-01` |
| `constructed-scenario-chip` | chip inside the flag card | |
| `event-row` | one row per event in the event feed (`data-event-type`, lowercase or enum case) | |
| `tile-human-review` | the `HUMAN_REVIEW` tile | |
| `tile-human-review-total` | the tile's total count text | not `0` after the approve |

Say/never-say: the flag card says "flagged for clinician review" and never "prevented",
"would have died", "the AI caught", "contraindicated for this patient" or "fatal". The board column
reads "Needs registrar", never "Flagged".
