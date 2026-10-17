"""Database tests against the ingest test database, each inside one rolled-back transaction."""

from types import SimpleNamespace

import pytest
from psycopg.rows import dict_row

from backend.core.api import CORE
from backend.core.block import BlockingResult, CandidatePair
from backend.ingest.blocking import KEY_TYPES
from backend.ingest.cli import ForeignRecords, load_corpus, truth_pairs_blocked
from backend.ingest.corruptor import LABEL_NOT_SAME, LABEL_SAME, build_corpus
from backend.ingest.records import SourceRecordDraft, plain_csv_draft, plain_fhir_draft
from backend.ingest.store import ImmutablePayloadConflict, ingest, pair_candidates_by_key_type
from backend.tests.ingest.conftest import PATIENT_A, clear_test_state


def drafts_for(bundles, csv_patients):
    return [plain_fhir_draft(b) for b in bundles.values()] + [plain_csv_draft(p) for p in csv_patients.values()]


def snapshot(conn):
    records = conn.execute(
        "SELECT id, source_system, source_local_id, kind, payload_sha256 FROM source_record ORDER BY id"
    ).fetchall()
    normalized = conn.execute("SELECT * FROM normalized_record ORDER BY record_id").fetchall()
    keys = conn.execute("SELECT key_type, key_value, record_id FROM block_key ORDER BY 1, 2, 3").fetchall()
    return records, normalized, keys


def stored_keys(conn) -> dict[str, set[tuple[str, str]]]:
    out: dict[str, set[tuple[str, str]]] = {}
    for key_type, key_value, record_id in conn.execute("SELECT key_type, key_value, record_id FROM block_key"):
        out.setdefault(str(record_id), set()).add((key_type, key_value))
    return out


def stored_rows(conn) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute("SELECT * FROM normalized_record ORDER BY record_id").fetchall()


def test_ingest_is_idempotent_across_fresh_and_repeated_loads(db, bundles, csv_patients):
    first = ingest(db, drafts_for(bundles, csv_patients))
    assert (first.records_inserted, first.records_skipped) == (4, 0)
    before = snapshot(db)
    assert len(before[0]) == 4 and len(before[1]) == 4 and before[2]

    clear_test_state(db)  # a fresh database
    ingest(db, drafts_for(bundles, csv_patients))
    assert snapshot(db) == before

    again = ingest(db, drafts_for(bundles, csv_patients))  # same database, loaded again
    assert (again.records_inserted, again.records_skipped, again.records_rederived, again.keys_inserted) == (0, 4, 0, 0)
    assert snapshot(db) == before


def test_three_tables_land_together_in_the_display_row_form(db, bundles, csv_patients):
    ingest(db, drafts_for(bundles, csv_patients))
    missing = db.execute(
        "SELECT count(*) FROM source_record s WHERE NOT EXISTS (SELECT 1 FROM normalized_record n WHERE n.record_id = s.id)"
    ).fetchone()[0]
    assert missing == 0
    row = db.execute(
        "SELECT given_name, family_name, family_name_folded, birth_year, sex, phone_e164, address_line, zip5 "
        "FROM normalized_record n JOIN source_record s ON s.id = n.record_id "
        "WHERE s.source_system = 'ER_FHIR' AND s.source_local_id = %s",
        (PATIENT_A,),
    ).fetchone()
    # registration spelling where the card and golden record show it; core's form everywhere else
    assert row == ("José", "Núñez-García", "nunez garcia", 1990, "MALE", "+15551234567", "857 Kling Arcade", "01604")
    kinds = dict(db.execute("SELECT kind, count(*) FROM source_record GROUP BY kind").fetchall())
    assert kinds == {"FHIR_PATIENT": 2, "CSV_ROW": 2}
    counts = pair_candidates_by_key_type(db)
    assert set(counts) <= set(KEY_TYPES)
    assert counts["DOB_EXACT"] >= 2  # each patient's ER and clinic rows share a DOB block


def test_changed_payload_for_same_source_id_is_refused(db, bundles, csv_patients):
    draft = plain_fhir_draft(bundles[PATIENT_A])
    ingest(db, [draft])
    altered = SourceRecordDraft(
        draft.source_system, draft.source_local_id, {**draft.raw_payload, "patient": {"id": "x"}}, draft.identity
    )
    with pytest.raises(ImmutablePayloadConflict):
        ingest(db, [altered])
    assert db.execute("SELECT count(*) FROM source_record").fetchone()[0] == 1


