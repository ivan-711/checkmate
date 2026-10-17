# eval/expectations/ — protected expectations (eval plan section 9)

Author: Gojo (evaluation harness, lane W5).

Lane agents never edit this directory once W5 has written it (CLAUDE.md rule 5). A change here is a
fork for Ivan: open a GitHub issue labeled `fork`, and the PR that applies it carries the `fork`
label so the `protected-paths` CI job lets it through. Every harness run records the sha256 of each
file here in `run.json` and `manifest.json`.

| File | What it fixes | Filled by |
|---|---|---|
| `config.json` | alpha, beta, the 50-component support floor, the review-burden cap, bootstrap resamples and seed, the held-out family config | W5 (held-out families: W1 at the 19:00 P1 commit, via a fork) |
| `splits.json` | the split contract parameters: showcase pool size, 70/30, 5 folds, language stratification | W5 |
| `tolerance.json` | the per-merge tolerance the review lane's merge rule 4 cites | W5 |
| `rule_tests.json` | the 18 BL-AMOX-01 cases (placeholder list) | W3b via a fork |
| `gate_suite.json` | the model-free gate-suite intake list (placeholder) | Q1 via a fork |
| `injection_strings.json` | the injection suite strings (placeholder) | Q5b via a fork |
| `invariants/` | leakage, monotonicity and determinism tests; any failure is red | W5 |

Per merge the harness runs the fast config only: P0 families, one seed, development components,
5-fold out of fold. Never the test partition, held-out families, the showcase pool or the benchmark.
