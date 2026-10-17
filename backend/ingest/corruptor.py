"""Corruption generator: the P0 core rows of the taxonomy (evaluation plan §2, §3) with a seed.

Per entity (one Synthea person) the generator renders an ER FHIR record, usually a Clinic CSV
record and sometimes a within-system duplicate, applies one sampled family per record, and
writes the hidden truth: truth.csv (entity, record, source, Synthea id, component, split),
pairs.csv (pair id, label, the family that produced it) and labels.jsonl (field, before, after).

Hard negatives are grafts: a donor's demographics written over a recipient who keeps its own
clinical payload. Donor and recipient form one dependency component and inherit one split,
assigned by hash before any record is generated. The same per-record corruption runs on both
sides of a negative pair, so "looks mangled" never separates matches from negatives.

Randomness is stdlib ``random.Random`` seeded per entity from sha256(f"{seed}:{entity}"), so
one entity's stream never depends on another's and the truth table is a function of the seed.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from uuid import UUID, uuid5

from backend.ingest.blocking import swapped_day_month
from backend.ingest.csvio import CsvPatient
from backend.ingest.fhir import FhirPatientBundle
from backend.ingest.normalize import Identity, parse_date, strip_accents
from backend.ingest.records import SOURCE_CLINIC_CSV, SOURCE_ER_FHIR, SourceRecordDraft, csv_draft, fhir_draft

# Taxonomy rows (evaluation plan §2). Core = P0, implemented here; P1 rows land by 19:00 and are
# the pool the held-out draw samples from.
CORE_TRUE_MATCH = ("T1", "T3", "D1", "D3", "L1", "L3", "L7", "S1", "S3", "S5", "S6", "C1")
CORE_HARD_NEGATIVE = ("N1", "N3")
P1_FAMILIES = ("T2", "T4", "T5", "T6", "T7", "S2", "S4", "S7", "S8", "M1", "D2", "D4", "D5", "L2", "L4", "L5", "L6",
               "C2", "C3", "C4", "C5", "N2", "N4", "N5", "N6", "N7", "N8", "N9")
HELDOUT_COUNT = 5
HELDOUT_SPANISH_STRATUM = ("S4", "S7", "S8")
HELDOUT_NEGATIVE_STRATUM = ("N2", "N4", "N5", "N6", "N7", "N8", "N9")
HELDOUT_DOB_ADDRESS_STRATUM = ("D2", "D4", "D5", "L2", "L4", "L5", "L6")
TWO_SURNAME_FAMILIES = frozenset({"S3", "S5"})  # only for Spanish-language entities (eval plan §2)
SPANISH_LANGUAGE_PREFIX = "es"
NO_EDIT = "NONE"
LABEL_SAME = "SAME"
LABEL_NOT_SAME = "NOT_SAME"

# Family weights for the per-record draw; design choices, not observed rates.
FAMILY_WEIGHTS = {"T1": 2.0, "T3": 1.5, "D1": 1.5, "D3": 1.5, "L1": 2.0, "L3": 1.5, "L7": 1.5,
                  "S1": 1.0, "S3": 1.5, "S5": 1.5, "S6": 1.0, "C1": 1.5}
C1_POOL = ("T1", "T3", "D1", "D3", "L1", "L3", "L7")
C1_EDIT_COUNT_WEIGHTS = ((2, 0.7), (3, 0.3))
MAX_FAMILY_DRAWS = 6  # resample a no-op family this many times before emitting an exact copy
FRAGMENT_COUNTS = ((1, 0.15), (2, 0.65), (3, 0.20))  # records per entity: singletons allowed
P_FHIR_BASE_CORRUPTED = 0.3
P_OTHER_RECORD_CORRUPTED = 0.9
P_CLINIC_HAS_PHONE = 0.6
P_SAME_ZIP_ON_MOVE = 0.6
HARD_NEGATIVE_FRACTION = 0.10
SHOWCASE_POOL_SIZE = 20
DEV_FRACTION = 0.70
CV_FOLDS = 5
SIBLING_MAX_YEAR_GAP = 3
PARENT_CHILD_MIN_YEARS = 18
PARENT_CHILD_MAX_YEARS = 40
P_CHILD_HAS_SUFFIX = 0.5
P_HOUSEHOLD_PHONE = 0.5
P_CHILD_IS_RECIPIENT = 0.5
P_S5_HYPHENATE = 0.5  # else the two surnames are glued together
FALLBACK_DONOR_DOB = date(1980, 1, 1)  # only if a donor somehow has no parseable DOB

PAIR_NAMESPACE = UUID("0b8c1d2e-3f4a-4b5c-8d6e-7f8a9b0c1d2e")
ENTITY_NAMESPACE = UUID("9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d")

# Generator-side nickname table. The scoring feature's table (W2) is written separately on purpose.
GENERATOR_NICKNAMES = {
    "Robert": ("Bob", "Rob"), "William": ("Bill", "Will"), "Richard": ("Rick", "Dick"), "James": ("Jim",),
    "John": ("Jack", "Johnny"), "Michael": ("Mike",), "Thomas": ("Tom",), "Charles": ("Chuck", "Charlie"),
    "Joseph": ("Joe",), "Daniel": ("Dan",), "Christopher": ("Chris",), "Matthew": ("Matt",), "Anthony": ("Tony",),
    "Edward": ("Ed", "Eddie"), "Steven": ("Steve",), "Kenneth": ("Ken",), "Andrew": ("Andy",), "Joshua": ("Josh",),
    "Timothy": ("Tim",), "Jeffrey": ("Jeff",), "Elizabeth": ("Liz", "Beth"), "Katherine": ("Kate", "Kathy"),
    "Margaret": ("Peggy", "Maggie"), "Jennifer": ("Jen",), "Patricia": ("Pat", "Patty"), "Susan": ("Sue",),
    "Deborah": ("Debbie",), "Rebecca": ("Becky",), "Samantha": ("Sam",), "Jessica": ("Jess",), "Dorothy": ("Dot",),
    "Barbara": ("Barb",), "Nicholas": ("Nick",), "Benjamin": ("Ben",), "Alexander": ("Alex",), "Jonathan": ("Jon",),
    "Victoria": ("Vicky",), "Abigail": ("Abby",), "Catherine": ("Cathy",), "Theodore": ("Ted",), "Raymond": ("Ray",),
    "Donald": ("Don",), "Ronald": ("Ron",), "Lawrence": ("Larry",), "Frederick": ("Fred",), "Gregory": ("Greg",),
}
STREET_NAMES = ("Maple", "Oak", "Elm", "Cedar", "Pine", "Birch", "Walnut", "Chestnut", "Spruce", "Willow", "Main", "Park")
STREET_TYPES = ("St", "Ave", "Rd", "Ln", "Dr", "Ct")
# Other Massachusetts ZIPs for L1 moves across ZIP; the sample is Massachusetts-only.
OTHER_ZIPS = ("01002", "01040", "01201", "01420", "01545", "01602", "01702", "01803", "01905", "02021", "02118", "02301", "02460", "02571", "02740")
GIVEN_NAME_FALLBACKS = ("Alex", "Sam", "Jordan", "Taylor", "Casey", "Morgan", "Riley", "Jamie")
LETTERS = "abcdefghijklmnopqrstuvwxyz"
MARIA_ABBREVIATION = "Ma."


@dataclass(frozen=True)
class Edit:
    family: str
    field: str
    before: str | None
    after: str | None


@dataclass
class Entity:
    synthea_id: str
    bundle: FhirPatientBundle
    csv: CsvPatient | None
    identity: Identity  # the entity's true identity after Spanish compounding or a graft


@dataclass
class GraftSpec:
    family: str
    donor_id: str
    recipient_id: str


@dataclass
class GeneratedRecord:
    draft: SourceRecordDraft
    entity_id: str
    synthea_id: str
    family: str
    edits: list[Edit]


@dataclass
class CorpusOutput:
    records: list[GeneratedRecord]
    pairs: list[dict]
    truth_rows: list[dict]
    splits: dict[str, dict]
    grafts: list[GraftSpec]
    heldout_families: list[str]
    run: dict
    files: dict[str, Path] = field(default_factory=dict)
    sha256: dict[str, str] = field(default_factory=dict)


def _seed_int(*parts: str) -> int:
    return int(hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest(), 16)


def rng_for(seed: int, *parts: str) -> random.Random:
    return random.Random(_seed_int(str(seed), *parts))


def _weighted(rng: random.Random, options: tuple[tuple[object, float], ...]) -> object:
    return rng.choices([o for o, _ in options], weights=[w for _, w in options], k=1)[0]


def _shift_years(dob: date, years: int) -> date:
    try:
        return dob.replace(year=dob.year + years)
    except ValueError:  # 29 Feb into a common year
        return dob.replace(year=dob.year + years, day=28)


def entity_id_for(synthea_id: str) -> str:
    return str(uuid5(ENTITY_NAMESPACE, synthea_id))


def pair_id_for(record_a: str, record_b: str) -> str:
    a, b = sorted((record_a, record_b))
    return str(uuid5(PAIR_NAMESPACE, f"{a}:{b}"))


def is_spanish(identity: Identity) -> bool:
    return bool(identity.language) and identity.language.lower().startswith(SPANISH_LANGUAGE_PREFIX)


def maternal_surname(mother_maiden: str | None) -> str | None:
    """Last surname of the mother's maiden name, keeping particles ('de Anda', not 'Anda')."""
    tokens = (mother_maiden or "").split()  # digits already stripped by the loader
    return " ".join(tokens[1:]) if len(tokens) > 1 else None


