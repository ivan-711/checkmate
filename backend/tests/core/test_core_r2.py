"""R2 paired-review tests for lane W2 (architecture section 3 S2-S6, section 6; ADR-001; eval plan section 5).

Written without the builder's reasoning. Tests marked ``R2 finding`` are expected to fail on
lane/w2 at c5a09e3; each names the finding it reproduces.
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest
from sklearn.model_selection import GroupKFold

from backend.core.band import (
    DEMO_THRESHOLDS,
    apply_negative_rules,
    band_from_score,
    match,
    negative_rules_for,
)
from backend.core.block import (
    KEY_DMETA_FAMILY_YEAR,
    KEY_PHONE_LAST7,
    KEY_ZIP5_INITIAL,
    MAX_EXACT_HOT_BLOCKS,
    block_keys,
    build_block_index,
    candidate_pairs,
    candidates_for_record,
)
from backend.core.features import FEATURE_NAMES, MISSING_GROUPS, compute_features
from backend.core.normalize import fold_text, normalize_record
from backend.core.score import HANDSET_WEIGHTS, Weights, display_probability, load_weights, score_pair, sigmoid
from backend.core.train import (
    build_labeled_pairs,
    design_matrix,
    design_row,
    fit_weights,
    load_records_csv,
    load_truth_csv,
)
from contracts.models.common import Band, NegativeRule
from contracts.models.thresholds import ThresholdSet
from contracts.version import BLOCK_MAX_RECORDS

REPO_ROOT = Path(__file__).resolve().parents[3]

GIVEN = [
    "Maria",
    "José",
    "Ana",
    "Luis",
    "Carmen",
    "Juan",
    "Rosa",
    "Pedro",
    "Elena",
    "Francisco",
    "Robert",
    "Susan",
    "Willie",
]
FAMILY = [
    "García",
    "López",
    "Martínez",
    "Pérez",
    "Smith",
    "Johnson",
    "Hernández-Díaz",
    "Torres",
    "O'Brien",
    "de la Cruz",
]
ZIPS = ["02139", "02138", "10001", "94110"]


def random_raw(rng: random.Random, *, allow_missing: bool = True) -> dict:
    """One fielded source record; each optional field is dropped with probability 1/5 when allowed."""

    def maybe(value):
        return None if allow_missing and rng.random() < 0.2 else value

    y, m, d = rng.randint(1940, 2010), rng.randint(1, 12), rng.randint(1, 28)
    return {
        "given_name": maybe(rng.choice(GIVEN)),
        "family_name": maybe(rng.choice(FAMILY)),
        "dob": maybe(f"{y}-{m:02d}-{d:02d}"),
        "sex": maybe(rng.choice(["M", "F"])),
        "phone": maybe(f"617{rng.randint(200, 999)}{rng.randint(1000, 9999)}"),
        "address": maybe(f"{rng.randint(1, 999)} {rng.choice(['Main St', 'Oak Ave', 'Elm Road'])}"),
        "zip": maybe(rng.choice(ZIPS)),
    }


def raw_score(a: dict, b: dict, weights: Weights = HANDSET_WEIGHTS) -> float:
    return score_pair(compute_features(normalize_record(a), normalize_record(b)), weights).raw_score


# --- S5: contributions, p, determinism ----------------------------------------------------


def test_contributions_sum_to_logit_minus_intercept_on_random_records():
    rng = random.Random(2026)
    for _ in range(300):
        fv = compute_features(normalize_record(random_raw(rng)), normalize_record(random_raw(rng)))
        result = score_pair(fv, HANDSET_WEIGHTS)
        assert sum(c.logit for c in result.contributions) == pytest.approx(
            result.raw_score - HANDSET_WEIGHTS.intercept, abs=1e-9
        )
        for c in result.contributions:
            assert c.value is None or 0.0 <= c.value <= 1.0, c.feature


def test_p_is_monotone_in_the_logit_for_plain_sigmoid_and_a_negative_a_platt_map():
    rng = random.Random(1)
    logits = sorted(rng.uniform(-40, 40) for _ in range(500))
    assert [sigmoid(x) for x in logits] == sorted(sigmoid(x) for x in logits)
    platt = Weights(scorer_version="platt", intercept=-11.0, weights=HANDSET_WEIGHTS.weights, platt_a=-0.9, platt_b=1.2)
    ps = [display_probability(x, platt) for x in logits]
    assert ps == sorted(ps) and all(0.0 <= p <= 1.0 for p in ps)


def test_weights_reject_a_platt_map_that_would_make_p_decrease_in_the_raw_score():
    """R2 finding: eval plan section 5 contract item 3 says the Platt map is strictly increasing
    (sklearn convention: a_ < 0) and the check is asserted, not assumed. ``Weights`` accepts a >= 0."""
    with pytest.raises(ValueError):
        Weights(scorer_version="bad", intercept=-11.0, weights=HANDSET_WEIGHTS.weights, platt_a=0.7, platt_b=0.0)
    with pytest.raises(ValueError):
        Weights(scorer_version="bad", intercept=-11.0, weights=HANDSET_WEIGHTS.weights, platt_a=0.0, platt_b=0.0)


def test_weights_json_on_disk_equals_in_code_handset_weights_field_by_field():
    loaded = load_weights("handset-0")
    assert loaded == HANDSET_WEIGHTS
    assert loaded.intercept == HANDSET_WEIGHTS.intercept
    assert dict(loaded.weights) == dict(HANDSET_WEIGHTS.weights)
    assert loaded.platt_a is None and loaded.platt_b is None


def _hash_200_pairs_in_subprocess(hash_seed: str) -> str:
    code = (
        "import json, hashlib, random\n"
        "from backend.core.band import match, DEMO_THRESHOLDS\n"
        "from backend.core.score import HANDSET_WEIGHTS\n"
        "from backend.tests.core.test_core_r2 import random_raw\n"
        "rng = random.Random(99)\n"
        "h = hashlib.sha256()\n"
        "for _ in range(200):\n"
        "    r = match(random_raw(rng), random_raw(rng), HANDSET_WEIGHTS, DEMO_THRESHOLDS)\n"
        "    h.update(json.dumps(r.as_dict(), sort_keys=True, default=str).encode())\n"
        "print(h.hexdigest())\n"
    )
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def test_match_is_deterministic_across_process_restarts_and_hash_seeds():
    first = _hash_200_pairs_in_subprocess("1")
    second = _hash_200_pairs_in_subprocess("4242")
    assert first == second and len(first) == 64


# --- S6: bands and negative rules --------------------------------------------------------


def test_band_is_monotone_in_the_raw_score_whenever_c_low_le_c_high():
    rng = random.Random(5)
    order = {Band.KEEP_SEPARATE: 0, Band.REVIEW: 1, Band.AUTO_LINK: 2}
    for _ in range(200):
        lo, hi = sorted((rng.uniform(-10, 10), rng.uniform(-10, 10)))
        t = ThresholdSet(thresholds_id="t", c_low=lo, c_high=hi)
        scores = sorted(rng.uniform(-15, 15) for _ in range(50)) + [lo, hi]
        bands = [order[band_from_score(s, t)] for s in sorted(scores)]
        assert bands == sorted(bands)
        assert band_from_score(lo, t) is (Band.AUTO_LINK if lo >= hi else Band.REVIEW)
        assert band_from_score(hi, t) is Band.AUTO_LINK


def test_negative_rules_only_ever_move_auto_link_to_review():
    rng = random.Random(8)
    rules = list(NegativeRule)
    for _ in range(500):
        fired = rng.sample(rules, k=rng.randint(0, len(rules)))
        for band in Band:
            after = apply_negative_rules(band, fired)
            if band is Band.AUTO_LINK and fired:
                assert after is Band.REVIEW
            else:
                assert after is band


def test_every_fired_rule_on_random_pairs_demotes_auto_link_only():
    rng = random.Random(13)
    force_auto = ThresholdSet(thresholds_id="auto", c_low=-1e9, c_high=-1e8)
    force_review = ThresholdSet(thresholds_id="review", c_low=-1e9, c_high=1e9)
    force_sep = ThresholdSet(thresholds_id="sep", c_low=1e9, c_high=2e9)
    seen = set()
    for _ in range(400):
        a, b = random_raw(rng), random_raw(rng)
        if rng.random() < 0.3:
            b = {
                **a,
                **rng.choice(
                    [{"sex": "F" if a.get("sex") == "M" else "M"}, {"dob": "1900-01-01"}, {"given_name": "Unknown"}]
                ),
            }
        r_auto, r_rev, r_sep = (match(a, b, HANDSET_WEIGHTS, t) for t in (force_auto, force_review, force_sep))
        seen.update(r_auto.negative_rules_fired)
        assert r_auto.band is (Band.REVIEW if r_auto.negative_rules_fired else Band.AUTO_LINK)
        assert r_rev.band is Band.REVIEW and r_sep.band is Band.KEEP_SEPARATE
    assert {NegativeRule.SEX_CONFLICT, NegativeRule.PLACEHOLDER_DOB, NegativeRule.PLACEHOLDER_NAME} <= seen


# --- S4: monotonicity, named DOB signals, accent/hyphen -----------------------------------

FULL = {
    "given_name": "Willie",
    "family_name": "Smith",
    "dob": "1990-03-07",
    "sex": "M",
    "phone": "617-555-2368",
    "address": "12 Main St",
    "zip": "02139",
}

SINGLE_FEATURE_CORRUPTIONS = {
    "dob_swap": {"dob": "1990-07-03"},
    "dob_digit": {"dob": "1990-03-17"},
    "dob_year": {"dob": "1991-03-07"},
    "dob_missing": {"dob": None},
    "sex_flip": {"sex": "F"},
    "sex_missing": {"sex": None},
    "phone_digit": {"phone": "617-555-2369"},
    "phone_missing": {"phone": None},
    "address_edit": {"address": "14 Main St"},
    "address_missing": {"address": None},
    "zip_near": {"zip": "02138"},
    "zip_missing": {"zip": None},
    "family_typo": {"family_name": "Smyth"},
    "family_accent_hyphen": {"family_name": "Smíth"},
    "given_typo": {"given_name": "Wilie"},
    "given_nickname": {"given_name": "Will"},
    "given_initial": {"given_name": "W"},
    "given_missing": {"given_name": None},
}


@pytest.mark.parametrize("name", list(SINGLE_FEATURE_CORRUPTIONS))
def test_identical_record_scores_at_least_as_high_as_a_single_feature_corruption(name):
    """R2 finding (given_nickname): under handset-0 a nickname variant outscores the identical name
    because ``given_nickname`` is 0 for equal tokens (features.py) while its weight exceeds the
    similarity it costs (Willie/Will 6.17 vs Willie/Willie 5.5; also Daniel/Dani, Jessica/Jessie,
    Eduardo/Edward)."""
    same = raw_score(FULL, FULL)
    corrupted = raw_score(FULL, {**FULL, **SINGLE_FEATURE_CORRUPTIONS[name]})
    assert same >= corrupted - 1e-12, (same, corrupted)


def test_swapping_day_and_month_gives_the_swap_signal_and_exact_zero_on_random_dates():
    rng = random.Random(3)
    for _ in range(200):
        y, m, d = rng.randint(1940, 2010), rng.randint(1, 12), rng.randint(1, 12)
        if m == d:
            continue
        a, b = {**FULL, "dob": f"{y}-{m:02d}-{d:02d}"}, {**FULL, "dob": f"{y}-{d:02d}-{m:02d}"}
        fv = compute_features(normalize_record(a), normalize_record(b))
        assert fv.values["dob_day_month_swap"] == 1.0 and fv.values["dob_exact"] == 0.0
        assert fv.values["dob_one_component_off"] == 0.0 and fv.values["dob_year_match"] == 1.0
        assert fv.missing["dob"] is False
        # The signal is strong: the swapped pair stays within the named-feature credit of exact.
        r = match(a, b, HANDSET_WEIGHTS, DEMO_THRESHOLDS)
        assert r.band is Band.AUTO_LINK and r.features["dob_day_month_swap"] == 1.0


def test_accent_and_hyphen_and_case_variants_score_within_epsilon():
    a = {**FULL, "given_name": "Ana", "family_name": "González-Rivera"}
    same = raw_score(a, a)
    assert abs(same - raw_score(a, {**a, "family_name": "Gonzalez Rivera"})) < 0.1
    assert same == raw_score(a, {**a, "family_name": "GONZÁLEZ-RIVERA"})
    assert raw_score({**a, "family_name": "González"}, {**a, "family_name": "González"}) == raw_score(
        {**a, "family_name": "González"}, {**a, "family_name": "GONZÁLEZ"}
    )
    fv = compute_features(normalize_record(a), normalize_record({**a, "family_name": "Gonzalez Rivera"}))
    assert fv.values["family_jw_folded"] == fv.values["family_dl"] == fv.values["family_dmeta"] == 1.0


def test_case_fold_happens_before_any_feature():
    rng = random.Random(21)
    for _ in range(100):
        a = random_raw(rng, allow_missing=False)
        shouted = {k: (v.upper() if isinstance(v, str) else v) for k, v in a.items()}
        assert compute_features(normalize_record(a), normalize_record(shouted)) == compute_features(
            normalize_record(a), normalize_record(a)
        )


def test_missing_feature_is_none_with_its_indicator_set_never_a_silent_zero():
    rng = random.Random(17)
    for _ in range(200):
        a, b = random_raw(rng), random_raw(rng)
        fv = compute_features(normalize_record(a), normalize_record(b))
        result = score_pair(fv, HANDSET_WEIGHTS)
        by_name = {c.feature: c for c in result.contributions}
        for group in MISSING_GROUPS:
            features_in_group = [n for n in FEATURE_NAMES if n.startswith(group.split("_")[0])]
            if fv.missing[group]:
                assert by_name[f"missing_{group}"].value == 1.0
                assert by_name[f"missing_{group}"].logit == HANDSET_WEIGHTS.weights[f"missing_{group}"]
                if group != "dob":  # a year-only side keeps dob_year_match
                    for n in features_in_group:
                        assert fv.values[n] is None and by_name[n].logit == 0.0, n
            else:
                assert by_name[f"missing_{group}"].value == 0.0 and by_name[f"missing_{group}"].logit == 0.0
    # Scorer and trainer agree on the arithmetic for a missing field.
    a, b = normalize_record(FULL), normalize_record({**FULL, "phone": None})
    row = design_row(a, b)
    expected = HANDSET_WEIGHTS.intercept + sum(
        w * x
        for w, x in zip(
            [HANDSET_WEIGHTS.weights[n] for n in FEATURE_NAMES + tuple(f"missing_{g}" for g in MISSING_GROUPS)], row
        )
    )
    assert score_pair(compute_features(a, b), HANDSET_WEIGHTS).raw_score == pytest.approx(expected, abs=1e-9)


# --- S2: the two name forms stay consistent -----------------------------------------------


@pytest.mark.parametrize(
    "given,family",
    [
        ("John", "Smith, Jr."),
        ("John", "Smith-Jr"),
        ("Dr. Robert", "Jones"),
        ("José", "García López"),
        ("Jr.", "Sr.-Sr."),
        ("López", "Mr-Dr.-Jr."),
        ("Sr", "Sra.-Sr-de la"),
    ],
)
def test_accented_form_folds_to_the_folded_form(given, family):
    """R2 finding: for glued title/suffix words the accented form keeps tokens the folded form
    dropped (``Mr-Dr.-Jr.`` -> accented ``dr.``, folded ``None``), so ``family_jw`` compares text the
    folded features never see."""
    n = normalize_record({"given_name": given, "family_name": family})
    assert fold_text(n.given_name) == n.given_name_folded
    assert fold_text(n.family_name) == n.family_name_folded


def test_inline_ordinal_generation_suffix_is_recognised_not_turned_into_a_surname_token():
    """R2 finding: ``strip_synthea_digits`` removes every digit from a name before the suffix
    check, so ``Smith 3rd`` becomes surname tokens ('smith', 'rd') with no suffix and the
    GENERATION_SUFFIXES entries '2nd', '3rd', '4th' are unreachable from the family field."""
    n = normalize_record({"given_name": "John", "family_name": "Smith 3rd"})
    assert n.suffix == "III" and n.family_tokens == ("smith",)


def test_renormalizing_the_stored_row_is_idempotent():
    """R2 finding (edge): ``coerce_normalized`` relies on idempotence; ``Smith, III Don`` is not."""
    rng = random.Random(31)
    for _ in range(300):
        n = normalize_record({"record_id": "r", **random_raw(rng)})
        assert normalize_record(n.to_row_dict()) == n
    n = normalize_record({"given_name": "Ann", "family_name": "Smith, III Don"})
    assert normalize_record(n.to_row_dict()) == n


# --- S3: blocking -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value,key_types_that_must_be_absent",
    [
        ("dob", "1900-01-01", {"DOB_EXACT", "DOB_DAY_MONTH_SWAP", KEY_DMETA_FAMILY_YEAR}),
        ("given_name", "Unknown", {KEY_DMETA_FAMILY_YEAR, KEY_ZIP5_INITIAL}),
        ("family_name", "Doe", {KEY_DMETA_FAMILY_YEAR, KEY_ZIP5_INITIAL}),
        ("phone", "555-0100", {KEY_PHONE_LAST7}),
        ("phone", "617-555-0100", {KEY_PHONE_LAST7}),
        ("phone", "000-000-0000", {KEY_PHONE_LAST7}),
        ("phone", "617-000-0000", {KEY_PHONE_LAST7}),
        ("phone", "(617) 000-0000", {KEY_PHONE_LAST7}),
        ("zip", "", {KEY_ZIP5_INITIAL}),
        ("zip", "00000", {KEY_ZIP5_INITIAL}),
    ],
)
def test_placeholder_values_never_form_a_block_key(field, value, key_types_that_must_be_absent):
    """R2 finding (617-000-0000): ``is_placeholder_phone`` looks at the whole 10 digits but the
    key is the last 7, so a ``0000000`` suffix forms ``PHONE_LAST7:0000000`` and blocks every
    desk-filled number with any area code together."""
    keys = {k.key_type for k in block_keys(normalize_record({**FULL, field: value}))}
    assert not (keys & key_types_that_must_be_absent), keys


def test_oversized_block_is_skipped_and_reported_and_reduction_ratio_still_computed():
    n = BLOCK_MAX_RECORDS + 1
    records = {f"h{i:03d}": normalize_record({"given_name": "g", "dob": "1990-03-25"}) for i in range(n)}
    records["x1"] = normalize_record(FULL)
    records["x2"] = normalize_record({**FULL, "given_name": "Bill"})
    result = candidate_pairs(records)
    assert [(p.record_a_id, p.record_b_id) for p in result.pairs] == [("x1", "x2")]
    assert len(result.oversized_blocks) == 1
    block = result.oversized_blocks[0]
    assert block.key == "DOB_EXACT:1990-03-25" and block.size == n
    assert block.pairs_skipped == n * (n - 1) // 2 == result.pairs_skipped_oversized
    total = (n + 2) * (n + 1) // 2
    assert result.n_total_pairs == total and result.reduction_ratio == pytest.approx(1 - 1 / total)
    assert result.block_sizes[block.key] == n


def test_gate_lookup_returns_every_member_of_a_500_record_block():
    n = 500
    records = {f"h{i:03d}": normalize_record({"given_name": "g", "dob": "1990-03-25"}) for i in range(n)}
    index = build_block_index(records)
    probe = normalize_record({"given_name": "New", "family_name": "Person", "dob": "1990-03-25"})
    found = candidates_for_record("intake", probe, index)
    assert len(found) == n
    assert {p.record_a_id for p in found} | {p.record_b_id for p in found} == set(records) | {"intake"}
    assert all(p.record_a_id < p.record_b_id for p in found)
    # The same block is skipped in the match run, so the gate and the run disagree by design and on purpose.
    assert candidate_pairs(records).n_candidate_pairs == 0


def test_exclusions_are_honored_in_both_orders_in_the_run_and_in_the_gate():
    records = {
        "a": normalize_record(FULL),
        "b": normalize_record(FULL),
        "c": normalize_record({**FULL, "given_name": "Will"}),
    }
    for order in (("a", "b"), ("b", "a")):
        result = candidate_pairs(records, exclusions=[order])
        assert ("a", "b") not in {(p.record_a_id, p.record_b_id) for p in result.pairs}
        assert result.n_candidate_pairs == 2 and result.n_excluded_not_a_match == 1
    index = build_block_index(records)
    for order in (("a", "intake"), ("intake", "a")):
        found = candidates_for_record("intake", normalize_record(FULL), index, exclusions=[order])
        assert {p.record_a_id for p in found} | {p.record_b_id for p in found} == {"b", "c", "intake"}


def _brute_force_skipped(records, cap, exclusions):
    """Pairs in some block over ``cap`` that no small block produced and no exclusion removed."""
    index = build_block_index(records)
    excluded = {tuple(sorted(e)) for e in exclusions}
    produced, hot_union, per_block = set(), set(), {}
    for key, members in index.items():
        pairs = {tuple(sorted((str(a), str(b)))) for a, b in combinations(members, 2)}
        if len(members) > cap:
            hot_union |= pairs
            per_block[str(key)] = pairs
        else:
            produced |= pairs
    skipped_total = len(hot_union - produced - excluded)
    skipped_per_block = {k: len(v - produced - excluded) for k, v in per_block.items()}
    return skipped_total, skipped_per_block, len(hot_union)


def test_hot_block_accounting_matches_brute_force_on_random_corpora():
    rng = random.Random(77)
    cap = 3
    exact_cases = 0
    for _ in range(60):
        records = {f"r{i}": normalize_record(random_raw(rng)) for i in range(rng.randint(4, 14))}
        ids = list(records)
        exclusions = [tuple(rng.sample(ids, 2)) for _ in range(rng.randint(0, 3))]
        result = candidate_pairs(records, exclusions=exclusions, max_block_records=cap)
        total, per_block, _ = _brute_force_skipped(records, cap, exclusions)
        assert {b.key: b.pairs_skipped for b in result.oversized_blocks} == per_block
        if len(result.oversized_blocks) <= MAX_EXACT_HOT_BLOCKS:
            assert result.pairs_skipped_oversized == total and not result.pairs_skipped_is_upper_bound
            exact_cases += 1
        else:
            assert result.pairs_skipped_oversized >= total and result.pairs_skipped_is_upper_bound
        produced = {(p.record_a_id, p.record_b_id) for p in result.pairs}
        assert not produced & {tuple(sorted(e)) for e in exclusions}
    assert exact_cases > 10


# --- train.py -----------------------------------------------------------------------------


def _tiny_corpus(rng: random.Random, n_entities: int = 40):
    records, truth = [], []
    for e in range(n_entities):
        base = random_raw(rng, allow_missing=False)
        y, m, d = (int(x) for x in base["dob"].split("-"))
        damaged = {**base, "dob": f"{y}-{d:02d}-{m:02d}" if m != d else f"{y + 1}-{m:02d}-{d:02d}"}
        for k, rec in enumerate((base, damaged)):
            records.append({"record_id": f"e{e}r{k}", **rec})
            truth.append(
                {"record_id": f"e{e}r{k}", "entity_id": f"e{e}", "component_id": f"c{e}", "partition": "development"}
            )
    return records, truth


def _write(tmp_path, records, truth):
    import csv

    rp, tp = tmp_path / "records.csv", tmp_path / "truth.csv"
    for path, rows in ((rp, records), (tp, truth)):
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return rp, tp


def test_train_writes_an_out_of_fold_score_for_every_blocked_pair(tmp_path):
    records, truth = _tiny_corpus(random.Random(5))
    rp, tp = _write(tmp_path, records, truth)
    recs, tru = load_records_csv(rp), load_truth_csv(tp, partition="development")
    weights, report, oof = fit_weights(recs, tru, version="r2-test")
    assert len(oof) == report["n_pairs"] == len(build_labeled_pairs(recs, tru))
    assert all(not np.isnan(row["raw_score"]) for row in oof)
    assert set(weights.weights) == set(HANDSET_WEIGHTS.weights)


def test_grouped_folds_keep_every_component_on_one_side(tmp_path):
    """R2 finding: a cross-component negative pair is grouped under the smaller component id
    (train.py ``build_labeled_pairs``), so the other component's records sit in a validation pair
    while that component also trains the fold's model. Eval plan section 3 steps 4-5: pairs stay
    inside one fold and no person id appears in more than one fold; such pairs must be dropped
    from the fold, not re-labelled."""
    records, truth = _tiny_corpus(random.Random(5))
    rp, tp = _write(tmp_path, records, truth)
    recs, tru = load_records_csv(rp), load_truth_csv(tp, partition="development")
    pairs = build_labeled_pairs(recs, tru)
    X, y, groups = design_matrix(pairs, recs)
    folds = min(5, len(set(groups)))
    leaks = []
    for train_idx, test_idx in GroupKFold(n_splits=folds).split(X, y, groups):
        comps = lambda idx: (
            {tru[pairs[i].record_a_id].component_id for i in idx}
            | {tru[pairs[i].record_b_id].component_id for i in idx}
        )
        overlap = comps(train_idx) & comps(test_idx)
        if overlap:
            leaks.append(sorted(overlap)[:3])
    assert leaks == [], leaks


# --- negative-rule corner the glossary names -------------------------------------------------


def test_negative_rules_are_computed_only_from_normalized_fields_and_features():
    a, b = (
        normalize_record({**FULL, "ssn": "123-45-6789", "mrn": "A1"}),
        normalize_record({**FULL, "ssn": "999-99-9999", "mrn": "B2"}),
    )
    assert negative_rules_for(a, b, compute_features(a, b)) == []
    assert raw_score({**FULL, "ssn": "123-45-6789"}, {**FULL, "ssn": "999-99-9999"}) == raw_score(FULL, FULL)
