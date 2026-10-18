# Gate ablation: 300 scripted check-ins

Author: Christian Flores (integration verifier) · 2026-10-17

The question: when a returning patient checks in at the kiosk and the matcher can find their chart, does the identity gate stop the agent from opening a duplicate chart, and does it still let genuinely new patients get one?

## Result

| Gate | Returning patients: duplicate charts created / n | New patients: charts created / n | New patients: sent to a registrar / n |
|---|---|---|---|
| on | 0 / 150 (Wilson 95%: 0.000 to 0.025) | 150 / 150 | 0 / 150 |
| off | 150 / 150 (Wilson 95%: 0.975 to 1.000) | 150 / 150 | 0 / 150 |

With the gate on, all 150 returning patients were handed to a registrar instead of getting a new chart.

## What this does and does not measure

The cohort was selected on purpose: 150 returning patients whose existing chart scores REVIEW or higher against the typed check-in, and 150 new patients whose entire dependency component was withheld from the database. It measures the gate's effect under that condition. It is not an estimate of how often duplicates happen in a real population, and it says nothing about matching accuracy; for that, see the held-out run in `run-1c3f8f96-metrics.json`. Of the candidate returning patients, 53 were excluded because no eligible existing chart scored REVIEW or higher, and 19 because the scripted check-in was incomplete or ungrounded.

## Method

- Both passes ran the same ordered check-ins against independent fresh database schemas, with the real tool executor and real writes.
- The gate-off pass bypassed only the candidate safety decision, and only inside the ablation harness process. Product code and thresholds were not changed.
- The typed returning-patient text was not stored.

## Run record

- Commit `88585326f3ce1e83b746989aafe83be1af82bfbb`, seed 20261017, scorer `handset-1` (weights sha256 `cc2c32a2…6ac`), truth table sha256 `67235d09…2b1`, started 2026-10-17 21:51 CT, status COMPLETE.
- The harness script and the run manifest were produced in a private integration checkout and are not in this repository, so this result cannot be re-run from the repository alone.
- Two earlier attempts were superseded and are recorded in the manifest. Attempt 1 failed before migration on a URL-escaping error. Attempt 2 used the wrong eligibility probe (record sex instead of the typed check-in's), so its cohort was not the specified one; it reported 2 / 150 duplicates with the gate on and is not used.