def spanish_base_identity(identity: Identity) -> Identity:
    """Two surnames for Spanish-language entities: paternal = family, maternal from the mother's
    maiden name. Synthea draws the mother's surname independently, so this is an arbitrary
    surname, not a real family relation (evaluation plan §2)."""
    maternal = maternal_surname(identity.mother_maiden)
    if not is_spanish(identity) or not identity.family or not maternal:
        return identity
    return replace(identity, family=f"{identity.family} {maternal}")


# ---- true-match edits: each returns (identity, Edit) or None when the edit would be a no-op ----

def edit_t1(identity: Identity, rng: random.Random) -> tuple[Identity, Edit] | None:
    name = identity.family
    if not name or len(name) < 3:
        return None
    op = rng.choice(("insert", "delete", "substitute"))
    pos = rng.randrange(len(name))
    letter = rng.choice(LETTERS)
    if name[pos].isupper():
        letter = letter.upper()
    if op == "insert":
        after = name[:pos] + letter + name[pos:]
    elif op == "delete":
        after = name[:pos] + name[pos + 1:]
    else:
        if name[pos].lower() == letter.lower():
            return None
        after = name[:pos] + letter + name[pos + 1:]
    return replace(identity, family=after), Edit("T1", "family", name, after)


def edit_t3(identity: Identity, rng: random.Random) -> tuple[Identity, Edit] | None:
    options = GENERATOR_NICKNAMES.get(identity.given or "")
    if not options:
        return None
    after = rng.choice(options)
    return replace(identity, given=after), Edit("T3", "given", identity.given, after)


