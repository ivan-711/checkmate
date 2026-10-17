"""The production evaluation inputs: W1's corpus and W2's engine, the code the app runs.

The production command (``python -m eval.harness.run``) measures the product, so a product
regression moves the published numbers:

- corpus: ``backend.ingest`` (W1) over the Synthea Nov 2021 sample in ``data/raw`` (downloaded and
  hash-checked by ``data/download.py``), with W1's own truth table, grafts and split assignment;
- engine: ``backend.core`` (W2): ``block.candidate_pairs`` for blocking, ``band.match`` for the
  score and band, the shipped ``api.CORE.weights``; refit per training fold with
  ``train.fit_weights`` only when the shipped weights were trained (``trained_on`` non-empty).

Either one missing raises ``ProductUnavailable``; the production command exits non-zero and never
falls back to the stand-in. ``eval.harness.standin`` and ``eval.harness.fixture`` exist only for the
harness's own unit tests. ``CHECKMATE_ENGINE_PACKAGE`` (default ``backend.core``) names the engine
package so a reviewer can point the harness at a branch copy without installing it.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from contracts.models.thresholds import ThresholdSet
from contracts.version import BLOCK_MAX_RECORDS
from eval.harness.splits import Assignment
from eval.harness.types import BlockFn, Corpus, FitFn, MatchFn, MatchResult, Record, TruthRow, pair_key

ENGINE_PACKAGE_ENV = "CHECKMATE_ENGINE_PACKAGE"
DEFAULT_ENGINE_PACKAGE = "backend.core"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw"
HASHES_FILE = REPO_ROOT / "data" / "HASHES.json"
HARNESS_THRESHOLDS_ID = "harness-sweep"   # the harness sweeps cutoffs; bands are recomputed from the raw score
NO_EDIT_FAMILIES = frozenset({"NONE", ""})


class ProductUnavailable(RuntimeError):
    """The production command cannot measure the product (engine or corpus absent)."""


class EngineWeights(Mapping):
    """The engine's weights object, readable as ``{feature: weight, "intercept": b}`` by the export."""

    def __init__(self, native: Any) -> None:
        self.native = native
        self._flat = {**dict(native.weights), "intercept": float(native.intercept)}

    def __getitem__(self, key: str) -> float:
        return self._flat[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._flat)

    def __len__(self) -> int:
        return len(self._flat)


@dataclass
class Engine:
    match: MatchFn
    fit: FitFn
    block: BlockFn
    scorer_version: str
    provenance: dict = field(default_factory=dict)


def engine_input(rec: Record) -> dict:
    """Scorer inputs only: demographics. Truth (entity, person, categories) never reaches the engine."""
    return {"record_id": rec.get("record_id"), "given_name": rec.get("given_name"),
            "family_name": rec.get("family_name"), "birth_date": rec.get("birth_date"), "sex": rec.get("sex"),
            "phone": rec.get("phone"), "address_line": rec.get("address_line"), "zip": rec.get("zip5"),
            "zip5": rec.get("zip5")}


def _package_sha256(package: Any) -> str:
    """sha256 over every source file of the engine package, sorted by path: the code that was measured."""
    root = Path(package.__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".json"} and "__pycache__" not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def load_engine(package_name: str | None = None) -> Engine:
    name = package_name or os.environ.get(ENGINE_PACKAGE_ENV, DEFAULT_ENGINE_PACKAGE)
    try:
        package = importlib.import_module(name)
        api = importlib.import_module(f"{name}.api")
        band = importlib.import_module(f"{name}.band")
        block = importlib.import_module(f"{name}.block")
        normalize = importlib.import_module(f"{name}.normalize")
    except ImportError as exc:
        raise ProductUnavailable(f"{name} (W2's engine) is not importable: {exc}. The production evaluation "
                                 "command measures the product and never falls back to the stand-in.") from exc
    shipped = api.CORE.weights

    def match(a: Record, b: Record, weights: Mapping[str, float], thresholds: Mapping[str, float]) -> MatchResult:
        native = weights.native if isinstance(weights, EngineWeights) else shipped
        ts = ThresholdSet(thresholds_id=HARNESS_THRESHOLDS_ID, c_low=thresholds["c_low"], c_high=thresholds["c_high"])
        r = band.match(engine_input(a), engine_input(b), native, ts)
        return MatchResult(raw_score=float(r.raw_score), p=float(r.p), band=str(getattr(r.band, "value", r.band)),
                           contributions=tuple((c.feature, float(c.logit)) for c in r.contributions),
                           negative_rules_fired=tuple(str(getattr(x, "value", x)) for x in r.negative_rules_fired),
                           features=tuple(r.features.items()))

    def block_fn(records: Sequence[Record]) -> set[tuple[str, str]]:
        normalized = {r["record_id"]: normalize.coerce_normalized(engine_input(r)) for r in records}
        result = block.candidate_pairs(normalized, max_block_records=BLOCK_MAX_RECORDS)
        return {pair_key(str(p.record_a_id), str(p.record_b_id)) for p in result.pairs}

    trained = bool(getattr(shipped, "trained_on", None))

    def fit(records: Sequence[Record], truth: Sequence[TruthRow]) -> Mapping[str, float]:
        if not trained:
            return EngineWeights(shipped)  # hand-set weights: no parameter is learned from any partition
        try:
            train = importlib.import_module(f"{name}.train")
        except ImportError as exc:
            raise ProductUnavailable(f"{name}.train is needed to refit trained weights per fold: {exc}") from exc
        by_id = {t.record_id: t for t in truth}
        rows = {r["record_id"]: train.TruthRow(entity_id=by_id[r["record_id"]].entity_id,
                                               component_id=by_id[r["record_id"]].synthea_patient_id, partition=None)
                for r in records if r["record_id"] in by_id}
        normalized = {r["record_id"]: normalize.coerce_normalized(engine_input(r)) for r in records if r["record_id"] in rows}
        weights, _, _ = train.fit_weights(normalized, rows, version=f"{shipped.scorer_version}+fold")
        return EngineWeights(weights)

    weights_json = shipped.to_json_dict() if hasattr(shipped, "to_json_dict") else {}
    provenance = {
        "engine": name, "engineSha256": _package_sha256(package), "scorerVersion": shipped.scorer_version,
        "weightsSha256": hashlib.sha256(json.dumps(weights_json, sort_keys=True).encode()).hexdigest(),
        "trainedOn": dict(getattr(shipped, "trained_on", {}) or {}),
        "fit": ("refit per training fold with train.fit_weights" if trained
                else "shipped hand-set weights; no parameter is learned, so no fold can leak into them"),
        "block": f"{name}.block.candidate_pairs (blocks over {BLOCK_MAX_RECORDS} records skipped)",
        "match": f"{name}.band.match",
    }
    return Engine(match=match, fit=fit, block=block_fn, scorer_version=shipped.scorer_version, provenance=provenance)


