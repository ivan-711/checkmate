"""Fit scorer weights from a truth table with grouped out-of-fold evaluation (ADR-001).

Pairs come from the same blocking the match run uses, so the scorer is trained on the
candidate distribution it will see. Folds are grouped by dependency component (``component_id``
in the truth table, falling back to ``entity_id``) so corrupted copies of one person never sit
on both sides of a fold. Out-of-fold raw scores are written for threshold choice (W3a) and the
Platt display map (Q5); this module fits neither. The final model trains on all rows given.

Usage:
    uv run python -m backend.core.train --records records.csv --truth truth.csv \
        [--version logreg-x] [--out-dir backend/core/weights] [--oof-out oof.csv] [--partition development]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

from backend.core.block import candidate_pairs
from backend.core.features import FEATURE_NAMES, MISSING_GROUPS, FeatureVector, compute_features
from backend.core.normalize import Normalized, normalize_record
from backend.core.score import ALL_WEIGHT_NAMES, WEIGHTS_DIR, Weights, save_weights, score_pair
from contracts.version import BLOCK_MAX_RECORDS

DEFAULT_FOLDS = 5
DEVELOPMENT_PARTITION = "development"
DEFAULT_C = 1.0  # L2 strength; features are already in [0, 1] so no scaling is applied
MAX_ITER = 2_000
VERSION_PREFIX = "logreg"
DIGEST_CHARS = 8


@dataclass(frozen=True)
class TruthRow:
    entity_id: str
    component_id: str
    partition: str | None
    cv_fold: int | None = None  # from the splits assignment when the truth table carries it


@dataclass(frozen=True)
class LabeledPair:
    record_a_id: str
    record_b_id: str
    label: int
    group: str  # the CV fold both records' components belong to, as a string


@dataclass(frozen=True)
class FoldedPairs:
    pairs: list[LabeledPair]
    n_dropped_straddling: int  # blocked pairs whose two components sit in different folds


def load_records_csv(path: Path) -> dict[str, Normalized]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    records = {}
    for row in rows:
        norm = normalize_record(row)
        if norm.record_id is None:
            raise ValueError(f"{path}: every row needs a record_id")
        records[norm.record_id] = norm
    return records


# W1's truth.csv names the splits fold ``fold``; ``cv_fold`` is accepted as an alias.
FOLD_COLUMNS: tuple[str, ...] = ("fold", "cv_fold")


def load_truth_csv(path: Path, partition: str | None = None, require_fold: bool = False) -> dict[str, TruthRow]:
    """Truth rows, optionally one partition, with the splits fold when the table carries one.

    The fold must come from the splits assignment (evaluation plan section 3, step 2). With
    ``require_fold`` (the CLI default) a table without a fold column, or a kept row with an empty
    fold, is an error. Otherwise the components are hashed with W1's formula and a warning says so.
    """
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        columns = reader.fieldnames or []
    fold_column = next((c for c in FOLD_COLUMNS if c in columns), None)
    if fold_column is None:
        message = f"{path}: no fold column ({' or '.join(FOLD_COLUMNS)}); folds would be hashed, not the splits'"
        if require_fold:
            raise ValueError(message)
        warnings.warn(message, UserWarning, stacklevel=2)
    truth: dict[str, TruthRow] = {}
    for row in rows:
        row_partition = row.get("partition") or None
        if partition is not None and row_partition != partition:
            continue
        entity = str(row["entity_id"])
        fold = row.get(fold_column) if fold_column else None
        if require_fold and fold in (None, ""):
            raise ValueError(f"{path}: record {row['record_id']} ({row_partition}) has no {fold_column}")
        truth[str(row["record_id"])] = TruthRow(
            entity_id=entity,
            component_id=str(row.get("component_id") or entity),
            partition=row_partition,
            cv_fold=int(fold) if fold not in (None, "") else None,
        )
    return truth


def component_fold(component_id: str, n_folds: int) -> int:
    """Fold of one dependency component by hash: W1's formula (``backend/ingest/corruptor.py``), so
    the fallback agrees with splits.json for the same components (evaluation plan section 3, step 2)."""
    return int(hashlib.sha256(component_id.encode("utf-8")).hexdigest(), 16) % n_folds


def fold_of(row: TruthRow, n_folds: int) -> int:
    """The splits assignment's fold when the truth table carries one, else the hash fold."""
    if row.cv_fold is None:
        return component_fold(row.component_id, n_folds)
    if not 0 <= row.cv_fold < n_folds:
        raise ValueError(f"component {row.component_id} has fold {row.cv_fold}, outside 0..{n_folds - 1}")
    return row.cv_fold


