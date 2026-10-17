"""Compare a harness run against the last green ``main`` run (eval plan section 9 tolerance).

Exit 0 inside tolerance (improvements and changes inside tolerance are posted, not reverted),
exit 3 beyond it (CI opens a revert PR labeled ``revert``), exit 0 with a note when there is no
baseline yet. Before the first trained scorer only invariants apply.

    uv run python -m eval.compare --baseline <dir> --candidate <dir> [--tolerance eval/expectations/tolerance.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOLERANCE = REPO_ROOT / "eval" / "expectations" / "tolerance.json"
EXIT_BEYOND_TOLERANCE = 3
PP = 100.0


def _value(numbers: dict, key: str) -> float | None:
    cell = numbers.get(key)
    if not isinstance(cell, dict):
        return None
    value = cell.get("value")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def compare(baseline: dict, candidate: dict, tolerance: dict, baseline_metrics: dict | None,
            candidate_metrics: dict | None) -> tuple[list[str], list[str]]:
    """Returns (breaches, notes)."""
    breaches: list[str] = []
    notes: list[str] = []
    inv = (candidate_metrics or {}).get("invariants", {})
    for name, ok in inv.items():
        if ok is not True:
            breaches.append(f"invariant {name} failed")
    scorer = (candidate_metrics or {}).get("scorerVersion")
    before = tolerance.get("beforeFirstTrainedScorer", {})
    if before.get("invariantsOnly") and scorer in before.get("standInScorerVersions", []):
        notes.append(f"stand-in scorer {scorer}: only invariants apply before the first trained scorer")
        return breaches, notes
    keys = tolerance["keys"]
    checks = (
        (keys["blockingRecall"], -tolerance["blockingRecallDropPp"], "blocking recall fell"),
        (keys["lenientOutOfFoldEndToEndRecall"], -tolerance["lenientOutOfFoldEndToEndRecallDropPp"],
         "LENIENT out-of-fold end-to-end recall fell"),
        (keys["gateSuiteDuplicatesDenied"], -tolerance["gateSuiteDuplicatesDeniedDropPp"], "gate-suite duplicates denied fell"),
        (keys["reviewBurden"], tolerance["reviewBurdenRisePp"], "review burden rose"),
    )
    for key, limit_pp, label in checks:
        b, c = _value(baseline, key), _value(candidate, key)
        if b is None or c is None:
            notes.append(f"{key}: not measured on both sides; skipped")
            continue
        delta_pp = (c - b) * PP
        if limit_pp < 0 and delta_pp < limit_pp:
            breaches.append(f"{label} by {-delta_pp:.2f} pp (limit {-limit_pp} pp): {b:.4f} -> {c:.4f}")
        elif limit_pp > 0 and delta_pp > limit_pp:
            breaches.append(f"{label} by {delta_pp:.2f} pp (limit {limit_pp} pp): {b:.4f} -> {c:.4f}")
        else:
            notes.append(f"{key}: {b:.4f} -> {c:.4f} ({delta_pp:+.2f} pp) inside tolerance")
    if tolerance.get("alphaTargetMustStayReachable"):
        key = keys["alphaTargetReachable"]
        b_cell, c_cell = baseline.get(key, {}), candidate.get(key, {})
        if b_cell.get("value") is True and c_cell.get("value") is not True:
            breaches.append("alpha target became unreachable (fallback used)")
        elif c_cell.get("fallback_used"):
            notes.append("alpha target reached only through the fallback on both sides")
    return breaches, notes


def _load(path: Path | None, name: str) -> dict | None:
    if path is None or not (path / name).exists():
        return None
    return json.loads((path / name).read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", type=Path, default=None, help="run dir of the last green main run")
    parser.add_argument("--candidate", type=Path, required=True, help="run dir of this run")
    parser.add_argument("--tolerance", type=Path, default=DEFAULT_TOLERANCE)
    args = parser.parse_args(argv)
    tolerance = json.loads(args.tolerance.read_text())
    candidate = _load(args.candidate, "numbers.json")
    if candidate is None:
        print(f"candidate run has no numbers.json: {args.candidate}", file=sys.stderr)
        return 2
    candidate_metrics = _load(args.candidate, "metrics.json")
    baseline = _load(args.baseline, "numbers.json")
    if baseline is None:
        breaches, notes = compare({}, candidate, {"keys": tolerance["keys"], "beforeFirstTrainedScorer":
                                                  {"invariantsOnly": True, "standInScorerVersions": [
                                                      candidate_metrics.get("scorerVersion") if candidate_metrics else None]}},
                                  None, candidate_metrics)
        print("no baseline run: invariants checked, tolerance not applied")
        for n in notes:
            print(f"note: {n}")
        for b in breaches:
            print(f"BREACH: {b}")
        return EXIT_BEYOND_TOLERANCE if breaches else 0
    breaches, notes = compare(baseline, candidate, tolerance, _load(args.baseline, "metrics.json"), candidate_metrics)
    for n in notes:
        print(f"note: {n}")
    for b in breaches:
        print(f"BREACH: {b}")
    if breaches:
        print(f"{len(breaches)} breach(es) beyond eval/expectations/tolerance.json", file=sys.stderr)
        return EXIT_BEYOND_TOLERANCE
    print("inside tolerance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