def edit_d1(identity: Identity, rng: random.Random) -> tuple[Identity, Edit] | None:
    dob = parse_date(identity.birth_date)
    swapped = swapped_day_month(dob) if dob else None
    if swapped is None:
        return None
    after = swapped.isoformat()
    return replace(identity, birth_date=after), Edit("D1", "birth_date", identity.birth_date, after)


def edit_d3(identity: Identity, rng: random.Random) -> tuple[Identity, Edit] | None:
    dob = parse_date(identity.birth_date)
    if dob is None:
        return None
    after = _shift_years(dob, rng.choice((-1, 1))).isoformat()
    return replace(identity, birth_date=after), Edit("D3", "birth_date", identity.birth_date, after)


def edit_l1(identity: Identity, rng: random.Random) -> tuple[Identity, Edit] | None:
    if not identity.address_line:
        return None
    after_line = f"{rng.randint(1, 9999)} {rng.choice(STREET_NAMES)} {rng.choice(STREET_TYPES)}"
    postal = identity.postal_code
    if rng.random() >= P_SAME_ZIP_ON_MOVE:
        postal = rng.choice([z for z in OTHER_ZIPS if z != identity.postal_code])
    changed = replace(identity, address_line=after_line, postal_code=postal)
    return changed, Edit("L1", "address", f"{identity.address_line}|{identity.postal_code}", f"{after_line}|{postal}")


