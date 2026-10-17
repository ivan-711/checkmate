"""Database tests against checkmate_test_w1 (skipped when it is unreachable)."""
import pytest

from backend.ingest.blocking import KEY_TYPES
from backend.ingest.records import SourceRecordDraft, plain_csv_draft, plain_fhir_draft
from backend.ingest.store import ImmutablePayloadConflict, ingest, pair_candidates_by_key_type
from backend.tests.ingest.conftest import PATIENT_A


def drafts_for(bundles, csv_patients):
    return [plain_fhir_draft(b) for b in bundles.values()] + [plain_csv_draft(p) for p in csv_patients.values()]


def snapshot(conn):
    records = conn.execute("SELECT id, source_system, source_local_id, kind, payload_sha256 FROM source_record ORDER BY id").fetchall()
    normalized = conn.execute("SELECT * FROM normalized_record ORDER BY record_id").fetchall()
    keys = conn.execute("SELECT key_type, key_value, record_id FROM block_key ORDER BY 1, 2, 3").fetchall()
    return records, normalized, keys


def test_ingest_is_idempotent_across_fresh_and_repeated_loads(db, bundles, csv_patients):
    first = ingest(db, drafts_for(bundles, csv_patients))
    assert (first.records_inserted, first.records_skipped) == (4, 0)
    before = snapshot(db)
    assert len(before[0]) == 4 and len(before[1]) == 4 and before[2]

    from backend.ingest.store import clear_records
    clear_records(db)  # a fresh database
    ingest(db, drafts_for(bundles, csv_patients))
    assert snapshot(db) == before

    again = ingest(db, drafts_for(bundles, csv_patients))  # same database, loaded again
    assert (again.records_inserted, again.records_skipped, again.keys_inserted) == (0, 4, 0)
    assert snapshot(db) == before


def test_three_tables_land_together(db, bundles, csv_patients):
    ingest(db, drafts_for(bundles, csv_patients))
    missing = db.execute(
        "SELECT count(*) FROM source_record s WHERE NOT EXISTS (SELECT 1 FROM normalized_record n WHERE n.record_id = s.id)"
    ).fetchone()[0]
    assert missing == 0
    row = db.execute(
        "SELECT given_name, family_name_folded, birth_year, sex, phone_e164, zip5 FROM normalized_record n "
        "JOIN source_record s ON s.id = n.record_id WHERE s.source_system = 'ER_FHIR' AND s.source_local_id = %s",
        (PATIENT_A,),
    ).fetchone()
    assert row == ("josé", "nunez garcia", 1990, "M", "+15551234567", "01604")  # backend.core's row form
    kinds = dict(db.execute("SELECT kind, count(*) FROM source_record GROUP BY kind").fetchall())
    assert kinds == {"FHIR_PATIENT": 2, "CSV_ROW": 2}
    counts = pair_candidates_by_key_type(db)
    assert set(counts) <= set(KEY_TYPES)
    assert counts["DOB_EXACT"] >= 2  # each patient's ER and clinic rows share a DOB block


def test_changed_payload_for_same_source_id_is_refused(db, bundles, csv_patients):
    draft = plain_fhir_draft(bundles[PATIENT_A])
    ingest(db, [draft])
    altered = SourceRecordDraft(draft.source_system, draft.source_local_id, {**draft.raw_payload, "patient": {"id": "x"}}, draft.identity)
    with pytest.raises(ImmutablePayloadConflict):
        ingest(db, [altered])
    assert db.execute("SELECT count(*) FROM source_record").fetchone()[0] == 1


def test_stored_block_keys_are_what_core_computes_from_the_stored_row(db, bundles, csv_patients):
    """Issue #10: the gate reads normalized_record and keys it with CORE.block_keys; an ingested chart
    is findable only if the stored block_key rows are exactly those keys."""
    from psycopg.rows import dict_row

    from backend.core.api import CORE

    ingest(db, drafts_for(bundles, csv_patients))
    with db.cursor(row_factory=dict_row) as cur:
        rows = cur.execute("SELECT * FROM normalized_record").fetchall()
    stored: dict[str, set] = {}
    for key_type, key_value, record_id in db.execute("SELECT key_type, key_value, record_id FROM block_key").fetchall():
        stored.setdefault(str(record_id), set()).add((key_type, key_value))
    assert len(rows) == 4
    for row in rows:
        expected = {(k.key_type, k.key_value) for k in CORE.block_keys(row)}
        assert expected and stored[str(row["record_id"])] == expected


def test_cli_refuses_a_database_with_pre_issue_10_key_rows(db, bundles, csv_patients):
    from backend.ingest.cli import stale_key_rows

    ingest(db, drafts_for(bundles, csv_patients))
    assert stale_key_rows(db) == 0
    record_id = db.execute("SELECT id FROM source_record LIMIT 1").fetchone()[0]
    db.execute("INSERT INTO block_key (key_type, key_value, record_id) VALUES ('dob_exact', '1990-03-07', %s)", (record_id,))
    assert stale_key_rows(db) == 1


def test_db_fixture_clears_rows_that_reference_source_records(db, bundles, csv_patients):
    """A shared test database can hold another lane's committed candidate_pair rows; the fixture's
    clear must delete dependents first instead of failing on the foreign key."""
    from backend.tests.ingest.conftest import clear_test_state

    ingest(db, drafts_for(bundles, csv_patients))
    a, b = sorted(str(r[0]) for r in db.execute("SELECT id FROM source_record LIMIT 2").fetchall())
    db.execute(
        "INSERT INTO candidate_pair (id, record_a_id, record_b_id, origin) VALUES (gen_random_uuid(), %s, %s, 'MATCH_RUN')",
        (a, b),
    )
    clear_test_state(db)
    assert db.execute("SELECT count(*) FROM source_record").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM candidate_pair").fetchone()[0] == 0
