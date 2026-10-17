"""Corpus mode on W1's real loaders, with a hero directory shaped exactly like W5's export.

* Raw sample: W1's committed fixtures laid out as ``fhir/`` + ``csv/``.
* Hero: the fixture entity that has exactly one ER and one Clinic record (W1's corpus for seed
  20261017), named in a ``hero.json`` the way W5 names the hero (``records.<SYSTEM>.record_id``).
* Overlay: ``fixtures/w5_hero_overlay/`` holds W5's own overlay files, copied verbatim from
  origin/lane/w5 at b7db0f6 (``data/scenarios/hero/{fhir/hero_er.json,csv/allergies.csv,csv/patients.csv}``),
  so the loader is tested against the constructed markers and overlay patient ids W5 really writes.
"""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pytest

from backend.scenarios import loader

W1_FIXTURES = loader.REPO_ROOT / "backend" / "tests" / "ingest" / "fixtures"
W5_OVERLAY = Path(__file__).parent / "fixtures" / "w5_hero_overlay"
SEED = loader.DEFAULT_CORPUS_SEED
# The overlay's own patient ids (W5's uuid5 "er-patient" / clinic patient): never inserted as records.
OVERLAY_PATIENT_IDS = ("a6ca1cf3-951c-5f5a-91f6-ddf788b4aab1", "270d9b1e-1293-5791-947a-95c106c286af")


@dataclass(frozen=True)
class HeroCorpus:
    raw: Path
    hero_dir: Path
    er_id: str
    clinic_id: str
    corpus_size: int
    hero_given: str
    hero_birth_date: str


def _raw_sample(root: Path) -> Path:
    raw = root / "raw"
    (raw / "fhir").mkdir(parents=True)
    shutil.copytree(W1_FIXTURES / "csv", raw / "csv")
    for name in ("bundle_a.json", "bundle_b.json"):
        shutil.copy(W1_FIXTURES / name, raw / "fhir" / name)
    return raw


def _hero_entity(raw: Path):
    """W1's corpus, and the entity with exactly one ER and one Clinic record."""
    from backend.ingest.cli import load_sample
    from backend.ingest.corruptor import build_corpus

    records = build_corpus(SEED, *load_sample(raw)).records
    by_entity = defaultdict(list)
    for rec in records:
        by_entity[rec.entity_id].append(rec.draft)
    for drafts in by_entity.values():
        systems = sorted(d.source_system for d in drafts)
        if systems == ["CLINIC_CSV", "ER_FHIR"]:
            return len(records), {d.source_system: d for d in drafts}
    raise AssertionError("no W1 fixture entity with exactly one ER and one Clinic record")


def write_hero_dir(root: Path, er_id: str | None, clinic_id: str | None, overlay: bool = True) -> Path:
    hero_dir = root / "hero"
    if overlay:
        shutil.copytree(W5_OVERLAY, hero_dir)
    else:
        hero_dir.mkdir(parents=True)
    records = {}
    if er_id:
        records["ER_FHIR"] = {"record_id": er_id}
    if clinic_id:
        records["CLINIC_CSV"] = {"record_id": clinic_id}
    (hero_dir / loader.HERO_EXPORT_FILE).write_text(json.dumps({"records": records}))
    return hero_dir


@pytest.fixture
def hero_corpus(tmp_path, monkeypatch) -> HeroCorpus:
    pytest.importorskip("backend.ingest.cli")
    raw = _raw_sample(tmp_path)
    corpus_size, hero = _hero_entity(raw)
    er, clinic = hero["ER_FHIR"], hero["CLINIC_CSV"]
    hero_dir = write_hero_dir(tmp_path, str(er.id), str(clinic.id))
    monkeypatch.setenv("CHECKMATE_HERO_SOURCE", "corpus")
    monkeypatch.setenv("CHECKMATE_RAW_DIR", str(raw))
    monkeypatch.setenv("CHECKMATE_HERO_OVERLAY_DIR", str(hero_dir))
    loader._corpus_cards.cache_clear()
    yield HeroCorpus(
        raw=raw,
        hero_dir=hero_dir,
        er_id=str(er.id),
        clinic_id=str(clinic.id),
        corpus_size=corpus_size,
        hero_given=er.identity.given,
        hero_birth_date=er.identity.birth_date,
    )
    loader._corpus_cards.cache_clear()
