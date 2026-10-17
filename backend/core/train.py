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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold

from backend.core.block import candidate_pairs
from backend.core.features import FEATURE_NAMES, MISSING_GROUPS, compute_features
from backend.core.normalize import Normalized, normalize_record
from backend.core.score import ALL_WEIGHT_NAMES, WEIGHTS_DIR, Weights, save_weights
from contracts.version import BLOCK_MAX_RECORDS

DEFAULT_FOLDS = 5
DEFAULT_C = 1.0  # L2 strength; features are already in [0, 1] so no scaling is applied
MAX_ITER = 2_000
VERSION_PREFIX = "logreg"
DIGEST_CHARS = 8


@dataclass(frozen=True)
class TruthRow:
    entity_id: str
    component_id: str
    partition: str | None


@dataclass(frozen=True)
class LabeledPair:
    record_a_id: str
    record_b_id: str
    label: int
    group: str


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


def load_truth_csv(path: Path, partition: str | None = None) -> dict[str, TruthRow]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    truth: dict[str, TruthRow] = {}
    for row in rows:
        row_partition = row.get("partition") or None
        if partition is not None and row_partition != partition:
            continue
        entity = str(row["entity_id"])
        truth[str(row["record_id"])] = TruthRow(
            entity_id=entity, component_id=str(row.get("component_id") or entity), partition=row_partition
        )
    return truth


def build_labeled_pairs(
    records: Mapping[str, Normalized], truth: Mapping[str, TruthRow], max_block_records: int | None = BLOCK_MAX_RECORDS
) -> list[LabeledPair]:
    """Blocked pairs among labeled records; label 1 when both share an entity."""
    labeled = {rid: rec for rid, rec in records.items() if rid in truth}
    blocked = candidate_pairs(labeled, max_block_records=max_block_records)
    out = []
    for pair in blocked.pairs:
        ta, tb = truth[pair.record_a_id], truth[pair.record_b_id]
        # A cross-component negative is assigned to the smaller component id so the split is
        # deterministic; it is an approximation the evaluation harness tightens with weights.
        group = min(ta.component_id, tb.component_id)
        out.append(LabeledPair(pair.record_a_id, pair.record_b_id, int(ta.entity_id == tb.entity_id), group))
    return out


def design_row(a: Normalized, b: Normalized) -> list[float]:
    fv = compute_features(a, b)
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


def _raw_scores(model: LogisticRegression, X: np.ndarray) -> np.ndarray:
    return model.decision_function(X)


def data_digest(*paths: Path, partition: str | None, c: float, folds: int) -> str:
    """Digest of the inputs and the settings that change the fit, so runs never overwrite each other."""
    h = hashlib.sha256()
    for path in paths:
        h.update(path.read_bytes())
    h.update(f"|partition={partition}|C={c}|folds={folds}".encode())
    return h.hexdigest()[:DIGEST_CHARS]


def fit_weights(
    records: Mapping[str, Normalized],
    truth: Mapping[str, TruthRow],
    *,
    version: str,
    n_folds: int = DEFAULT_FOLDS,
    c: float = DEFAULT_C,
    provenance: Mapping[str, Any] | None = None,
) -> tuple[Weights, dict[str, Any], list[dict[str, Any]]]:
    """(weights, out-of-fold report, out-of-fold rows). Raises when a class or group count is too small."""
    pairs = build_labeled_pairs(records, truth)
    if not pairs:
        raise ValueError("no blocked pairs among labeled records")
    X, y, groups = design_matrix(pairs, records)
    if y.min() == y.max():
        raise ValueError("training pairs contain only one class")
    n_groups = len(set(groups))
    folds = min(n_folds, n_groups)
    if folds < 2:
        raise ValueError(f"need at least 2 components for grouped CV, got {n_groups}")
    oof = np.full(len(pairs), np.nan)
    for train_idx, test_idx in GroupKFold(n_splits=folds).split(X, y, groups):
        if y[train_idx].min() == y[train_idx].max():
            raise ValueError("a training fold has one class; add components or reduce folds")
        oof[test_idx] = _raw_scores(_new_model(c).fit(X[train_idx], y[train_idx]), X[test_idx])
    final = _new_model(c).fit(X, y)
    weights = Weights(
        scorer_version=version,
        intercept=float(final.intercept_[0]),
        weights={name: float(w) for name, w in zip(ALL_WEIGHT_NAMES, final.coef_[0], strict=True)},
        trained_on={
            **dict(provenance or {}),  # provenance first: the computed keys below always win
            "n_pairs": len(pairs),
            "n_positive": int(y.sum()),
            "n_components": n_groups,
            "n_folds": folds,
            "C": c,
        },
    )
    predicted_positive = oof >= 0.0
    tp = int(((y == 1) & predicted_positive).sum())
    report = {
        "scorer_version": version,
        "n_pairs": len(pairs),
        "n_positive": int(y.sum()),
        "n_components": n_groups,
        "n_folds": folds,
        "oof_auc": float(roc_auc_score(y, oof)),
        "oof_average_precision": float(average_precision_score(y, oof)),
        "oof_precision_at_raw_0": tp / max(int(predicted_positive.sum()), 1),
        "oof_recall_at_raw_0": tp / max(int(y.sum()), 1),
        "note": (
            "development, out-of-fold, descriptive; thresholds and Platt are chosen elsewhere on these raw scores. "
            "A cross-component negative pair is grouped under the smaller component id, so the other component's "
            "records can appear on both sides of a fold through it; the harness resamples by component to tighten this."
        ),
    }
    oof_rows = [
        {
            "record_a_id": p.record_a_id,
            "record_b_id": p.record_b_id,
            "label": p.label,
            "group": p.group,
            "raw_score": float(s),
        }
        for p, s in zip(pairs, oof, strict=True)
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
    parser.add_argument("--partition", default=None, help="keep only truth rows with this partition value")
    parser.add_argument("--folds", type=int, default=DEFAULT_FOLDS)
    parser.add_argument("--c", type=float, default=DEFAULT_C)
    args = parser.parse_args(argv)

    records = load_records_csv(args.records)
    truth = load_truth_csv(args.truth, partition=args.partition)
    digest = data_digest(args.records, args.truth, partition=args.partition, c=args.c, folds=args.folds)
    version = args.version or f"{VERSION_PREFIX}-{digest}"
    provenance = {
        "data_digest": digest,
        "partition": args.partition,
        "records": args.records.name,
        "truth": args.truth.name,
    }
    weights, report, oof_rows = fit_weights(
        records, truth, version=version, n_folds=args.folds, c=args.c, provenance=provenance
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