def folded_pairs(
    records: Mapping[str, Normalized],
    truth: Mapping[str, TruthRow],
    n_folds: int = DEFAULT_FOLDS,
    max_block_records: int | None = BLOCK_MAX_RECORDS,
) -> FoldedPairs:
    """Blocked pairs among labeled records whose two components share a fold.

    Each dependency component is assigned to one fold, so no component sits on both sides of a fold.
    A blocked pair whose two components fall in different folds belongs to neither and is dropped
    (and counted) rather than re-labelled (evaluation plan section 3, steps 4-5).
    """
    labeled = {rid: rec for rid, rec in records.items() if rid in truth}
    blocked = candidate_pairs(labeled, max_block_records=max_block_records)
    kept: list[LabeledPair] = []
    dropped = 0
    for p in blocked.pairs:
        ta, tb = truth[p.record_a_id], truth[p.record_b_id]
        fold_a, fold_b = fold_of(ta, n_folds), fold_of(tb, n_folds)
        if fold_a != fold_b:
            dropped += 1
            continue
        kept.append(LabeledPair(p.record_a_id, p.record_b_id, int(ta.entity_id == tb.entity_id), str(fold_a)))
    return FoldedPairs(pairs=kept, n_dropped_straddling=dropped)


def build_labeled_pairs(
    records: Mapping[str, Normalized],
    truth: Mapping[str, TruthRow],
    max_block_records: int | None = BLOCK_MAX_RECORDS,
    n_folds: int = DEFAULT_FOLDS,
) -> list[LabeledPair]:
    """The training pairs: ``folded_pairs`` without the drop count."""
    return folded_pairs(records, truth, n_folds=n_folds, max_block_records=max_block_records).pairs


def design_row(a: Normalized, b: Normalized) -> list[float]:
    return design_row_from(compute_features(a, b))


def design_row_from(fv: FeatureVector) -> list[float]:
    values = [0.0 if fv.values[name] is None else float(fv.values[name]) for name in FEATURE_NAMES]
    indicators = [1.0 if fv.missing[group] else 0.0 for group in MISSING_GROUPS]
    return values + indicators


