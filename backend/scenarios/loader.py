"""Scenario loading seam for ``POST /sessions``.

Two sources, chosen by ``CHECKMATE_HERO_SOURCE``:

* ``fixture`` (default): the frozen fixture shapes in ``contracts/fixtures/scenario.json``
  (watermarked placeholders), as W3a built and tested the routes against.
* ``corpus``: W1's loader and corruption generator over the Synthea sample under
  ``CHECKMATE_RAW_DIR`` (default ``data/raw``) for ``CHECKMATE_CORPUS_SEED`` (default 20261017):
  the same records, with the same ids, that ``python -m backend.ingest.cli load`` writes, plus the
  constructed overlay under ``CHECKMATE_HERO_OVERLAY_DIR`` (default ``data/scenarios/hero/``:
  ``fhir/*.json`` bundles and ``csv/``), every overlay record labeled ``is_constructed``.

Both keep the signature the route is coded against:

    load_scenario(scenario_id: str) -> Scenario   (raises ScenarioNotFound)

``hero`` loads every source card; ``frontdesk-hero`` loads all but the ER FHIR records, because the
intake plays the ER registration (architecture §9.1).

W1 is reached only through the three ``_w1_*`` functions, imported lazily so the fixture mode never
needs W1's modules or the raw sample.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from uuid import UUID

from contracts.models.records import NormalizedRecord, SourceCard, SourceRecord

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "contracts" / "fixtures" / "scenario.json"
HERO_OVERLAY_DIR = REPO_ROOT / "data" / "scenarios" / "hero"
RAW_DIR = REPO_ROOT / "data" / "raw"
ER_SOURCE_SYSTEM = "ER_FHIR"
DISPLAY_LABEL = {"ER_FHIR": "ER FHIR", "CLINIC_CSV": "Clinic CSV"}
HERO_SOURCE_FIXTURE = "fixture"
HERO_SOURCE_CORPUS = "corpus"
DEFAULT_CORPUS_SEED = 20261017
SCENARIO_IDS = ("hero", "frontdesk-hero")
HERO_EXPORT_FILE = "hero.json"  # W5's export, beside the overlay
SHOWCASE_ORDER = {"ER_FHIR": 0, "CLINIC_CSV": 1}  # the order the UI lays the cards out


class ScenarioNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    sources: list[SourceCard]  # every record the reset loads; match runs score all of them
    showcase: list[SourceCard]  # SessionResponse.sources: the hero pair's cards, never the whole corpus
    hero_provisional: bool
    hero_constructed_floor: bool


@dataclass(frozen=True)
class Corpus:
    cards: tuple[SourceCard, ...]
    showcase_ids: tuple[UUID, ...]


@cache
def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _fixture_cards() -> list[SourceCard]:
    return [SourceCard.model_validate(s) for s in _fixture()["session"]["sources"]]


# --- the W1 boundary --------------------------------------------------------------------------


def _w1_corpus_drafts(seed: int, raw_dir: Path) -> list:
    """W1's seeded corpus: ``SourceRecordDraft``s with deterministic ids."""
    from backend.ingest.cli import load_sample
    from backend.ingest.corruptor import build_corpus

    bundles, csv_patients = load_sample(raw_dir)
    return [rec.draft for rec in build_corpus(seed, bundles, csv_patients).records]


def _w1_overlay_drafts(overlay_dir: Path) -> list:
    """Constructed records under the overlay dir, through W1's loaders, labeled is_constructed."""
    from backend.ingest.csvio import read_csv_dir
    from backend.ingest.fhir import iter_bundle_paths, load_bundle
    from backend.ingest.records import csv_draft, fhir_draft

    drafts = []
    fhir_dir, csv_dir = overlay_dir / "fhir", overlay_dir / "csv"
    if fhir_dir.is_dir():
        for path in iter_bundle_paths(fhir_dir):
            bundle = load_bundle(path)
            drafts.append(fhir_draft(bundle.identity, bundle, bundle.patient_id, is_constructed=True))
    if (csv_dir / "patients.csv").exists():
        for patient in read_csv_dir(csv_dir).values():
            drafts.append(
                csv_draft(patient.identity, patient, patient.patient_id, include_phone=True, is_constructed=True)
            )
    return drafts


def _w1_normalize(identity):
    from backend.ingest.normalize import normalize_identity

    return normalize_identity(identity)


# --- drafts to contract cards -----------------------------------------------------------------


