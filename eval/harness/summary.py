"""Render per-band precision and recall with n from a run's ``numbers.json`` as Markdown.

CI posts this as a commit comment on every merge to ``main`` (CLAUDE.md wave 1, W5 "done when").

    uv run python -m eval.harness.summary eval/runs/<run_id>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROWS = (
    ("AUTO_LINK precision", "band.auto_link.precision"),
    ("AUTO_LINK recall (STRICT, end to end)", "recall.strict.end_to_end"),
    ("REVIEW precision", "band.review.precision"),
    ("REVIEW share of true pairs", "band.review.true_pair_share"),
    ("LENIENT recall (end to end)", "recall.lenient.end_to_end"),
    ("KEEP_SEPARATE precision", "band.keep_separate.precision"),
    ("False-merge rate (auto-links)", "false_merge_rate"),
    ("Review burden", "review_burden"),
    ("Blocking recall", "blocking.recall"),
)


def _fmt(x) -> str:
    if x is None:
        return "n/a"
    return f"{x:.3f}" if isinstance(x, float) else str(x)


def render(numbers: dict, manifest: dict | None = None) -> str:
    lines = []
    if manifest:
        lines.append(f"Harness run `{manifest.get('runId')}` ({manifest.get('config')}, seed {manifest.get('seed')}, "
                     f"scorer `{manifest.get('scorerVersion')}`, thresholds `{manifest.get('thresholdSetId')}`), "
                     "development components only, out of fold. Synthetic data; descriptive. "
                     f"95% intervals: percentile bootstrap over dependency components, "
                     f"{manifest.get('bootstrapResamples')} seeded resamples.")
        lines.append("")
    lines.append("| Number | Value | 95% interval | n pairs | n entities | n components | flags |")
    lines.append("|---|---|---|---|---|---|---|")
    for label, key in ROWS:
        cell = numbers.get(key)
        if cell is None:
            continue
        ci = cell.get("ci95")
        flags = []
        if cell.get("low_support"):
            flags.append("under 50 components")
        if cell.get("do_not_read"):
            flags.append("do not read")
        if cell.get("zero_events"):
            flags.append("zero observed; no upper bound")
        lines.append(f"| {label} | {_fmt(cell.get('value'))} | "
                     f"{'[' + _fmt(ci[0]) + ', ' + _fmt(ci[1]) + ']' if ci else 'n/a'} | "
                     f"{cell.get('n_pairs', cell.get('n_true_pairs', 'n/a'))} | {cell.get('n_entities', 'n/a')} | "
                     f"{cell.get('n_components', 'n/a')} | {', '.join(flags)} |")
    th = numbers.get("thresholds.alpha_target_reachable", {})
    lines.append("")
    lines.append(f"c_low = {_fmt(numbers.get('thresholds.c_low', {}).get('value'))}, "
                 f"c_high = {_fmt(numbers.get('thresholds.c_high', {}).get('value'))}; "
                 f"alpha target reachable: {th.get('value')} (fallback used: {th.get('fallback_used')}). "
                 "Demo cutoffs chosen on development data; configuration, not clinical thresholds.")
    lat = numbers.get("latency.match.p95_ms")
    if lat:
        lines.append(f"match() p95 {_fmt(lat.get('value'))} ms, warm, n = {lat.get('n')}, in-process.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m eval.harness.summary <run_dir>", file=sys.stderr)
        return 2
    run_dir = Path(argv[0])
    numbers = json.loads((run_dir / "numbers.json").read_text())
    manifest = json.loads((run_dir / "manifest.json").read_text()) if (run_dir / "manifest.json").exists() else None
    sys.stdout.write(render(numbers, manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
