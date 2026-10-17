"""``uv run python -m backend.ingest.cli load --seed 20261017``

Parses the Synthea Nov 2021 sample under data/raw (run ``uv run python data/download.py`` first),
runs the corruption generator, writes every generated record through the store and prints the
counts the build brief asks for. The blocking reduction ratio is W2's; until W2 merges the line
reads "reduction: pending W2".
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg

from backend.ingest.blocking import KEY_TYPES
from backend.ingest.corruptor import build_corpus, write_outputs
from backend.ingest.csvio import read_csv_dir
from backend.ingest.fhir import iter_bundle_paths, load_bundle
from backend.ingest.store import ingest, pair_candidates_by_key_type

DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_OUT_DIR = Path("eval/runs")
DEFAULT_DATABASE_URL = "postgresql://checkmate:checkmate@127.0.0.1:5432/checkmate"


def load_sample(raw_dir: Path, limit: int | None = None):
    fhir_dir, csv_dir = raw_dir / "fhir", raw_dir / "csv"
    paths = iter_bundle_paths(fhir_dir)
    if not paths or not (csv_dir / "patients.csv").exists():
        raise SystemExit(f"no sample under {raw_dir}; run `uv run python data/download.py` first")
    if limit:
        paths = paths[:limit]
    bundles = {}
    for path in paths:
        bundle = load_bundle(path)
        bundles[bundle.patient_id] = bundle
    csv_patients = read_csv_dir(csv_dir, patient_ids=set(bundles))
    return bundles, csv_patients


def cmd_load(args: argparse.Namespace) -> int:
    started = time.monotonic()
    bundles, csv_patients = load_sample(args.raw, args.limit)
    corpus = write_outputs(build_corpus(args.seed, bundles, csv_patients), args.out / f"corruptor-{args.seed}")
    with psycopg.connect(args.database_url) as conn:
        result = ingest(conn, (rec.draft for rec in corpus.records))
        counts = pair_candidates_by_key_type(conn)
        total_records = conn.execute("SELECT count(*) FROM source_record").fetchone()[0]
    print(f"entities: {corpus.run['entities']}")
    print(f"records: generated={corpus.run['records']} inserted={result.records_inserted} skipped={result.records_skipped} in_db={total_records}")
    print(f"pairs: same={corpus.run['pairs_same']} not_same={corpus.run['pairs_not_same']} grafts={corpus.run['grafts']}")
    for key_type in KEY_TYPES:
        print(f"pair candidates [{key_type}]: {counts.get(key_type, 0)}")
    print("reduction: pending W2")
    print(f"heldout families: {', '.join(corpus.heldout_families)}")
    print(f"truth table sha256: {corpus.sha256['truth']}  ({corpus.files['truth']})")
    print(f"pairs table sha256: {corpus.sha256['pairs']}  ({corpus.files['pairs']})")
    print(f"elapsed: {time.monotonic() - started:.1f}s")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backend.ingest.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    load = sub.add_parser("load", help="parse the sample, run the corruptor, write records")
    load.add_argument("--seed", type=int, required=True)
    load.add_argument("--raw", type=Path, default=DEFAULT_RAW_DIR)
    load.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    load.add_argument("--limit", type=int, default=None, help="only the first N bundles (smoke runs)")
    load.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    load.set_defaults(func=cmd_load)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