def edit_l3(identity: Identity, rng: random.Random) -> tuple[Identity, Edit] | None:
    if not identity.phone:
        return None
    return replace(identity, phone=None), Edit("L3", "phone", identity.phone, None)


def edit_l7(identity: Identity, rng: random.Random) -> tuple[Identity, Edit] | None:
    if not identity.address_line:
        return None
    changed = replace(identity, address_line=None, city=None, state=None, postal_code=None)
    return changed, Edit("L7", "address", f"{identity.address_line}|{identity.postal_code}", None)


def edit_s1(identity: Identity, rng: random.Random) -> tuple[Identity, Edit] | None:
    before = f"{identity.given or ''}|{identity.family or ''}"
    given = strip_accents(identity.given) if identity.given else None
    family = strip_accents(identity.family) if identity.family else None
    after = f"{given or ''}|{family or ''}"
    if after == before:
        return None
    return replace(identity, given=given, family=family), Edit("S1", "name", before, after)


def edit_s3(identity: Identity, rng: random.Random) -> tuple[Identity, Edit] | None:
    tokens = (identity.family or "").split()
    if len(tokens) < 2:
        return None
    after = tokens[0]
    return replace(identity, family=after), Edit("S3", "family", identity.family, after)


def edit_s5(identity: Identity, rng: random.Random) -> tuple[Identity, Edit] | None:
    name = identity.family or ""
    if "-" in name:
        after = name.replace("-", " ")
    elif " " in name:
        after = name.replace(" ", "-") if rng.random() < P_S5_HYPHENATE else name.replace(" ", "")
    else:
        return None
    return replace(identity, family=after), Edit("S5", "family", name, after)


def edit_s6(identity: Identity, rng: random.Random) -> tuple[Identity, Edit] | None:
    if not identity.given or strip_accents(identity.given).lower() != "maria":
        return None
    return replace(identity, given=MARIA_ABBREVIATION), Edit("S6", "given", identity.given, MARIA_ABBREVIATION)


def edit_c1(identity: Identity, rng: random.Random) -> tuple[Identity, Edit] | None:
    wanted = int(_weighted(rng, C1_EDIT_COUNT_WEIGHTS))
    pool = list(C1_POOL)
    rng.shuffle(pool)
    applied: list[Edit] = []
    current = identity
    for family in pool:
        if len(applied) == wanted:
            break
        outcome = EDITS[family](current, rng)
        if outcome is None:
            continue
        current, edit = outcome
        applied.append(edit)
    if len(applied) < 2:
        return None
    summary = Edit("C1", "+".join(e.family for e in applied),
                   " | ".join(f"{e.field}={e.before}" for e in applied), " | ".join(f"{e.field}={e.after}" for e in applied))
    return current, summary


EDITS: dict[str, Callable[[Identity, random.Random], tuple[Identity, Edit] | None]] = {
    "T1": edit_t1, "T3": edit_t3, "D1": edit_d1, "D3": edit_d3, "L1": edit_l1, "L3": edit_l3, "L7": edit_l7,
    "S1": edit_s1, "S3": edit_s3, "S5": edit_s5, "S6": edit_s6, "C1": edit_c1,
}


def sample_family(rng: random.Random, spanish: bool) -> str:
    options = tuple((f, w) for f, w in FAMILY_WEIGHTS.items() if spanish or f not in TWO_SURNAME_FAMILIES)
    return str(_weighted(rng, options))


def corrupt(identity: Identity, rng: random.Random, spanish: bool) -> tuple[Identity, str, list[Edit]]:
    """Draw families until one changes a value (anti-tautology: no-ops are never counted)."""
    for _ in range(MAX_FAMILY_DRAWS):
        family = sample_family(rng, spanish)
        outcome = EDITS[family](identity, rng)
        if outcome is not None:
            changed, edit = outcome
            return changed, family, [edit]
    return identity, NO_EDIT, []


