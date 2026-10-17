from backend.core.block import (
    KEY_DMETA_FAMILY_YEAR,
    KEY_DOB_DAY_MONTH_SWAP,
    KEY_DOB_EXACT,
    KEY_PHONE_LAST7,
    KEY_ZIP5_INITIAL,
    block_keys,
    build_block_index,
    candidate_pairs,
    candidates_for_record,
)
from backend.core.normalize import normalize_record
from contracts.version import BLOCK_MAX_RECORDS


def rec(**kw):
    return normalize_record(kw)


FULL = {"given_name": "Maria", "family_name": "Garcia", "dob": "1990-03-07", "phone": "617-555-2368", "zip": "02139"}


def test_all_five_key_types_emitted_for_a_full_record():
    types = {k.key_type for k in block_keys(rec(**FULL))}
    assert types == {KEY_DMETA_FAMILY_YEAR, KEY_DOB_EXACT, KEY_DOB_DAY_MONTH_SWAP, KEY_PHONE_LAST7, KEY_ZIP5_INITIAL}


def test_swapped_dob_records_share_the_swap_key_but_not_the_exact_key():
    a = block_keys(rec(**{**FULL, "dob": "1990-03-07"}))
    b = block_keys(rec(**{**FULL, "dob": "1990-07-03"}))
    swap_a = {k for k in a if k.key_type == KEY_DOB_DAY_MONTH_SWAP}
    swap_b = {k for k in b if k.key_type == KEY_DOB_DAY_MONTH_SWAP}
    assert swap_a == swap_b and swap_a
    assert {k for k in a if k.key_type == KEY_DOB_EXACT} != {k for k in b if k.key_type == KEY_DOB_EXACT}


def test_day_over_twelve_gets_no_swap_key():
    assert not [k for k in block_keys(rec(**{**FULL, "dob": "1990-03-25"})) if k.key_type == KEY_DOB_DAY_MONTH_SWAP]


def test_placeholder_values_never_block():
    assert not [k for k in block_keys(rec(**{**FULL, "dob": "1900-01-01"})) if k.key_type.startswith("DOB")]
    assert not [k for k in block_keys(rec(**{**FULL, "dob": "1900-01-01"})) if k.key_type == KEY_DMETA_FAMILY_YEAR]
    assert not [k for k in block_keys(rec(**{**FULL, "phone": "555-555-5555"})) if k.key_type == KEY_PHONE_LAST7]
    assert not [k for k in block_keys(rec(**{**FULL, "phone": "617-555-0123"})) if k.key_type == KEY_PHONE_LAST7]
    assert not [k for k in block_keys(rec(**{**FULL, "zip": ""})) if k.key_type == KEY_ZIP5_INITIAL]
    name_keys = {k.key_type for k in block_keys(rec(**{**FULL, "given_name": "Unknown", "family_name": "Unknown"}))}
    assert KEY_DMETA_FAMILY_YEAR not in name_keys and KEY_ZIP5_INITIAL not in name_keys


def test_pairs_are_ordered_a_before_b_with_keys_recorded_and_reduction_ratio():
    records = {
        "r3": rec(**FULL),
        "r1": rec(**{**FULL, "family_name": "Garsia"}),
        "r2": rec(given_name="Zed", family_name="Quill", dob="1950-12-25", zip="99501"),
    }
    result = candidate_pairs(records)
    assert [(p.record_a_id, p.record_b_id) for p in result.pairs] == [("r1", "r3")]
    assert result.pairs[0].block_keys[0].startswith(KEY_DMETA_FAMILY_YEAR + ":")
    assert result.n_total_pairs == 3 and result.n_candidate_pairs == 1
    assert abs(result.reduction_ratio - (1 - 1 / 3)) < 1e-9


def test_not_a_match_pairs_are_excluded_whatever_the_order_given():
    records = {"a": rec(**FULL), "b": rec(**FULL)}
    assert candidate_pairs(records).n_candidate_pairs == 1
    result = candidate_pairs(records, exclusions=[("b", "a")])
    assert result.n_candidate_pairs == 0 and result.n_excluded_not_a_match > 0


def test_oversized_block_is_reported_not_dropped():
    # BLOCK_MAX_RECORDS + 1 records share one DOB and nothing else.
    n = BLOCK_MAX_RECORDS + 1
    records = {f"r{i:03d}": rec(given_name="g", dob="1990-03-25") for i in range(n)}
    result = candidate_pairs(records)
    assert result.n_candidate_pairs == 0
    assert len(result.oversized_blocks) == 1
    block = result.oversized_blocks[0]
    assert block.size == n and block.key == f"{KEY_DOB_EXACT}:1990-03-25"
    assert block.pairs_in_block == n * (n - 1) // 2 == block.pairs_skipped == result.pairs_skipped_oversized
    uncapped = candidate_pairs(records, max_block_records=None)
    assert uncapped.n_candidate_pairs == n * (n - 1) // 2 and not uncapped.oversized_blocks


def test_gate_lookup_is_never_capped():
    n = BLOCK_MAX_RECORDS + 1
    records = {f"r{i:03d}": rec(given_name="g", dob="1990-03-25") for i in range(n)}
    index = build_block_index(records)
    probe = rec(given_name="New", family_name="Person", dob="1990-03-25")
    found = candidates_for_record("intake", probe, index)
    assert len(found) == n
    assert all(p.record_a_id < p.record_b_id for p in found)
    assert len(candidates_for_record("intake", probe, index, exclusions=[("r000", "intake")])) == n - 1