def _card_from_draft(draft, ingested_at: datetime) -> SourceCard:
    """W1's ``SourceRecordDraft`` (raw payload + identity) to the contract card the route inserts."""
    fields = _w1_normalize(draft.identity)
    record = SourceRecord(
        id=draft.id,
        source_system=draft.source_system,
        source_local_id=draft.source_local_id,
        kind=draft.kind,
        payload_sha256=draft.sha256,
        is_constructed=draft.is_constructed,
        ingested_at=ingested_at,
        raw_payload=draft.raw_payload,
    )
    normalized = NormalizedRecord(
        record_id=draft.id,
        given_name=fields.given_name,
        family_name=fields.family_name,
        given_name_folded=fields.given_name_folded,
        family_name_folded=fields.family_name_folded,
        birth_date=fields.birth_date,
        sex=fields.sex,
        phone_e164=fields.phone_e164,
        address_line=fields.address_line,
        zip5=fields.zip5,
    )
    label = DISPLAY_LABEL.get(draft.source_system, draft.source_system)
    return SourceCard(record=record, normalized=normalized, display_label=label)


@cache
def _corpus_cards(seed: int, raw_dir: Path, overlay_dir: Path) -> Corpus:
    """Built once per (seed, raw dir, overlay dir): read-only input, the same ids on every reset.
    The overlay dir is part of the key so pointing the env var elsewhere is never silently ignored."""
    ingested_at = datetime.now(UTC)
    overlay = _w1_overlay_drafts(overlay_dir)
    drafts = _w1_corpus_drafts(seed, raw_dir) + overlay
    _refuse_duplicate_ids(drafts)
    cards = tuple(_card_from_draft(d, ingested_at) for d in drafts)
    return Corpus(cards=cards, showcase_ids=_showcase_ids(cards, {d.id for d in overlay}, overlay_dir))


def _showcase_ids(cards: tuple[SourceCard, ...], overlay_ids: set, overlay_dir: Path) -> tuple[UUID, ...]:
    """The hero pair's records, ER first. The constructed overlay when there is one: W5 writes the hero's
    ER registration and Clinic row there with the identity exactly as selected plus the clinical content
    BL-AMOX-01 needs, so they are the pair the demo approves. Otherwise hero.json's records, if loaded."""
    wanted = overlay_ids or _hero_json_record_ids(overlay_dir)
    chosen = [c for c in cards if c.record.id in wanted]
    chosen.sort(key=lambda c: (SHOWCASE_ORDER.get(c.record.source_system, len(SHOWCASE_ORDER)), str(c.record.id)))
    return tuple(c.record.id for c in chosen)


def _hero_json_record_ids(hero_dir: Path) -> set[UUID]:
    """W5's hero export names the hero pair by record id: ``records.<SOURCE_SYSTEM>.record_id``."""
    path = hero_dir / HERO_EXPORT_FILE
    if not path.exists():
        return set()
    records = json.loads(path.read_text()).get("records", {})
    return {UUID(r["record_id"]) for r in records.values() if r.get("record_id")}


def _refuse_duplicate_ids(drafts: list) -> None:
    """Two drafts with one (source system, local id) would insert as one row (ON CONFLICT DO NOTHING):
    an overlay record colliding with a corpus record would silently lose its is_constructed label."""
    seen: set = set()
    duplicates = []
    for draft in drafts:
        if draft.id in seen:
            duplicates.append(f"{draft.source_system}/{draft.source_local_id}")
        seen.add(draft.id)
    if duplicates:
        raise ValueError(f"scenario records share an id: {', '.join(sorted(duplicates))}")


def _all_cards() -> tuple[list[SourceCard], list[SourceCard]]:
    """(every card to load, the showcase). The fixture is the showcase itself."""
    source = os.environ.get("CHECKMATE_HERO_SOURCE", HERO_SOURCE_FIXTURE)
    if source == HERO_SOURCE_CORPUS:
        corpus = _corpus_cards(
            int(os.environ.get("CHECKMATE_CORPUS_SEED", DEFAULT_CORPUS_SEED)),
            Path(os.environ.get("CHECKMATE_RAW_DIR", str(RAW_DIR))),
            Path(os.environ.get("CHECKMATE_HERO_OVERLAY_DIR", str(HERO_OVERLAY_DIR))),
        )
        by_id = {c.record.id: c for c in corpus.cards}
        return list(corpus.cards), [by_id[i] for i in corpus.showcase_ids]
    if source != HERO_SOURCE_FIXTURE:
        raise ValueError(f"CHECKMATE_HERO_SOURCE must be {HERO_SOURCE_FIXTURE} or {HERO_SOURCE_CORPUS}, not {source!r}")
    cards = _fixture_cards()
    return cards, list(cards)


def load_scenario(scenario_id: str) -> Scenario:
    if scenario_id not in SCENARIO_IDS:
        raise ScenarioNotFound(scenario_id)
    cards, showcase = _all_cards()
    if scenario_id == "frontdesk-hero":
        cards = [c for c in cards if c.record.source_system != ER_SOURCE_SYSTEM]
        showcase = [c for c in showcase if c.record.source_system != ER_SOURCE_SYSTEM]
    hero = _fixture().get("hero", {})
    return Scenario(
        scenario_id=scenario_id,
        sources=cards,
        showcase=showcase,
        hero_provisional=bool(hero.get("provisional", True)),
        hero_constructed_floor=bool(hero.get("constructedFloor", False)),
    )
