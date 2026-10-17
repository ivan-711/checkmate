"""In-repo synthetic fixture: a small seeded corpus with a hidden truth table.

Stands in for W1's loader and corruptor until they merge. Follows the generator shape of
eval plan section 3: a per-entity RNG stream derived from ``sha256(f"{root_seed}:{entity}")``,
one to three records per entity over the ER FHIR and Clinic CSV systems, the P0 core families
(T1, T3, D1, D3, L1, L3, L7, S1, S3, S5, S6, C1) as true-match mutations, and the P0 hard
negatives (N1 siblings, N3 parent/child) as demographic grafts that add dependency edges.
Nothing here is real; every name comes from the small tables below.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass

from eval.harness.standin import fold
from eval.harness.types import Corpus, Record, TruthRow

ER_FHIR = "ER_FHIR"
CLINIC_CSV = "CLINIC_CSV"
SYSTEMS = (ER_FHIR, CLINIC_CSV)

P0_TRUE_MATCH_FAMILIES = ("T1", "T3", "D1", "D3", "L1", "L3", "L7", "S1", "S3", "S5", "S6", "C1")
P0_HARD_NEGATIVE_FAMILIES = ("N1", "N3")
P0_FAMILIES = P0_TRUE_MATCH_FAMILIES + P0_HARD_NEGATIVE_FAMILIES
SPANISH_FAMILIES = ("S1", "S3", "S5", "S6")

EN_GIVEN = ("Robert", "William", "Elizabeth", "Margaret", "James", "Katherine", "Michael", "Patricia",
            "Thomas", "Jennifer", "Richard", "Dorothy", "Charles", "Susan", "Joseph", "Barbara")
EN_FAMILY = ("Anderson", "Thompson", "Mitchell", "Patterson", "Henderson", "Sullivan", "Richardson",
             "Campbell", "Fletcher", "Harrington", "Whitaker", "Bennett")
ES_GIVEN = ("José", "María", "Jesús", "Andrés", "Raúl", "Sofía", "Nicolás", "Inés", "Ramón", "Lucía",
            "Tomás", "Ángela", "María Guadalupe", "María José", "Juan Carlos", "Ana Lucía")
ES_PATERNAL = ("García", "Hernández", "López", "Martínez", "Rodríguez", "Pérez", "Sánchez", "Ramírez",
               "Muñoz", "Núñez", "Jiménez", "Ibáñez")
ES_MATERNAL = ("Castillo", "de la Cruz", "Vargas", "Ortega", "Delgado", "de Anda", "Romero", "Flores")
NICKNAMES = {"Robert": "Bob", "William": "Bill", "Elizabeth": "Liz", "Margaret": "Peggy", "James": "Jim",
             "Katherine": "Kate", "Michael": "Mike", "Patricia": "Pat", "Thomas": "Tom", "Jennifer": "Jen",
             "Richard": "Dick", "Dorothy": "Dot", "Charles": "Chuck", "Susan": "Sue", "Joseph": "Joe",
             "Barbara": "Barb"}
STREETS = ("Oak", "Maple", "Cedar", "Birch", "Elm", "Walnut", "Spruce", "Willow", "Aspen", "Pine")
ZIPS = ("54301", "54302", "54303", "54304", "54311", "54313", "54115", "54155", "54162", "54173")
PLACEHOLDER_DOB = "1900-01-01"


@dataclass(frozen=True)
class FixtureConfig:
    seed: int = 20261017
    entities: int = 180
    spanish_share: float = 0.35
    fragment_probs: tuple[float, float, float] = (0.15, 0.65, 0.20)  # 1, 2, 3 records
    hard_negative_pairs: int = 24
    families: tuple[str, ...] = P0_FAMILIES


def _rng_for(root_seed: int, key: str) -> random.Random:
    digest = hashlib.sha256(f"{root_seed}:{key}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _fold(text: str) -> str:
    return fold(text)


def _base_person(pid: int, rng: random.Random, spanish: bool) -> Record:
    if spanish:
        given = rng.choice(ES_GIVEN)
        family = f"{rng.choice(ES_PATERNAL)} {rng.choice(ES_MATERNAL)}"
    else:
        given = rng.choice(EN_GIVEN)
        family = rng.choice(EN_FAMILY)
    year = rng.randint(1940, 2005)
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    return {
        "person_id": f"P{pid:04d}",
        "given_name": given,
        "family_name": family,
        "birth_date": f"{year:04d}-{month:02d}-{day:02d}",
        "sex": rng.choice(("FEMALE", "MALE")),
        "phone": f"+1920555{rng.randint(0, 9999):04d}",
        "address_line": f"{rng.randint(100, 9999)} {rng.choice(STREETS)} St",
        "zip5": rng.choice(ZIPS),
        "language": "ES" if spanish else "EN",
    }


# --- true-match mutations (eval plan section 2; applied in place, return the label or None if no-op) ---

def _t1_one_char(rec: Record, rng: random.Random) -> str | None:
    name = rec["family_name"]
    if len(name) < 3:
        return None
    i = rng.randrange(1, len(name) - 1)
    rec["family_name"] = name[:i] + rng.choice("aeiosnt") + name[i + 1:]
    return "T1" if rec["family_name"] != name else None


def _t3_nickname(rec: Record, rng: random.Random) -> str | None:
    nick = NICKNAMES.get(rec["given_name"])
    if nick is None:
        return None
    rec["given_name"] = nick
    return "T3"


def _d1_swap_day_month(rec: Record, rng: random.Random) -> str | None:
    y, m, d = rec["birth_date"].split("-")
    if int(d) > 12 or d == m:
        return None
    rec["birth_date"] = f"{y}-{d}-{m}"
    return "D1"


def _d3_year_off_by_one(rec: Record, rng: random.Random) -> str | None:
    y, m, d = rec["birth_date"].split("-")
    rec["birth_date"] = f"{int(y) + rng.choice((-1, 1)):04d}-{m}-{d}"
    return "D3"


def _l1_old_address(rec: Record, rng: random.Random) -> str | None:
    rec["address_line"] = f"{rng.randint(100, 9999)} {rng.choice(STREETS)} Ave"
    if rng.random() < 0.5:
        rec["zip5"] = rng.choice(ZIPS)
    return "L1"


def _l3_phone_missing(rec: Record, rng: random.Random) -> str | None:
    if rec["phone"] is None:
        return None
    rec["phone"] = None
    return "L3"


def _l7_address_missing(rec: Record, rng: random.Random) -> str | None:
    if rec["address_line"] is None:
        return None
    rec["address_line"] = None
    rec["zip5"] = None
    return "L7"


def _s1_accent_dropped(rec: Record, rng: random.Random) -> str | None:
    before = (rec["given_name"], rec["family_name"])
    rec["given_name"] = _fold(rec["given_name"]).title()
    rec["family_name"] = " ".join(_fold(t).title() if t[0].isupper() else _fold(t) for t in rec["family_name"].split())
    return "S1" if (rec["given_name"], rec["family_name"]) != before else None


def _s3_maternal_dropped(rec: Record, rng: random.Random) -> str | None:
    tokens = rec["family_name"].split()
    if rec["language"] != "ES" or len(tokens) < 2:
        return None
    rec["family_name"] = tokens[0]
    return "S3"


def _s5_hyphen_particle(rec: Record, rng: random.Random) -> str | None:
    name = rec["family_name"]
    if rec["language"] != "ES":
        return None
    if " de la " in f" {name} " or " de " in f" {name} ":
        rec["family_name"] = name.replace("de la ", "Dela").replace("de ", "De")
    elif " " in name:
        rec["family_name"] = name.replace(" ", "-", 1)
    else:
        return None
    return "S5"


def _s6_ma_abbreviation(rec: Record, rng: random.Random) -> str | None:
    if not rec["given_name"].startswith("María "):
        return None
    rec["given_name"] = "Ma. " + rec["given_name"][len("María "):]
    return "S6"


SINGLE_EDITS = {"T1": _t1_one_char, "T3": _t3_nickname, "D1": _d1_swap_day_month, "D3": _d3_year_off_by_one,
                "L1": _l1_old_address, "L3": _l3_phone_missing, "L7": _l7_address_missing, "S1": _s1_accent_dropped,
                "S3": _s3_maternal_dropped, "S5": _s5_hyphen_particle, "S6": _s6_ma_abbreviation}


def _c1_two_edits(rec: Record, rng: random.Random) -> str | None:
    applied = [f for f in ("T1", "D1", "L1", "D3", "T3") if SINGLE_EDITS[f](rec, rng)]
    return "C1" if len(applied) >= 2 else None


def _apply_family(rec: Record, family: str, rng: random.Random) -> str | None:
    if family == "C1":
        return _c1_two_edits(rec, rng)
    return SINGLE_EDITS[family](rec, rng)


def _emit(records: list[Record], truth: list[TruthRow], base: Record, entity_id: str, system: str,
          categories: list[str], donors: list[str], seq: int) -> Record:
    rec = dict(base)
    rec["record_id"] = f"{entity_id}-{system}-{seq}"
    rec["source_system"] = system
    rec["categories"] = list(categories)
    rec["donor_person_ids"] = list(donors)
    rec["entity_id"] = entity_id
    records.append(rec)
    truth.append(TruthRow(entity_id=entity_id, record_id=rec["record_id"], source_system=system,
                          synthea_patient_id=base["person_id"]))
    return rec


def build_fixture(cfg: FixtureConfig | None = None) -> Corpus:
    """Deterministic for a config: the same seed gives byte-identical records and truth."""
    cfg = cfg or FixtureConfig()
    records: list[Record] = []
    truth: list[TruthRow] = []
    edges: list[tuple[str, str]] = []
    person_language: dict[str, str] = {}
    tm_families = [f for f in cfg.families if f in P0_TRUE_MATCH_FAMILIES]
    hn_families = [f for f in cfg.families if f in P0_HARD_NEGATIVE_FAMILIES]
    persons: list[Record] = []
    for i in range(cfg.entities):
        rng = _rng_for(cfg.seed, f"entity:{i}")
        spanish = rng.random() < cfg.spanish_share
        base = _base_person(i, rng, spanish)
        persons.append(base)
        person_language[base["person_id"]] = base["language"]
        entity_id = f"E{i:04d}"
        n_rec = rng.choices((1, 2, 3), weights=cfg.fragment_probs)[0]
        systems = [ER_FHIR, CLINIC_CSV][:n_rec] if n_rec <= 2 else [ER_FHIR, CLINIC_CSV, rng.choice(SYSTEMS)]
        for seq, system in enumerate(systems):
            rec = dict(base)
            categories: list[str] = []
            if seq > 0:  # the first fragment is the clean rendering; later fragments carry edits
                n_edits = rng.choices((0, 1, 2, 3), weights=(0.20, 0.45, 0.25, 0.10))[0]
                for family in rng.sample(tm_families, k=min(n_edits, len(tm_families))):
                    label = _apply_family(rec, family, rng)
                    if label:
                        categories.append(label)
            _emit(records, truth, rec, entity_id, system, categories, [], seq)
    # hard negatives: a new person P2 takes demographics from P1 and keeps its own identity (its own entity);
    # the graft adds the dependency edge P1-P2 so both land in one component
    for j in range(cfg.hard_negative_pairs if hn_families else 0):
        rng = _rng_for(cfg.seed, f"hard_negative:{j}")
        family = hn_families[j % len(hn_families)]
        p1 = rng.choice(persons)
        p2 = _base_person(cfg.entities + j, rng, p1["language"] == "ES")
        person_language[p2["person_id"]] = p2["language"]
        graft = dict(p2)
        if family == "N1":  # siblings: same surname, address, phone; birth year within 3; different given name
            graft["family_name"] = p1["family_name"]
            graft["address_line"], graft["zip5"], graft["phone"] = p1["address_line"], p1["zip5"], p1["phone"]
            y, m, d = p1["birth_date"].split("-")
            graft["birth_date"] = f"{int(y) + rng.choice((-3, -2, -1, 1, 2, 3)):04d}-{m}-{d}"
        else:  # N3 parent and child: same full name, same address, DOB at least 18 years apart
            graft["given_name"], graft["family_name"] = p1["given_name"], p1["family_name"]
            graft["address_line"], graft["zip5"] = p1["address_line"], p1["zip5"]
            y, m, d = p1["birth_date"].split("-")
            graft["birth_date"] = f"{int(y) + rng.choice((-30, -25, 25, 30)):04d}-{m}-{d}"
            graft["sex"] = p1["sex"]
        # the graft side gets the same corruption draw the true-match fragments get; P1's own fragments
        # already carry theirs, so "looks mangled" does not separate matches from negatives (section 2)
        fam = rng.choice(tm_families) if tm_families and rng.random() < 0.5 else None
        if fam:
            _apply_family(graft, fam, rng)
        entity_id = f"E{cfg.entities + j:04d}"
        system = rng.choice(SYSTEMS)
        _emit(records, truth, graft, entity_id, system, [family], [p1["person_id"]], 0)
        edges.append((p1["person_id"], p2["person_id"]))
    return Corpus(records=records, truth=truth, dependency_edges=edges, person_language=person_language)


def corpus_hashes(corpus: Corpus) -> dict[str, str]:
    """sha256 of the canonical records and truth, for the manifest and the idempotent-ingest check."""
    rec_bytes = json.dumps(sorted(corpus.records, key=lambda r: r["record_id"]), sort_keys=True).encode()
    truth_bytes = "\n".join(f"{t.entity_id},{t.record_id},{t.source_system},{t.synthea_patient_id}"
                            for t in sorted(corpus.truth, key=lambda t: t.record_id)).encode()
    return {"records": hashlib.sha256(rec_bytes).hexdigest(), "truth": hashlib.sha256(truth_bytes).hexdigest()}
