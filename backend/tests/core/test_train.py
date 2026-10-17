import csv
import random

import pytest

from backend.core.score import load_weights
from backend.core.train import build_labeled_pairs, fit_weights, load_records_csv, load_truth_csv, main

GIVEN = ["Maria", "Jose", "Ana", "Luis", "Carmen", "Juan", "Rosa", "Pedro", "Elena", "Francisco", "Robert", "Susan"]
FAMILY = ["Garcia", "Lopez", "Martinez", "Perez", "Smith", "Johnson", "Hernandez", "Diaz", "Torres", "Brown"]


def synthetic_corpus(seed: int, n_entities: int = 60):
    """Two records per entity with desk-style damage, plus a sibling hard negative per fourth entity."""
    rng = random.Random(seed)
    records, truth = [], []
    for e in range(n_entities):
        given, family = rng.choice(GIVEN), rng.choice(FAMILY)
        y, m, d = rng.randint(1950, 2005), rng.randint(1, 12), rng.randint(1, 12)
        phone = f"617555{rng.randint(1000, 9999)}"
        zip5 = rng.choice(["02139", "02138", "10001"])
        sex = rng.choice(["M", "F"])
        base = {
            "given_name": given,
            "family_name": family,
            "dob": f"{y}-{m:02d}-{d:02d}",
            "sex": sex,
            "phone": phone,
            "address": f"{rng.randint(1, 99)} Main St",
            "zip": zip5,
        }
        damaged = dict(base)
        kind = rng.choice(["swap", "digit", "nickname", "phone_missing", "typo", "address_missing"])
        if kind == "swap" and m != d:
            damaged["dob"] = f"{y}-{d:02d}-{m:02d}"
        elif kind == "digit":
            damaged["dob"] = f"{y}-{m:02d}-{min(d + 10, 28):02d}"
        elif kind == "nickname" and given == "Francisco":
            damaged["given_name"] = "Paco"
        elif kind == "phone_missing":
            damaged["phone"] = ""
        elif kind == "typo":
            damaged["family_name"] = family[:-1] + "s"
        elif kind == "address_missing":
            damaged["address"] = ""
        component = f"c{e}"
        for k, rec in enumerate((base, damaged)):
            rid = f"e{e}r{k}"
            records.append({"record_id": rid, **rec})
            truth.append(
                {"record_id": rid, "entity_id": f"e{e}", "component_id": component, "partition": "development"}
            )
        if e % 4 == 0:
            sibling = dict(
                base,
                given_name=rng.choice([g for g in GIVEN if g != given]),
                dob=f"{y + 2}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            )
            records.append({"record_id": f"e{e}sib", **sibling})
            truth.append(
                {
                    "record_id": f"e{e}sib",
                    "entity_id": f"e{e}sib",
                    "component_id": component,
                    "partition": "development",
                }
            )
    return records, truth


def write_csvs(tmp_path, records, truth):
    rp, tp = tmp_path / "records.csv", tmp_path / "truth.csv"
    with rp.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)
    with tp.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(truth[0]))
        w.writeheader()
        w.writerows(truth)
    return rp, tp


def test_fit_weights_separates_matches_out_of_fold_and_writes_loadable_json(tmp_path):
    records, truth = synthetic_corpus(seed=11)
    rp, tp = write_csvs(tmp_path, records, truth)
    recs, tru = load_records_csv(rp), load_truth_csv(tp, partition="development")
    pairs = build_labeled_pairs(recs, tru)
    assert any(p.label == 1 for p in pairs) and any(p.label == 0 for p in pairs)
    __weights, report, oof = fit_weights(recs, tru, version="logreg-test")
    assert report["oof_auc"] > 0.9
    assert report["n_folds"] == 5 and len(oof) == report["n_pairs"]
    out_dir = tmp_path / "weights"
    assert (
        main(
            [
                "--records",
                str(rp),
                "--truth",
                str(tp),
                "--version",
                "logreg-test",
                "--out-dir",
                str(out_dir),
                "--oof-out",
                str(tmp_path / "oof.csv"),
                "--hash-folds",
            ]
        )
        == 0
    )
    loaded = load_weights(out_dir / "logreg-test.json")
    assert loaded.scorer_version == "logreg-test"
    assert loaded.trained_on["partition"] == "development" and len(loaded.trained_on["data_digest"]) == 8
    assert loaded.weights["dob_exact"] > 0.0
    assert (tmp_path / "oof.csv").read_text().startswith("record_a_id,record_b_id,label,group,raw_score")


def test_default_version_is_a_deterministic_digest_of_the_data(tmp_path):
    records, truth = synthetic_corpus(seed=3)
    rp, tp = write_csvs(tmp_path, records, truth)
    out_dir = tmp_path / "w"
    main(["--records", str(rp), "--truth", str(tp), "--out-dir", str(out_dir), "--hash-folds"])
    main(["--records", str(rp), "--truth", str(tp), "--out-dir", str(out_dir), "--hash-folds"])
    files = sorted(out_dir.glob("logreg-*.json"))
    assert len(files) == 1


def test_single_class_data_is_rejected(tmp_path):
    records, truth = synthetic_corpus(seed=5, n_entities=8)
    truth = [{**t, "entity_id": "same"} for t in truth]
    rp, tp = write_csvs(tmp_path, records, truth)
    with pytest.raises(ValueError):
        fit_weights(load_records_csv(rp), load_truth_csv(tp), version="x")


