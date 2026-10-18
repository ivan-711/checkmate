# Devpost outline

Author: Christian Flores (docs) · 2026-10-17

The seven headings of the Devpost project story. Every number comes from a frozen run manifest or harness output, never from memory: the held-out table below is copied from `docs/eval/run-1c3f8f96-metrics.json`, and any `{placeholder}` is filled the same way. A sentence whose number has no source stays out.

## Inspiration

{why a patient filed under two identities matters at check-in}

## What it does

FrontDesk: {frontdesk_summary}. Scripted check-ins evaluated: {gate_eval_n}.

ChartGuard: {chartguard_summary}

## How we built it

{stack and process, each line pointing to a file in the repository}

## Challenges we ran into

{challenge, and what changed because of it}

## Accomplishments that we're proud of

Observed on the frozen held-out test partition, run 1c3f8f96 (synthetic data, hand-set weights, threshold row provisional-1):

| Number | Value | n pairs |
|---|---|---|
| REVIEW precision | 0.903 | 186 |
| LENIENT recall (end to end) | 0.847 | 216 |
| STRICT recall (AUTO_LINK, auto-link is off in the demo) | 0.069 | 216 |
| Review burden | 0.681 | 273 |
| Blocking recall | 0.898 | 216 |
| AUTO_LINK precision, KEEP_SEPARATE precision, false-merge rate | not reported (below the reporting floor) | 15, 72, 15 |

A separate five-seed Modal sweep (seeds 20261017 to 20261021) is a development pass, not held-out.

## What we learned

{one lesson per line}

## What's next for CheckMate

{next_steps}