# ---- hard negatives: grafts ----

def graft(donor: Identity, recipient: Identity, family: str, rng: random.Random) -> Identity:
    """N1 siblings share surname, address and phone with a birth year within 3 and another given
    name; N3 parent/child share the full name and address with DOBs at least 18 years apart."""
    donor_dob = parse_date(donor.birth_date) or FALLBACK_DONOR_DOB
    shared = replace(recipient, family=donor.family, address_line=donor.address_line, city=donor.city,
                     state=donor.state, postal_code=donor.postal_code)
    if family == "N1":
        gap = rng.choice([g for g in range(-SIBLING_MAX_YEAR_GAP, SIBLING_MAX_YEAR_GAP + 1) if g != 0])
        given = recipient.given
        if not given or given == donor.given:
            given = rng.choice([g for g in GIVEN_NAME_FALLBACKS if g != donor.given])
        return replace(shared, given=given, phone=donor.phone, birth_date=_shift_years(donor_dob, gap).isoformat())
    if family == "N3":
        years = rng.randint(PARENT_CHILD_MIN_YEARS, PARENT_CHILD_MAX_YEARS)
        child_is_recipient = rng.random() < P_CHILD_IS_RECIPIENT
        dob = _shift_years(donor_dob, years if child_is_recipient else -years)
        suffix = "Jr." if child_is_recipient and rng.random() < P_CHILD_HAS_SUFFIX else recipient.suffix
        phone = donor.phone if rng.random() < P_HOUSEHOLD_PHONE else recipient.phone
        return replace(shared, given=donor.given, middle=donor.middle, sex=donor.sex, suffix=suffix, phone=phone,
                       birth_date=dob.isoformat())
    raise ValueError(f"unknown hard-negative family {family}")