def test_stored_block_keys_are_what_core_computes_from_the_stored_row(db, bundles, csv_patients):
    """Issue #10: the gate reads normalized_record and keys it with CORE.block_keys; an ingested chart
    is findable only if the stored block_key rows are exactly those keys."""
    ingest(db, drafts_for(bundles, csv_patients))
    rows, keys = stored_rows(db), stored_keys(db)
    assert len(rows) == 4
    for row in rows:
        expected = {(k.key_type, k.key_value) for k in CORE.block_keys(row)}
        assert expected and keys[str(row["record_id"])] == expected


def test_reload_rederives_rows_and_keys_an_older_normalizer_wrote(db, bundles, csv_patients):
    """A database loaded before issue #10 (old vocabulary, old row form) is brought in line by a reload."""
    ingest(db, drafts_for(bundles, csv_patients))
    current_rows, current_keys = stored_rows(db), stored_keys(db)
    record_id = db.execute(
        "SELECT id FROM source_record WHERE source_system = 'ER_FHIR' AND source_local_id = %s", (PATIENT_A,)
    ).fetchone()[0]
    db.execute("UPDATE normalized_record SET given_name = 'josé', sex = 'M' WHERE record_id = %s", (record_id,))
    db.execute("DELETE FROM block_key WHERE record_id = %s AND key_type = 'PHONE_LAST7'", (record_id,))
    db.execute(
        "INSERT INTO block_key (key_type, key_value, record_id) VALUES ('dob_exact', '1990-03-07', %s)", (record_id,)
    )

    again = ingest(db, drafts_for(bundles, csv_patients))
    assert (again.records_inserted, again.records_skipped, again.records_rederived) == (0, 4, 1)
    assert stored_rows(db) == current_rows and stored_keys(db) == current_keys
    assert ingest(db, drafts_for(bundles, csv_patients)).records_rederived == 0


def test_load_corpus_reports_blocking_over_what_it_stored(db, bundles, csv_patients, tmp_path):
    corpus = build_corpus(7, bundles, csv_patients)
    summary = load_corpus(db, corpus, tmp_path)
    assert summary.result.records_inserted == len(corpus.records) == summary.records_in_db
    assert summary.blocking.n_records == len(corpus.records)
    assert (tmp_path / "truth.csv").exists()
    same_hit, same_n = truth_pairs_blocked(summary.blocking, corpus, LABEL_SAME)
    assert same_n == sum(p["label"] == LABEL_SAME for p in corpus.pairs) and 0 <= same_hit <= same_n
    assert load_corpus(db, corpus, tmp_path).result.records_inserted == 0  # a reload adds nothing


def test_load_corpus_refuses_a_database_holding_another_corpus(db, bundles, csv_patients, tmp_path):
    ingest(db, [plain_fhir_draft(bundles[PATIENT_A])])  # the plain sample record is not in any seeded corpus
    with pytest.raises(ForeignRecords):
        load_corpus(db, build_corpus(7, bundles, csv_patients), tmp_path)
    assert not (tmp_path / "truth.csv").exists()  # nothing written before the refusal


def test_truth_pairs_blocked_matches_cores_pair_ordering():
    corpus = SimpleNamespace(
        pairs=[
            {"record_a_id": "b", "record_b_id": "a", "label": LABEL_SAME},  # truth stored in either order
            {"record_a_id": "a", "record_b_id": "c", "label": LABEL_SAME},
            {"record_a_id": "c", "record_b_id": "b", "label": LABEL_NOT_SAME},
        ]
    )

    result = BlockingResult(
        pairs=(CandidatePair("a", "b", ("DOB_EXACT:1990-03-07",)), CandidatePair("b", "c", ("PHONE_LAST7:1234567",))),
        n_records=3,
        n_total_pairs=3,
        n_candidate_pairs=2,
        reduction_ratio=1 / 3,
        n_excluded_not_a_match=0,
    )
    assert truth_pairs_blocked(result, corpus, LABEL_SAME) == (1, 2)
    assert truth_pairs_blocked(result, corpus, LABEL_NOT_SAME) == (1, 1)


def test_db_fixture_clears_rows_that_reference_source_records(db, bundles, csv_patients):
    """A shared test database can hold another lane's committed candidate_pair rows; the fixture's
    clear must delete dependents first instead of failing on the foreign key."""
    ingest(db, drafts_for(bundles, csv_patients))
    a, b = sorted(str(r[0]) for r in db.execute("SELECT id FROM source_record LIMIT 2").fetchall())
    db.execute(
        "INSERT INTO candidate_pair (id, record_a_id, record_b_id, origin) VALUES (gen_random_uuid(), %s, %s, 'MATCH_RUN')",
        (a, b),
    )
    clear_test_state(db)
    assert db.execute("SELECT count(*) FROM source_record").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM candidate_pair").fetchone()[0] == 0