def design_matrix(
    pairs: Sequence[LabeledPair], records: Mapping[str, Normalized]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X = np.array([design_row(records[p.record_a_id], records[p.record_b_id]) for p in pairs], dtype=float)
    y = np.array([p.label for p in pairs], dtype=int)
    groups = np.array([p.group for p in pairs])
    return X, y, groups


def _new_model(c: float) -> LogisticRegression:
    return LogisticRegression(C=c, max_iter=MAX_ITER, solver="lbfgs")


def weights_from_model(model: LogisticRegression, version: str) -> Weights:
    return Weights(
        scorer_version=version,
        intercept=float(model.intercept_[0]),
        weights={name: float(w) for name, w in zip(ALL_WEIGHT_NAMES, model.coef_[0], strict=True)},
    )


def data_digest(*paths: Path, partition: str | None, c: float, folds: int) -> str:
    """Digest of the inputs and the settings that change the fit, so runs never overwrite each other."""
    h = hashlib.sha256()
    for path in paths:
        h.update(path.read_bytes())
    h.update(f"|partition={partition}|C={c}|folds={folds}".encode())
    return h.hexdigest()[:DIGEST_CHARS]


def fold_stats(y: np.ndarray, groups: np.ndarray, n_folds: int) -> list[dict[str, int]]:
    out = []
    for k in range(n_folds):
        in_fold = groups == str(k)
        out.append(
            {
                "fold": k,
                "n_pairs": int(in_fold.sum()),
                "n_positive": int(y[in_fold].sum()),
                "n_negative": int((y[in_fold] == 0).sum()),
            }
        )
    return out


def fit_weights(
    records: Mapping[str, Normalized],
    truth: Mapping[str, TruthRow],
    *,
    version: str,
    n_folds: int = DEFAULT_FOLDS,
    c: float = DEFAULT_C,
    provenance: Mapping[str, Any] | None = None,
    require_negatives_per_fold: bool = False,
) -> tuple[Weights, dict[str, Any], list[dict[str, Any]]]:
    """(weights, out-of-fold report, out-of-fold rows).

    Out-of-fold raw scores come from ``score_pair`` with each fold's weights, the same function the
    API serves, so thresholds chosen on them apply to served scores exactly.

    A fold that is empty or has no negatives says nothing about false merges. With
    ``require_negatives_per_fold`` (the CLI default, i.e. every real-corpus run) that raises; without
    it the folds are listed in the report under ``folds_without_negatives`` and a warning is emitted,
    never silently (small unit-test corpora with one entity per component hit this by construction).
    """
    if n_folds < 2:
        raise ValueError(f"need at least 2 folds, got {n_folds}")
    folded = folded_pairs(records, truth, n_folds=n_folds)
    pairs = folded.pairs
    if not pairs:
        raise ValueError("no blocked pairs whose components share a fold")
    fvs: list[FeatureVector] = [compute_features(records[p.record_a_id], records[p.record_b_id]) for p in pairs]
    X = np.array([design_row_from(fv) for fv in fvs], dtype=float)
    y = np.array([p.label for p in pairs], dtype=int)
    groups = np.array([p.group for p in pairs])
    if y.min() == y.max():
        raise ValueError("training pairs contain only one class")
    per_fold = fold_stats(y, groups, n_folds)
    folds_without_negatives = [stats["fold"] for stats in per_fold if stats["n_negative"] == 0]
    if folds_without_negatives:
        message = f"folds {folds_without_negatives} have no negative pairs: {per_fold}"
        if require_negatives_per_fold:
            raise ValueError(message)
        warnings.warn(message, UserWarning, stacklevel=2)
    oof = np.full(len(pairs), np.nan)
    for k in range(n_folds):
        test_mask = groups == str(k)
        train_idx, test_idx = np.flatnonzero(~test_mask), np.flatnonzero(test_mask)
        if y[train_idx].min() == y[train_idx].max():
            raise ValueError(f"training data outside fold {k} has one class: {per_fold}")
        fold_weights = weights_from_model(_new_model(c).fit(X[train_idx], y[train_idx]), f"{version}-fold{k}")
        for i in test_idx:  # an empty fold simply scores nothing
            oof[i] = score_pair(fvs[i], fold_weights).raw_score
    final = _new_model(c).fit(X, y)
    n_components = len({t.component_id for t in truth.values()})
    counts = {
        "n_pairs": len(pairs),
        "n_positive": int(y.sum()),
        "n_components": n_components,
        "n_folds": n_folds,
        "n_dropped_straddling_folds": folded.n_dropped_straddling,
        "per_fold": per_fold,
        "folds_without_negatives": folds_without_negatives,
    }
    weights = Weights(
        scorer_version=version,
        intercept=float(final.intercept_[0]),
        weights={name: float(w) for name, w in zip(ALL_WEIGHT_NAMES, final.coef_[0], strict=True)},
        trained_on={**dict(provenance or {}), **counts, "C": c},  # computed keys win over provenance
    )
    predicted_positive = oof >= 0.0
    tp = int(((y == 1) & predicted_positive).sum())
    report = {
        "scorer_version": version,
        **counts,
        "oof_auc": float(roc_auc_score(y, oof)),
        "oof_average_precision": float(average_precision_score(y, oof)),
        "oof_precision_at_raw_0": tp / max(int(predicted_positive.sum()), 1),
        "oof_recall_at_raw_0": tp / max(int(y.sum()), 1),
        "note": (
            "development, out-of-fold, descriptive; thresholds and Platt are chosen elsewhere on these raw scores. "
            "Each component is in one fold (by hash, or the splits file's cv_fold); pairs straddling two folds "
            "are dropped and counted."
        ),
    }
    oof_rows = [
        {
            "record_a_id": p.record_a_id,
            "record_b_id": p.record_b_id,
            "label": p.label,
            "group": p.group,
            "raw_score": float(score),
        }
        for p, score in zip(pairs, oof, strict=True)
    ]
    return weights, report, oof_rows


def write_oof(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["record_a_id", "record_b_id", "label", "group", "raw_score"])
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--version", default=None, help=f"defaults to {VERSION_PREFIX}-<data digest>")
    parser.add_argument("--out-dir", type=Path, default=WEIGHTS_DIR)
    parser.add_argument("--oof-out", type=Path, default=None)
    parser.add_argument(
        "--partition",
        default=DEVELOPMENT_PARTITION,
        help="truth rows to fit on (default: development; test and showcase rows never train the scorer)",
    )
    parser.add_argument(
        "--hash-folds",
        action="store_true",
        help="allow a truth table without a fold column and hash components instead (never for the real corpus)",
    )
    parser.add_argument("--folds", type=int, default=DEFAULT_FOLDS)
    parser.add_argument("--c", type=float, default=DEFAULT_C)
    parser.add_argument(
        "--allow-folds-without-negatives",
        action="store_true",
        help="report, rather than fail on, a CV fold with no negative pairs (never for the real corpus)",
    )
    args = parser.parse_args(argv)

    records = load_records_csv(args.records)
    truth = load_truth_csv(args.truth, partition=args.partition, require_fold=not args.hash_folds)
    if not truth:
        raise ValueError(f"{args.truth}: no truth rows in partition {args.partition!r}")
    digest = data_digest(args.records, args.truth, partition=args.partition, c=args.c, folds=args.folds)
    version = args.version or f"{VERSION_PREFIX}-{digest}"
    provenance = {
        "data_digest": digest,
        "partition": args.partition,
        "records": args.records.name,
        "truth": args.truth.name,
    }
    weights, report, oof_rows = fit_weights(
        records,
        truth,
        version=version,
        n_folds=args.folds,
        c=args.c,
        provenance=provenance,
        require_negatives_per_fold=not args.allow_folds_without_negatives,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"{version}.json"
    save_weights(weights, out)
    if args.oof_out is not None:
        write_oof(oof_rows, args.oof_out)
    for key, value in report.items():
        print(f"{key}: {value}")
    print(f"weights: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