def plan_grafts(seed: int, entity_ids: list[str]) -> list[GraftSpec]:
    rng = rng_for(seed, "hard-negatives")
    ids = sorted(entity_ids)
    rng.shuffle(ids)
    count = min(int(len(ids) * HARD_NEGATIVE_FRACTION), len(ids) // 2)
    recipients, donors = ids[:count], ids[count:2 * count]
    return [GraftSpec(rng.choice(CORE_HARD_NEGATIVE), donor, recipient) for donor, recipient in zip(donors, recipients)]


# ---- splits: components first, assignment by hash, then generation ----

def components(entity_ids: list[str], grafts: list[GraftSpec]) -> dict[str, str]:
    """Union-find over graft edges; a component is named by its smallest person id."""
    parent = {e: e for e in entity_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for spec in grafts:
        a, b = find(spec.donor_id), find(spec.recipient_id)
        if a != b:
            parent[max(a, b)] = min(a, b)
    return {e: find(e) for e in entity_ids}


def assign_splits(component_of: dict[str, str], language_of: dict[str, str]) -> dict[str, dict]:
    """Showcase pool first, then 70/30 development/test by hash, stratified by language;
    development components get a CV fold in the same pass."""
    members: dict[str, list[str]] = {}
    for entity, comp in component_of.items():
        members.setdefault(comp, []).append(entity)
    ranked = sorted(members, key=lambda c: hashlib.sha256(c.encode()).hexdigest())
    result: dict[str, dict] = {}
    pool, rest = ranked[:SHOWCASE_POOL_SIZE], ranked[SHOWCASE_POOL_SIZE:]
    for comp in pool:
        result[comp] = {"partition": "showcase", "fold": None, "members": sorted(members[comp])}
    by_language: dict[str, list[str]] = {}
    for comp in rest:
        by_language.setdefault(language_of.get(comp, "other"), []).append(comp)
    for comps in by_language.values():
        cut = round(len(comps) * DEV_FRACTION)
        for i, comp in enumerate(comps):
            partition = "development" if i < cut else "test"
            fold = int(hashlib.sha256(comp.encode()).hexdigest(), 16) % CV_FOLDS if partition == "development" else None
            result[comp] = {"partition": partition, "fold": fold, "members": sorted(members[comp])}
    return result


def draw_heldout_families(seed: int) -> list[str]:
    """Five P1 families drawn by seed: one Spanish (S4/S7/S8), one hard negative, one D or L, two more."""
    rng = rng_for(seed, "heldout")
    chosen = [rng.choice(HELDOUT_SPANISH_STRATUM), rng.choice(HELDOUT_NEGATIVE_STRATUM), rng.choice(HELDOUT_DOB_ADDRESS_STRATUM)]
    remaining = [f for f in P1_FAMILIES if f not in chosen]
    chosen.extend(rng.sample(remaining, HELDOUT_COUNT - len(chosen)))
    return chosen


# ---- generation ----

def corpus_fingerprint(seed: int, entity_ids: list[str]) -> str:
    """Seed plus the entity set: grafts depend on which entities exist, so a corpus built from a
    subset (``--limit``) must never share local ids, and thus payloads, with the full one."""
    return hashlib.sha256(f"{seed}:{','.join(sorted(entity_ids))}".encode()).hexdigest()[:12]


def _local_id(fingerprint: str, synthea_id: str, index: int, source: str) -> str:
    prefix = "ER" if source == SOURCE_ER_FHIR else "CL"
    return f"{prefix}-{hashlib.sha256(f'{fingerprint}:{synthea_id}:{index}'.encode()).hexdigest()[:10].upper()}"


def generate_entity(seed: int, fingerprint: str, entity: Entity) -> list[GeneratedRecord]:
    rng = rng_for(seed, entity.synthea_id)
    spanish = is_spanish(entity.bundle.identity)
    n_rec = int(_weighted(rng, FRAGMENT_COUNTS))
    systems = [SOURCE_ER_FHIR]
    if n_rec >= 2 and entity.csv is not None:
        systems.append(SOURCE_CLINIC_CSV)
    if n_rec >= 3:
        systems.append(rng.choice((SOURCE_ER_FHIR, SOURCE_CLINIC_CSV)) if entity.csv is not None else SOURCE_ER_FHIR)

    records: list[GeneratedRecord] = []
    for index, source in enumerate(systems):
        p_corrupt = P_FHIR_BASE_CORRUPTED if index == 0 else P_OTHER_RECORD_CORRUPTED
        identity, family, edits = (corrupt(entity.identity, rng, spanish) if rng.random() < p_corrupt
                                   else (entity.identity, NO_EDIT, []))
        local_id = _local_id(fingerprint, entity.synthea_id, index, source)
        if source == SOURCE_ER_FHIR:
            draft = fhir_draft(identity, entity.bundle, local_id)
        else:
            draft = csv_draft(identity, entity.csv, local_id, include_phone=rng.random() < P_CLINIC_HAS_PHONE)
        records.append(GeneratedRecord(draft, entity_id_for(entity.synthea_id), entity.synthea_id, family, edits))
    return records


def build_entities(bundles: dict[str, FhirPatientBundle], csv_patients: dict[str, CsvPatient]) -> dict[str, Entity]:
    return {
        pid: Entity(pid, bundle, csv_patients.get(pid), spanish_base_identity(bundle.identity))
        for pid, bundle in bundles.items()
    }


def apply_grafts(seed: int, entities: dict[str, Entity], grafts: list[GraftSpec]) -> None:
    for spec in grafts:
        rng = rng_for(seed, "graft", spec.donor_id, spec.recipient_id)
        donor, recipient = entities[spec.donor_id], entities[spec.recipient_id]
        recipient.identity = graft(donor.identity, recipient.identity, spec.family, rng)


def build_corpus(seed: int, bundles: dict[str, FhirPatientBundle], csv_patients: dict[str, CsvPatient]) -> CorpusOutput:
    entities = build_entities(bundles, csv_patients)
    ids = sorted(entities)
    grafts = plan_grafts(seed, ids)
    component_of = components(ids, grafts)
    language_of = {comp: ("es" if is_spanish(entities[comp].bundle.identity) else "other") for comp in set(component_of.values())}
    splits = assign_splits(component_of, language_of)
    apply_grafts(seed, entities, grafts)

    fingerprint = corpus_fingerprint(seed, ids)
    records: list[GeneratedRecord] = []
    for pid in ids:
        records.extend(generate_entity(seed, fingerprint, entities[pid]))

    by_entity: dict[str, list[GeneratedRecord]] = {}
    for rec in records:
        by_entity.setdefault(rec.synthea_id, []).append(rec)

    def partition(pid: str) -> str:
        return splits[component_of[pid]]["partition"]

    pairs: list[dict] = []
    for pid, recs in by_entity.items():
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                a, b = recs[i], recs[j]
                pairs.append({"pair_id": pair_id_for(str(a.draft.id), str(b.draft.id)), "record_a_id": str(a.draft.id),
                              "record_b_id": str(b.draft.id), "label": LABEL_SAME, "family": "+".join(sorted((a.family, b.family))),
                              "partition": partition(pid)})
    for spec in grafts:
        for a in by_entity[spec.donor_id]:
            for b in by_entity[spec.recipient_id]:
                pairs.append({"pair_id": pair_id_for(str(a.draft.id), str(b.draft.id)), "record_a_id": str(a.draft.id),
                              "record_b_id": str(b.draft.id), "label": LABEL_NOT_SAME, "family": spec.family,
                              "partition": partition(spec.recipient_id)})
    pairs.sort(key=lambda p: p["pair_id"])

    truth_rows = [{
        "entity_id": rec.entity_id, "record_id": str(rec.draft.id), "source_system": rec.draft.source_system,
        "synthea_patient_id": rec.synthea_id, "component_id": component_of[rec.synthea_id],
        "partition": partition(rec.synthea_id), "fold": splits[component_of[rec.synthea_id]]["fold"], "family": rec.family,
    } for rec in records]

    heldout = draw_heldout_families(seed)
    run = {
        "seed": seed, "corpus_fingerprint": fingerprint, "entities": len(ids), "records": len(records), "pairs_same": sum(p["label"] == LABEL_SAME for p in pairs),
        "pairs_not_same": sum(p["label"] == LABEL_NOT_SAME for p in pairs), "grafts": len(grafts),
        "spanish_entities": sum(1 for e in entities.values() if is_spanish(e.bundle.identity)),
        "components": len(splits), "largest_component": max(len(s["members"]) for s in splits.values()),
        "partitions": {name: sum(1 for s in splits.values() if s["partition"] == name) for name in ("showcase", "development", "test")},
        "families_core": list(CORE_TRUE_MATCH + CORE_HARD_NEGATIVE), "heldout_families": heldout,
        "heldout_note": "drawn from the P1 rows by seed; their generators land by 19:00, so they are held out from training by name",
        "family_counts": dict(sorted(Counter(rec.family for rec in records).items())),
    }
    return CorpusOutput(records, pairs, truth_rows, splits, grafts, heldout, run)


def write_outputs(corpus: CorpusOutput, out_dir: Path) -> CorpusOutput:
    """truth.csv, pairs.csv, labels.jsonl, splits.json, run.json; sha256 of each recorded on the corpus."""
    out_dir.mkdir(parents=True, exist_ok=True)
    truth = out_dir / "truth.csv"
    with truth.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(corpus.truth_rows[0].keys()))
        writer.writeheader()
        writer.writerows(corpus.truth_rows)
    pairs = out_dir / "pairs.csv"
    with pairs.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["pair_id", "record_a_id", "record_b_id", "label", "family", "partition"])
        writer.writeheader()
        writer.writerows(corpus.pairs)
    labels = out_dir / "labels.jsonl"
    with labels.open("w", encoding="utf-8") as fh:
        for rec in corpus.records:
            for edit in rec.edits:
                fh.write(json.dumps({"record_id": str(rec.draft.id), "family": edit.family, "field": edit.field,
                                     "before": edit.before, "after": edit.after}, ensure_ascii=False) + "\n")
    splits = out_dir / "splits.json"
    splits.write_text(json.dumps(corpus.splits, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    run = out_dir / "run.json"
    run.write_text(json.dumps(corpus.run, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    corpus.files = {"truth": truth, "pairs": pairs, "labels": labels, "splits": splits, "run": run}
    corpus.sha256 = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in corpus.files.items()}
    return corpus
