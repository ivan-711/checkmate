"""R5 round 2 (lane/w5 at c4bc3ad): the production path (W1's corpus, W2's engine) and the real hero."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from data import hero_select as hs
from data.hero_export import iso_date
from eval.harness import product, standin, whatifs
from eval.harness.run import EXPECTATIONS_DIR
from eval.harness.types import BAND_KEEP_SEPARATE, MatchResult, Record, band_for

ROOT = Path(__file__).resolve().parents[2]
HERO_DIR = ROOT / "data" / "scenarios" / "hero"
C_LOW, C_HIGH, MID = 0.0, 4.0, 2.0


# --- the committed hero: a no-op what-if must not be narrated as a demonstrated robustness -------------

def test_committed_swap_what_if_is_not_a_noop_narrated_as_robustness():
    """Architecture 9.1 / eval plan 7: narrate only what occurs. The hero's ER DOB has day > 12, so the
    swap cannot happen; the export still captions it 'the engine has a named feature for this; the score
    barely moves' with a counterfactual equal to the original DOB."""
    scenario = json.loads((HERO_DIR / "scenario.json").read_text())
    hero = json.loads((HERO_DIR / "hero.json").read_text())
    er_dob = iso_date(hero["records"]["ER_FHIR"]["birth_date"])
    swap = scenario["whatIfs"]["SWAP_DOB_DAY_MONTH"]
    noop = swap["counterfactualFields"].get("birthDate") == er_dob
    assert not (noop and "named feature" in swap["caption"]), (er_dob, swap["caption"])
    if noop:
        assert scenario["hero"]["criteria"]["swap_dob_day_month_robust"] is not True, \
            "a swap that cannot be applied is reported as a met robustness criterion"


# --- the selector: a no-op what-if is not evidence -------------------------------------------------------

class _Corpus:
    def __init__(self, records, languages):
        self.records, self.person_language, self.truth = records, languages, []

    def record_by_id(self):
        return {r["record_id"]: r for r in self.records}

    def entity_of(self):
        return {r["record_id"]: r["entity_id"] for r in self.records}


class _Assignment:
    def __init__(self, partition):
        self._p = partition

    def partition_of_person(self, pid):
        return self._p.get(pid, "development")


def _rec(rid, system, dob) -> Record:
    return {"record_id": rid, "person_id": "E1", "entity_id": "E1", "source_system": system, "given_name": "Ana",
            "family_name": "García López", "birth_date": dob, "sex": "FEMALE", "phone": "+19205550100",
            "address_line": "100 Oak St", "zip5": "54311", "language": "ES", "categories": [], "donor_person_ids": []}


def _select(match, dob="1985-07-03"):
    corpus = _Corpus([_rec("er", "ER_FHIR", dob), _rec("cl", "CLINIC_CSV", dob)], {"E1": "ES"})
    return hs.select_hero(corpus, _Assignment({"E1": "showcase"}), match, {}, C_LOW, C_HIGH, 1, "t", "t")


def _result(s, thresholds):
    return MatchResult(raw_score=s, p=standin.display_p(s, {}), band=band_for(s, thresholds["c_low"], thresholds["c_high"]))


def test_selector_does_not_count_an_inapplicable_swap_as_robust():
    def match(a, b, weights, thresholds):
        s = MID - (3.0 if a.get("address_line") is None or a["birth_date"][:4] != "1985" else 0.0)
        return _result(s, thresholds)

    sel = _select(match, dob="1985-07-16")  # day 16: SWAP_DOB_DAY_MONTH cannot apply
    cand = sel.hero or sel.best_partial
    assert not whatifs.is_applicable(whatifs.SWAP_DOB_DAY_MONTH, _rec("er", "ER_FHIR", "1985-07-16"))
    assert cand.criteria["swap_dob_day_month_robust"] is not True, "an unchanged score from an unapplied edit passed"


def test_level_three_cannot_qualify_on_the_direction_the_ui_never_shows():
    """Fork #11 A fixes the shipped CHANGE_BIRTH_YEAR at -1. Level 3 still accepts 'either +1 or -1 drops',
    so a hero that drops only at +1 qualifies while the shipped -1 what-if stays in REVIEW."""
    def match(a, b, weights, thresholds):
        s = MID - (3.0 if a.get("address_line") is None or a["birth_date"][:4] == "1986" else 0.0)
        return _result(s, thresholds)

    sel = _select(match)
    if sel.ok:
        shipped = sel.hero.what_ifs[f"{whatifs.CHANGE_BIRTH_YEAR}:{hs.HERO_BIRTH_YEAR_DELTA:+d}"]
        assert shipped.band == BAND_KEEP_SEPARATE, (
            f"qualified at level {sel.relaxation_level} via +1 only; the shipped -1 what-if is {shipped.band}")


# --- the production corpus adapter ------------------------------------------------------------------------

def test_hard_negative_family_reaches_the_harness_categories(tmp_path, monkeypatch):
    """W1 labels a graft with GraftSpec.family (N1/N3). product.load_corpus reads categories from the
    record's own family only, so every hard_negative.N1/N3 cell is computed over zero pairs in production."""
    (tmp_path / "fhir").mkdir()
    (tmp_path / "csv").mkdir()
    (tmp_path / "csv" / "patients.csv").write_text("Id\n")

    def rec(rid, synthea, entity):
        ident = SimpleNamespace(given="Ana", family="Lopez", birth_date="1985-07-03", sex="FEMALE", phone=None,
                                address_line="1 Oak St", postal_code="54311")
        draft = SimpleNamespace(id=rid, identity=ident, source_system="ER_FHIR")
        return SimpleNamespace(draft=draft, entity_id=entity, synthea_id=synthea, family="NONE", share=None)

    out = SimpleNamespace(
        records=[rec("r1", "P1", "E1"), rec("r2", "P2", "E2")],
        grafts=[SimpleNamespace(family="N1", donor_id="P1", recipient_id="P2")],
        splits={"P1": {"partition": "development", "fold": 0, "members": ["P1", "P2"]}},
        run={}, heldout_families=[])
    fakes = {"backend.ingest.cli": SimpleNamespace(load_sample=lambda raw: ([], [])),
             "backend.ingest.corruptor": SimpleNamespace(build_corpus=lambda seed, b, c: out,
                                                         is_spanish=lambda ident: False)}
    monkeypatch.setattr(product.importlib, "import_module", lambda name: fakes[name])
    corpus, _ = product.load_corpus(1, tmp_path)
    recipient = next(r for r in corpus.records if r["person_id"] == "P2")
    assert "N1" in recipient["categories"], recipient["categories"]


def test_w1_seeded_held_out_draw_and_the_evaluation_config_agree():
    """Eval plan 3: the evaluation config's seeded draw decides the held-out families. W1 draws its own by
    seed; the harness reads only config.json. Two sources of truth with no equality check: when the P1
    generators land, the per-merge run scores W1's held-out families unless the fork copies the list."""
    from backend.ingest.corruptor import draw_heldout_families

    cfg = json.loads((EXPECTATIONS_DIR / "config.json").read_text())["heldOutFamilies"]
    assert sorted(draw_heldout_families(cfg["seed"])) == sorted(cfg["drawn"])