def test_folds_come_from_components_and_straddling_pairs_are_counted(tmp_path):
    from backend.core.train import TruthRow, component_fold, fold_of, folded_pairs

    records, truth = synthetic_corpus(seed=11)
    _rp, tp = write_csvs(tmp_path, records, truth)
    recs, tru = load_records_csv(tmp_path / "records.csv"), load_truth_csv(tp)
    folded = folded_pairs(recs, tru)
    assert folded.pairs
    for p in folded.pairs:
        assert p.group == str(component_fold(tru[p.record_a_id].component_id, 5))
        assert fold_of(tru[p.record_a_id], 5) == fold_of(tru[p.record_b_id], 5)
    blocked_total = len(folded.pairs) + folded.n_dropped_straddling
    assert blocked_total >= len(folded.pairs)
    assert fold_of(TruthRow("e", "c1", None, cv_fold=3), 5) == 3  # the splits file's fold wins


def test_cv_fold_column_is_read_from_the_truth_table(tmp_path):
    records, truth = synthetic_corpus(seed=11)
    truth = [{**t, "cv_fold": str(int(t["component_id"][1:]) % 5)} for t in truth]
    _rp, tp = write_csvs(tmp_path, records, truth)
    tru = load_truth_csv(tp)
    assert all(row.cv_fold == int(row.component_id[1:]) % 5 for row in tru.values())


def test_a_fold_without_negatives_warns_in_the_library_and_fails_in_strict_mode_and_the_cli(tmp_path):
    """Folds pinned through cv_fold: sibling components (the negatives) spread over folds 0-3, and
    one single-entity component alone in fold 4, so fold 4 has a positive and no negative."""
    records, truth = synthetic_corpus(seed=11)

    def fold(component: str) -> int:
        e = int(component[1:])
        if e == 1:
            return 4
        return (e // 4) % 4 if e % 4 == 0 else e % 4

    truth = [{**t, "cv_fold": str(fold(t["component_id"]))} for t in truth]
    rp, tp = write_csvs(tmp_path, records, truth)
    recs, tru = load_records_csv(rp), load_truth_csv(tp)
    with pytest.warns(UserWarning, match="no negative pairs"):
        _weights, report, _oof = fit_weights(recs, tru, version="x")
    assert report["folds_without_negatives"] == [4]
    assert report["per_fold"][4]["n_positive"] >= 1 and report["per_fold"][4]["n_negative"] == 0
    with pytest.raises(ValueError, match="no negative pairs"):
        fit_weights(recs, tru, version="x", require_negatives_per_fold=True)
    cli = ["--records", str(rp), "--truth", str(tp), "--out-dir", str(tmp_path / "w")]
    with pytest.raises(ValueError, match="no negative pairs"):
        main(cli)
    with pytest.warns(UserWarning, match="no negative pairs"):
        assert main([*cli, "--allow-folds-without-negatives"]) == 0


def _fold_table(tmp_path, rows, header):
    import csv

    path = tmp_path / "truth_fold.csv"
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_w1_fold_column_is_read_and_cv_fold_is_an_alias(tmp_path):
    rows = [{"record_id": "r1", "entity_id": "e1", "component_id": "c1", "partition": "development", "fold": "3"}]
    assert load_truth_csv(_fold_table(tmp_path, rows, list(rows[0])))["r1"].cv_fold == 3
    alias = [{**{k: v for k, v in rows[0].items() if k != "fold"}, "cv_fold": "2"}]
    assert load_truth_csv(_fold_table(tmp_path, alias, list(alias[0])), require_fold=True)["r1"].cv_fold == 2


def test_missing_or_empty_fold_warns_in_the_library_and_fails_when_required(tmp_path):
    rows = [{"record_id": "r1", "entity_id": "e1", "component_id": "c1", "partition": "development"}]
    path = _fold_table(tmp_path, rows, list(rows[0]))
    with pytest.warns(UserWarning, match="no fold column"):
        assert load_truth_csv(path)["r1"].cv_fold is None
    with pytest.raises(ValueError, match="no fold column"):
        load_truth_csv(path, require_fold=True)
    empty = [{**rows[0], "fold": ""}]
    with pytest.raises(ValueError, match="has no fold"):
        load_truth_csv(_fold_table(tmp_path, empty, list(empty[0])), require_fold=True)


def test_fold_outside_the_fold_count_is_rejected():
    from backend.core.train import TruthRow, fold_of

    with pytest.raises(ValueError, match="outside"):
        fold_of(TruthRow("e", "c1", "development", cv_fold=7), 5)


def test_fallback_hash_is_w1s_formula():
    import hashlib

    from backend.core.train import component_fold

    for comp in ("c0001", "c0420", "component-x"):
        assert component_fold(comp, 5) == int(hashlib.sha256(comp.encode()).hexdigest(), 16) % 5


def test_cli_refuses_a_truth_table_without_folds_and_defaults_to_development(tmp_path):
    records, truth = synthetic_corpus(seed=11)
    rp, tp = write_csvs(tmp_path, records, truth)
    with pytest.raises(ValueError, match="no fold column"):
        main(["--records", str(rp), "--truth", str(tp), "--out-dir", str(tmp_path / "w")])
    test_only = [{**t, "partition": "test"} for t in truth]
    rp2, tp2 = write_csvs(tmp_path, records, test_only)
    with pytest.raises(ValueError, match="no truth rows in partition 'development'"):
        main(["--records", str(rp2), "--truth", str(tp2), "--out-dir", str(tmp_path / "w"), "--hash-folds"])