def _language(identity: Any, corruptor: Any) -> str:
    return "ES" if corruptor.is_spanish(identity) else "EN"


def load_corpus(seed: int, raw_dir: Path = DEFAULT_RAW_DIR) -> tuple[Corpus, dict]:
    """W1's seeded corpus as harness records, W1's truth and W1's split (assigned before generation)."""
    try:
        cli = importlib.import_module("backend.ingest.cli")
        corruptor = importlib.import_module("backend.ingest.corruptor")
    except ImportError as exc:
        raise ProductUnavailable(f"backend.ingest (W1's corpus) is not importable: {exc}") from exc
    if not (raw_dir / "fhir").is_dir() or not (raw_dir / "csv" / "patients.csv").exists():
        raise ProductUnavailable(f"no Synthea sample under {raw_dir}; run `uv run python data/download.py` first")
    bundles, csv_patients = cli.load_sample(raw_dir)
    out = corruptor.build_corpus(seed, bundles, csv_patients)
    donors: dict[str, list[str]] = {}
    for g in out.grafts:
        donors.setdefault(g.recipient_id, []).append(g.donor_id)
    records: list[Record] = []
    truth: list[TruthRow] = []
    person_language: dict[str, str] = {}
    for rec in out.records:
        ident = rec.draft.identity
        rid = str(rec.draft.id)
        language = _language(ident, corruptor)
        person_language.setdefault(rec.synthea_id, language)
        records.append({
            "record_id": rid, "person_id": rec.synthea_id, "entity_id": rec.entity_id,
            "source_system": rec.draft.source_system, "given_name": ident.given, "family_name": ident.family,
            "birth_date": ident.birth_date, "sex": ident.sex, "phone": ident.phone,
            "address_line": ident.address_line, "zip5": ident.postal_code, "language": language,
            "categories": [] if rec.family in NO_EDIT_FAMILIES else [rec.family],
            "donor_person_ids": sorted(donors.get(rec.synthea_id, [])),
        })
        truth.append(TruthRow(entity_id=rec.entity_id, record_id=rid, source_system=rec.draft.source_system,
                              synthea_patient_id=rec.synthea_id))
    component_of = {m: comp for comp, s in out.splits.items() for m in s["members"]}
    assignment = Assignment(
        component_of_person=component_of,
        partition_of_component={comp: s["partition"] for comp, s in out.splits.items()},
        fold_of_component={comp: s["fold"] for comp, s in out.splits.items() if s["partition"] == "development"},
        components={comp: sorted(s["members"]) for comp, s in out.splits.items()},
    )
    corpus = Corpus(records=records, truth=truth, dependency_edges=[(g.donor_id, g.recipient_id) for g in out.grafts],
                    person_language=person_language, assignment=assignment)
    hashes = json.loads(HASHES_FILE.read_text()) if HASHES_FILE.exists() else {}
    provenance = {
        "corpus": "backend.ingest.corruptor.build_corpus", "seed": seed, "rawDir": str(raw_dir),
        "corpusFingerprint": out.run.get("corpus_fingerprint"), "syntheaSourceHashes": {k: v.get("sha256") for k, v in hashes.items()},
        "entities": out.run.get("entities"), "records": out.run.get("records"), "grafts": out.run.get("grafts"),
        "w1HeldOutFamiliesDrawn": list(out.heldout_families),
        "w1HeldOutNote": out.run.get("heldout_note"),
    }
    return corpus, provenance
