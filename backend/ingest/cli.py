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


class DuplicatePatientId(RuntimeError):
    """Two bundles claim one Synthea person id: the sample is corrupt, so stop rather than keep either."""


def load_sample(raw_dir: Path, limit: int | None = None, skipped: list[str] | None = None):
    """Parse the bundles and the CSV cohort. A malformed bundle (bad JSON, no Patient, Patient
    without id) is skipped and its file name appended to ``skipped``; a duplicate id raises."""
    fhir_dir, csv_dir = raw_dir / "fhir", raw_dir / "csv"
    paths = iter_bundle_paths(fhir_dir)
    if not paths or not (csv_dir / "patients.csv").exists():
        raise SystemExit(f"no sample under {raw_dir}; run `uv run python data/download.py` first")
    if limit:
        paths = paths[:limit]
    bundles = {}
    for path in paths:
        try:
            bundle = load_bundle(path)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:  # JSONDecodeError is a ValueError
            print(f"warning: skipped {path.name}: {exc}", file=sys.stderr)
            if skipped is not None:
                skipped.append(path.name)
            continue
        if bundle.patient_id in bundles:
            raise DuplicatePatientId(f"duplicate patient id {bundle.patient_id} in {path.name}")
        bundles[bundle.patient_id] = bundle
    csv_patients = read_csv_dir(csv_dir, patient_ids=set(bundles))
    return bundles, csv_patients


def foreign_records(conn: psycopg.Connection, corpus) -> int:
    """Rows already in source_record that are not part of this corpus. Loading on top of another
    corpus or seed would mix truth tables and pair counts, so the CLI refuses before writing."""
    expected = {(rec.draft.source_system, rec.draft.source_local_id) for rec in corpus.records}
    rows = conn.execute("SELECT source_system, source_local_id FROM source_record").fetchall()
    return sum(1 for row in rows if tuple(row) not in expected)


def cmd_load(args: argparse.Namespace) -> int:
    started = time.monotonic()
    skipped: list[str] = []
    bundles, csv_patients = load_sample(args.raw, args.limit, skipped)
    corpus = build_corpus(args.seed, bundles, csv_patients)
    with psycopg.connect(args.database_url) as conn:
        foreign = foreign_records(conn, corpus)
        if foreign:
            raise SystemExit(f"database already holds {foreign} record(s) from another corpus or seed; use a fresh database")
        write_outputs(corpus, args.out / f"corruptor-{args.seed}")
        result = ingest(conn, (rec.draft for rec in corpus.records))
        counts = pair_candidates_by_key_type(conn)
        total_records = conn.execute("SELECT count(*) FROM source_record").fetchone()[0]
    print(f"bundles skipped as malformed: {len(skipped)}" + (f" ({', '.join(skipped)})" if skipped else ""))
    print(f"entities: {corpus.run['entities']}")
    print(f"records: generated={corpus.run['records']} inserted={result.records_inserted} skipped={result.records_skipped} in_db={total_records}")
    print(f"pairs: same={corpus.run['pairs_same']} not_same={corpus.run['pairs_not_same']} grafts={corpus.run['grafts']}")
    for key_type in KEY_TYPES:
        print(f"pair candidates [{key_type}]: {counts.get(key_type, 0)}")
    print("reduction: pending W2")
    print("records per family: " + ", ".join(f"{f}={n}" for f, n in corpus.run["family_counts"].items()))
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
