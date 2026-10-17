"""Write source_record, normalized_record and block_key rows in one transaction (architecture §4).

Idempotent: a draft whose (source_system, source_local_id) already exists with the same payload
hash is skipped; the same local id with a different payload is an error, because raw payloads
are immutable. The derived rows are not immutable: for a skipped record the normalized row and its
block keys are re-derived and replaced when they differ, so a database loaded by an older
normalizer or key vocabulary (issue #10) is brought in line by a reload instead of keeping keys the
gate can no longer match. Postgres is the source of truth; nothing here caches.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import psycopg
from psycopg.types.json import Jsonb

from backend.ingest.blocking import block_keys
from backend.ingest.normalize import normalized_row
from backend.ingest.records import SourceRecordDraft

BATCH_SIZE = 100


class ImmutablePayloadConflict(RuntimeError):
    """The same source id was seen with a different payload: raw payloads never change."""


@dataclass
class IngestResult:
    records_seen: int = 0
    records_inserted: int = 0
    records_skipped: int = 0
    records_rederived: int = 0  # skipped records whose normalized row or block keys were out of date
    keys_inserted: int = 0
    inserted_ids: list[str] = field(default_factory=list)


INSERT_SOURCE = """
INSERT INTO source_record (id, source_system, source_local_id, kind, raw_payload, payload_sha256, is_constructed)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (source_system, source_local_id) DO NOTHING
RETURNING id
"""
SELECT_EXISTING_HASH = "SELECT payload_sha256 FROM source_record WHERE source_system = %s AND source_local_id = %s"
# The normalized_record columns, in one place: the statement and the values are both built from it.
NORMALIZED_COLUMNS = (
    "given_name",
    "family_name",
    "given_name_folded",
    "family_name_folded",
    "birth_date",
    "birth_year",
    "birth_month",
    "birth_day",
    "sex",
    "phone_e164",
    "address_line",
    "zip5",
)
_COLUMN_LIST = ", ".join(NORMALIZED_COLUMNS)
_EXCLUDED_LIST = ", ".join(f"EXCLUDED.{column}" for column in NORMALIZED_COLUMNS)
_STORED_LIST = ", ".join(f"normalized_record.{column}" for column in NORMALIZED_COLUMNS)
# Insert, or replace only when a column differs: rowcount is 0 exactly when the stored row is current.
UPSERT_NORMALIZED = (
    f"INSERT INTO normalized_record (record_id, {_COLUMN_LIST}) "
    f"VALUES ({', '.join(['%s'] * (len(NORMALIZED_COLUMNS) + 1))}) "
    f"ON CONFLICT (record_id) DO UPDATE SET ({_COLUMN_LIST}) = ({_EXCLUDED_LIST}) "
    f"WHERE ({_STORED_LIST}) IS DISTINCT FROM ({_EXCLUDED_LIST})"
)
SELECT_KEYS = "SELECT key_type, key_value FROM block_key WHERE record_id = %s"
DELETE_KEYS = "DELETE FROM block_key WHERE record_id = %s"
INSERT_BLOCK_KEY = "INSERT INTO block_key (key_type, key_value, record_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING"


def _write_one(cur: psycopg.Cursor, draft: SourceRecordDraft, result: IngestResult) -> None:
    result.records_seen += 1
    sha = draft.sha256
    cur.execute(
        INSERT_SOURCE,
        (
            draft.id,
            draft.source_system,
            draft.source_local_id,
            draft.kind.value,
            Jsonb(draft.raw_payload),
            sha,
            draft.is_constructed,
        ),
    )
    if cur.fetchone() is None:
        existing = cur.execute(SELECT_EXISTING_HASH, (draft.source_system, draft.source_local_id)).fetchone()
        if existing is None or existing[0] != sha:
            raise ImmutablePayloadConflict(
                f"{draft.source_system}:{draft.source_local_id} already exists with a different payload"
            )
        result.records_skipped += 1
        if _write_derived(cur, draft, result):
            result.records_rederived += 1
        return
    _write_derived(cur, draft, result)
    result.records_inserted += 1
    result.inserted_ids.append(str(draft.id))


def _write_derived(cur: psycopg.Cursor, draft: SourceRecordDraft, result: IngestResult) -> bool:
    """Bring the record's normalized row and block keys in line with the payload; True if anything changed.

    The keys are computed from the stored row, exactly as the gate and match runs re-read it.
    """
    row = normalized_row(draft.identity)
    cur.execute(UPSERT_NORMALIZED, (draft.id, *(row[column] for column in NORMALIZED_COLUMNS)))
    changed = cur.rowcount == 1
    keys = block_keys(row)
    stored = {tuple(key) for key in cur.execute(SELECT_KEYS, (draft.id,)).fetchall()}
    if stored != set(keys):
        cur.execute(DELETE_KEYS, (draft.id,))
        cur.executemany(INSERT_BLOCK_KEY, [(key_type, key_value, draft.id) for key_type, key_value in keys])
        result.keys_inserted += len(keys)
        changed = True
    return changed


def ingest(conn: psycopg.Connection, drafts: Iterable[SourceRecordDraft], batch_size: int = BATCH_SIZE) -> IngestResult:
    """Each batch is one transaction, so a record's three tables land together or not at all."""
    result = IngestResult()
    batch: list[SourceRecordDraft] = []

    def flush() -> None:
        if not batch:
            return
        with conn.transaction(), conn.cursor() as cur:
            for draft in batch:
                _write_one(cur, draft, result)
        batch.clear()

    for draft in drafts:
        batch.append(draft)
        if len(batch) >= batch_size:
            flush()
    flush()
    return result


def pair_candidates_by_key_type(conn: psycopg.Connection) -> dict[str, int]:
    """Within-block pair count per key type: sum over blocks of n*(n-1)/2."""
    rows = conn.execute(
        """
        SELECT key_type, COALESCE(SUM(n * (n - 1) / 2), 0)::bigint
        FROM (SELECT key_type, key_value, count(*) AS n FROM block_key GROUP BY key_type, key_value) b
        GROUP BY key_type ORDER BY key_type
        """
    ).fetchall()
    return {key_type: int(count) for key_type, count in rows}
