"""Scenario loading seam for ``POST /sessions``.

Two sources, chosen by ``CHECKMATE_HERO_SOURCE``:

* ``fixture`` (default): the frozen fixture shapes in ``contracts/fixtures/scenario.json``
  (watermarked placeholders), as W3a built and tested the routes against.
* ``corpus``: W1's loader and corruption generator over the Synthea sample under
  ``CHECKMATE_RAW_DIR`` (default ``data/raw``) for ``CHECKMATE_CORPUS_SEED`` (default 20261017):
  the same records, with the same ids, that ``python -m backend.ingest.cli load`` writes. The hero is
  W5's export in ``CHECKMATE_HERO_OVERLAY_DIR`` (default ``data/scenarios/hero/``): ``hero.json``
  names the hero's two corpus records, and the constructed overlay (``fhir/*.json``, ``csv/``) is
  applied to those two records' payloads (evaluation doc §5): clinical content only, ids and identity
  exactly as selected, both labeled ``is_constructed``. No overlay record is inserted, so the hero
  exists once, as two records, and those two are the showcase.

Both keep the signature the route is coded against:

    load_scenario(scenario_id: str) -> Scenario   (raises ScenarioNotFound)

``hero`` loads every source card; ``frontdesk-hero`` loads all but the ER FHIR records, because the
intake plays the ER registration (architecture §9.1).

W1 is reached only through the two ``_w1_*`` functions, imported lazily so the fixture mode never
needs W1's modules or the raw sample. W5's files are read, never written.
"""

from __future__ import annotations

import copy
import csv
import json
import logging
import os
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from uuid import UUID

from contracts.models.records import NormalizedRecord, SourceCard, SourceRecord

log = logging.getLogger("checkmate.scenarios")

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "contracts" / "fixtures" / "scenario.json"
HERO_OVERLAY_DIR = REPO_ROOT / "data" / "scenarios" / "hero"
RAW_DIR = REPO_ROOT / "data" / "raw"
ER_SOURCE_SYSTEM = "ER_FHIR"
CLINIC_SOURCE_SYSTEM = "CLINIC_CSV"
DISPLAY_LABEL = {"ER_FHIR": "ER FHIR", "CLINIC_CSV": "Clinic CSV"}
HERO_SOURCE_FIXTURE = "fixture"
HERO_SOURCE_CORPUS = "corpus"
DEFAULT_CORPUS_SEED = 20261017
SCENARIO_IDS = ("hero", "frontdesk-hero")
HERO_EXPORT_FILE = "hero.json"  # W5's export, beside the overlay
SHOWCASE_ORDER = {"ER_FHIR": 0, "CLINIC_CSV": 1}  # the order the UI lays the cards out
# W5's constructed markers (scenario_manifest.json metaTag; the allergies.csv CONSTRUCTED column)
CONSTRUCTED_TAG_SYSTEM = "urn:chartguard:provenance"
CONSTRUCTED_TAG_CODE = "constructed-scenario"
CONSTRUCTED_COLUMN = "CONSTRUCTED"
TRUTHY = frozenset({"true", "1", "yes", "y"})
# Where a constructed FHIR resource goes in W1's ER payload; an AllergyIntolerance is refused (no ER allergy history).
FHIR_LIST_FOR_TYPE = {"Encounter": "encounters", "MedicationRequest": "medicationRequests", "Medication": "medications"}


class ScenarioNotFound(LookupError):
    pass


class HeroNotFound(ScenarioNotFound):
    """Corpus mode cannot find the hero: a reset must not go ahead with no showcase. The message names
    what is missing, never a file path; the directory goes to the log only."""


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


def _w1_normalize(identity):
    """W1's ``normalized_record`` row for one identity, the same row ``cli load`` stores (issue #10),
    with attribute access so ``_card_from_draft`` reads it like any normalized record."""
    from types import SimpleNamespace

    from backend.ingest.normalize import normalized_row

    return SimpleNamespace(**normalized_row(identity))


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


# --- the hero: W5's export applied to the hero's own records (evaluation doc §5) ------------------


@dataclass(frozen=True)
class HeroExport:
    """What W5's hero directory says: the hero's record id per source system (``hero.json``) and the
    constructed clinical items of the overlay, with the overlay patient ids they reference."""

    record_ids: dict[str, UUID] = field(default_factory=dict)
    fhir_resources: list[dict] = field(default_factory=list)
    fhir_patient_ids: set[str] = field(default_factory=set)
    allergy_rows: list[dict] = field(default_factory=list)
    csv_patient_ids: set[str] = field(default_factory=set)


def _is_constructed_resource(resource: dict) -> bool:
    return any(
        t.get("system") == CONSTRUCTED_TAG_SYSTEM and t.get("code") == CONSTRUCTED_TAG_CODE
        for t in (resource.get("meta") or {}).get("tag") or []
    )


