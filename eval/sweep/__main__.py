"""Run a sweep over seeds x scorer versions x tiers on the local process pool or on Modal.

    uv run python -m eval.sweep --seeds 20261017 20261018 --scorer-versions handset-1 --tiers synthea \\
        --executor auto|local|modal [--config fast|development] [--raw data/raw] [--out eval/runs] [--workers N]

Writes ``<out>/sweeps/<utc time>-<sweep sha12>/sweep.json`` (manifest and hash, executor, every entry's
numbers, the table) and prints the table. ``--dry-run`` prints the manifest, its hash and its entries and
runs nothing. Exit codes: 0 done; 3 ``--executor modal`` without a token; 4 product unavailable (no
engine or no Synthea sample); 5 the manifest's scorer version is not the engine's.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from eval.harness.product import DEFAULT_RAW_DIR, ProductUnavailable
from eval.harness.run import RUNS_DIR
from eval.sweep.evaluate import ScorerVersionMismatch
from eval.sweep.executors import (
    EXECUTOR_AUTO,
    EXECUTORS,
    ModalTokenMissing,
    TokenCheck,
    executor_ran,
    modal_token_present,
    select_executor,
)
from eval.sweep.manifest import CONFIG_FAST, CONFIGS, TIER_SYNTHEA, TIERS, build_manifest
from eval.sweep.results import ENTRIES_NOTE, aggregate, render_table, withhold_below_floor

EXIT_OK = 0
EXIT_TOKEN_MISSING = 3
EXIT_PRODUCT_UNAVAILABLE = 4
EXIT_SCORER_MISMATCH = 5
SWEEPS_SUBDIR = "sweeps"
SWEEP_SHA_DIGITS = 12


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m eval.sweep", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--seeds", type=int, nargs="+", required=True, help="corpus seeds, one run each")
    parser.add_argument(
        "--scorer-versions",
        nargs="+",
        required=True,
        help="scorer versions to measure; each must be what the loaded engine reports",
    )
    parser.add_argument("--tiers", nargs="+", default=[TIER_SYNTHEA], choices=TIERS)
    parser.add_argument("--config", default=CONFIG_FAST, choices=CONFIGS, help="the harness config per run")
    parser.add_argument(
        "--executor",
        default=EXECUTOR_AUTO,
        choices=EXECUTORS,
        help="auto: Modal when a token is configured, else the local pool",
    )
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW_DIR, help="extracted Synthea sample (data/download.py)")
    parser.add_argument("--out", type=Path, default=RUNS_DIR, help="run directories and the sweeps/ folder go here")
    parser.add_argument("--workers", type=int, default=None, help="local pool size (default: the CPU count)")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the manifest, its hash and its entries; run nothing"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, token_present: TokenCheck = modal_token_present) -> int:
    args = parse_args(argv)
    manifest = build_manifest(
        seeds=args.seeds, scorer_versions=args.scorer_versions, tiers=args.tiers, config=args.config
    )
    entries = manifest.entries()
    if args.dry_run:
        print(
            json.dumps(
                {
                    "manifest": manifest.as_dict(),
                    "sweepSha256": manifest.sha256,
                    "entries": [e.as_dict() for e in entries],
                },
                indent=2,
            )
        )
        return EXIT_OK
    try:
        executor, reason = select_executor(args.executor, token_present=token_present, workers=args.workers)
    except ModalTokenMissing as exc:
        print(f"MODAL TOKEN MISSING: {exc}", file=sys.stderr)
        return EXIT_TOKEN_MISSING
    print(f"sweep {manifest.sha256} · {len(entries)} entries · executor: {executor.name} ({reason})")
    started_at = datetime.now(UTC)
    clock = time.perf_counter()
    try:
        results = executor.run(entries, out_dir=args.out, raw_dir=args.raw)
    except ProductUnavailable as exc:
        print(f"PRODUCT UNAVAILABLE: {exc}", file=sys.stderr)
        return EXIT_PRODUCT_UNAVAILABLE
    except ScorerVersionMismatch as exc:
        print(f"SCORER VERSION MISMATCH: {exc}", file=sys.stderr)
        return EXIT_SCORER_MISMATCH
    elapsed = time.perf_counter() - clock
    table = aggregate(results)
    ran_on = executor_ran(results)
    doc = {
        "sweepSha256": manifest.sha256,
        "manifest": json.loads(manifest.to_json()),
        "executor": ran_on,
        "executorRequested": executor.name,
        "executorReason": reason,
        "startedAt": started_at.isoformat(),
        "finishedAt": datetime.now(UTC).isoformat(),
        "elapsedSeconds": elapsed,
        "entriesNote": ENTRIES_NOTE,
        "entries": [{**r, "numbers": withhold_below_floor(r["numbers"])} for r in results],
        "table": table,
    }
    sweep_dir = args.out / SWEEPS_SUBDIR / f"{started_at:%Y%m%dT%H%M%SZ}-{manifest.sha256[:SWEEP_SHA_DIGITS]}"
    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "sweep.json").write_text(json.dumps(doc, indent=2) + "\n")
    for r in results:
        where = r["executor"] + (f" (fallback: {r['fallbackReason']})" if "fallbackReason" in r else "")
        print(
            f"  seed {r['entry']['seed']} · {r['entry']['tier']} · {r['entry']['scorerVersion']} · "
            f"{r['elapsedSeconds']:.1f} s · {where} · run {r['runId']}"
        )
    print(f"ran on: {ran_on} · total {elapsed:.1f} s")
    print(render_table(table))
    print(f"sweep written to {sweep_dir}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