def _read_hero_dir(hero_dir: Path) -> HeroExport:
    """Reads ``hero.json`` and the overlay's constructed markers: FHIR resources tagged
    ``urn:chartguard:provenance#constructed-scenario`` and allergy rows with a true ``CONSTRUCTED``."""
    export = HeroExport()
    hero_json = hero_dir / HERO_EXPORT_FILE
    if hero_json.exists():
        records = json.loads(hero_json.read_text()).get("records", {})
        export.record_ids.update({system: UUID(r["record_id"]) for system, r in records.items() if r.get("record_id")})
    for bundle_path in sorted((hero_dir / "fhir").glob("*.json")):
        for entry in json.loads(bundle_path.read_text()).get("entry", []):
            resource = entry.get("resource") or {}
            if not _is_constructed_resource(resource):
                continue
            if resource.get("resourceType") == "Patient":  # identity stays exactly as selected
                export.fhir_patient_ids.add(resource["id"])
            else:
                export.fhir_resources.append(resource)
    allergies_csv = hero_dir / "csv" / "allergies.csv"
    if allergies_csv.exists():
        with allergies_csv.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if (row.get(CONSTRUCTED_COLUMN) or "").strip().lower() in TRUTHY:
                    export.allergy_rows.append(row)
                    export.csv_patient_ids.add(row["PATIENT"])
    return export


def _repoint(value, old_ids: set[str], new_id: str):
    """Every reference to an overlay patient id now names the hero record (ids are uuids: one textual pass
    is exact, the way W1 re-mints ids)."""
    text = json.dumps(value, ensure_ascii=False)
    for old in old_ids:
        text = text.replace(old, new_id)
    return json.loads(text)


def _with_er_overlay(draft, export: HeroExport):
    """The ER registration as the scenario needs it: the constructed encounter and order added, no
    allergy history (the manifest's ``erAllergyHistory: absent by construction``)."""
    payload = copy.deepcopy(draft.raw_payload)
    patient_id = (payload.get("patient") or {}).get("id") or str(draft.id)
    for resource in _repoint(export.fhir_resources, export.fhir_patient_ids, patient_id):
        kind = resource.get("resourceType")
        if kind not in FHIR_LIST_FOR_TYPE:
            raise ValueError(
                f"the ER overlay carries a constructed {kind}; only {sorted(FHIR_LIST_FOR_TYPE)} are applied"
            )
        payload.setdefault(FHIR_LIST_FOR_TYPE[kind], []).append(resource)
    payload["allergyIntolerances"] = []
    return replace(draft, raw_payload=payload, is_constructed=True)


def _with_clinic_overlay(draft, export: HeroExport):
    """The Clinic CSV record with the constructed allergy rows (their CONSTRUCTED column kept)."""
    payload = copy.deepcopy(draft.raw_payload)
    payload.setdefault("allergies", []).extend(
        _repoint(export.allergy_rows, export.csv_patient_ids, draft.source_local_id)
    )
    return replace(draft, raw_payload=payload, is_constructed=True)


def _apply_hero_export(drafts: list, export: HeroExport) -> list:
    by_id = {d.id: d for d in drafts}
    applied = {}
    er_id, clinic_id = export.record_ids.get(ER_SOURCE_SYSTEM), export.record_ids.get(CLINIC_SOURCE_SYSTEM)
    if er_id is not None and export.fhir_resources:
        applied[er_id] = _with_er_overlay(by_id[er_id], export)
    if clinic_id is not None and export.allergy_rows:
        applied[clinic_id] = _with_clinic_overlay(by_id[clinic_id], export)
    return [applied.get(d.id, d) for d in drafts]


@cache
def _corpus_cards(seed: int, raw_dir: Path, overlay_dir: Path) -> Corpus:
    """Built once per (seed, raw dir, hero dir): read-only input, the same ids on every reset.
    The hero dir is part of the key so pointing the env var elsewhere is never silently ignored."""
    ingested_at = datetime.now(UTC)
    export = _read_hero_dir(overlay_dir)
    if not export.record_ids:  # checked before W1's corpus build, which takes seconds
        log.warning("corpus mode: no hero export (%s) in %s", HERO_EXPORT_FILE, overlay_dir)
        raise HeroNotFound("hero scenario not found: corpus mode needs the hero export (hero.json)")
    drafts = _w1_corpus_drafts(seed, raw_dir)
    loaded = {d.id for d in drafts}
    missing = sorted(f"{system} {rid}" for system, rid in export.record_ids.items() if rid not in loaded)
    if missing:
        log.warning("corpus mode: hero.json in %s names records the loaded corpus lacks: %s", overlay_dir, missing)
        raise HeroNotFound("hero scenario not found: hero.json names records the loaded corpus lacks")
    drafts = _apply_hero_export(drafts, export)
    showcase = sorted(export.record_ids.items(), key=lambda item: SHOWCASE_ORDER.get(item[0], len(SHOWCASE_ORDER)))
    return Corpus(
        cards=tuple(_card_from_draft(d, ingested_at) for d in drafts),
        showcase_ids=tuple(rid for _, rid in showcase),
    )


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
