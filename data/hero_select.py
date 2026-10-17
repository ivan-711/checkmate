"""Automated hero selection (architecture section 9.1; eval plan section 3).

The hero is a selected showcase satisfying published criteria; aggregate metrics cover the full
frozen test set. Candidates come from the showcase pool only (disjoint from development and
test). Every candidate's ER FHIR and Clinic CSV records are scored with the frozen scorer and
thresholds, and the criteria are:

- the baseline is in REVIEW (never relaxed);
- REMOVE_ADDRESS and CHANGE_BIRTH_YEAR (both +1 and -1) each drop the pair to KEEP_SEPARATE;
- SWAP_DOB_DAY_MONTH and ACCENT_HYPHEN_SURNAME each move p by at most 0.05;
- the intake rendering of the ER fragment lands in REVIEW against the Clinic record;
- the fixture_check bounds: p in [0, 1], no AUTO_LINK anywhere, no what-if raises p above the
  baseline by more than 0.005, no negative rule fires on the baseline.

Among qualifiers the hero is the one closest to the midpoint of the REVIEW band, ties broken by
sha256(entity_id). Relaxation, in the published order, stopping at the first level with a
qualifier: (1) drop the Spanish-name requirement; (2) widen the robustness tolerance from 0.05 to
0.10; (3) accept "drops at least one band" (CHANGE_BIRTH_YEAR needs one of +1/-1 to drop);
(4) no hero qualifies: the best partial candidate and the unmet criteria are reported and the
command exits non-zero. The test-split fallback runs only with ``--allow-test-fallback`` and says
so in ``selection.json``. Never a silent default.

    uv run python -m data.hero_select [--seed 20261017] [--out data/scenarios/hero]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from eval.harness import whatifs
from eval.harness.current_thresholds import CurrentThresholds, from_migrations
from eval.harness.fixture import CLINIC_CSV, ER_FHIR, FixtureConfig
from eval.harness.product import Engine
from eval.harness.run import RunConfig, RunResult, run
from eval.harness.splits import Assignment
from eval.harness.types import (
    BAND_AUTO_LINK,
    BAND_KEEP_SEPARATE,
    BAND_REVIEW,
    PARTITION_SHOWCASE,
    PARTITION_TEST,
    Corpus,
    MatchFn,
    MatchResult,
    Record,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "data" / "scenarios" / "hero"
EXIT_PRODUCT_UNAVAILABLE = 4
ROBUSTNESS_TOLERANCE = 0.05
ROBUSTNESS_TOLERANCE_RELAXED = 0.10
P_RAISE_BOUND = 0.005          # fixture_check: no what-if raises p above the baseline by more than this
INTAKE_SOURCE = "FRONTDESK_INTAKE"
INTAKE_FIELDS = ("given_name", "family_name", "birth_date", "sex", "phone", "address_line", "zip5")
CRITERIA = ("baseline_review", "remove_address_keep_separate", "change_birth_year_keep_separate",
            "swap_dob_day_month_robust", "accent_hyphen_surname_robust", "intake_rendering_review",
            "fixture_check_bounds", "spanish_name")
RELAXATION_LEVELS = (
    "0: all criteria, Spanish-language name required",
    "1: Spanish-name requirement dropped",
    "2: robustness tolerance widened from 0.05 to 0.10",
    "3: band-changers accept a drop at either +1 or -1 birth year",
    "4: no hero qualifies: best partial candidate shown with the unmet criteria",
)


@dataclass
class Level:
    index: int
    require_spanish: bool
    tolerance: float
    birth_year_both: bool


LEVELS = (
    Level(0, True, ROBUSTNESS_TOLERANCE, True),
    Level(1, False, ROBUSTNESS_TOLERANCE, True),
    Level(2, False, ROBUSTNESS_TOLERANCE_RELAXED, True),
    Level(3, False, ROBUSTNESS_TOLERANCE_RELAXED, False),
)


@dataclass
class Scored:
    raw_score: float
    p: float
    band: str
    negative_rules_fired: list[str]
    contributions: dict[str, float]
    features: dict[str, float | None] = field(default_factory=dict)

    @classmethod
    def of(cls, r: MatchResult) -> Scored:
        return cls(round(r.raw_score, 6), round(r.p, 6), r.band, list(r.negative_rules_fired),
                   {k: round(v, 6) for k, v in r.contributions},
                   {k: (None if v is None else round(v, 6)) for k, v in r.features})


@dataclass
class Candidate:
    entity_id: str
    person_id: str
    language: str
    er_record_id: str
    clinic_record_id: str
    baseline: Scored
    what_ifs: dict[str, Scored]
    intake: Scored
    criteria: dict[str, bool] = field(default_factory=dict)
    level: int | None = None
    required: list[str] = field(default_factory=list)
    distance_to_midpoint: float = 0.0
    tie_break: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for k in self.required if self.criteria.get(k))

    def qualifies(self) -> bool:
        return all(self.criteria.get(k) for k in self.required)

    def unmet(self) -> list[str]:
        """Criteria required at ``level`` that the candidate does not meet."""
        return [k for k in self.required if not self.criteria.get(k)]


@dataclass
class HeroSelection:
    ok: bool
    reason: str
    seed: int
    scorer_version: str
    thresholds_id: str
    c_low: float
    c_high: float
    review_midpoint: float
    pool_size: int
    candidate_count: int
    relaxation_level: int | None
    relaxation_levels: list[str]
    qualifier_count_per_level: dict[str, int]
    drawn_from_test: bool
    hero: Candidate | None
    best_partial: Candidate | None
    criteria: dict[str, str]
    candidates: list[Candidate]

    def as_json(self) -> dict:
        d = asdict(self)
        d["wording"] = ("a selected showcase satisfying published criteria; aggregate metrics cover the full frozen "
                        "test set; headline metrics were frozen before selection")
        return d


HERO_BIRTH_YEAR_DELTA = -1  # fork #11, decided option A: the shipped CHANGE_BIRTH_YEAR what-if is fixed at -1


def whatif_year_direction(c: Candidate) -> int:
    """The CHANGE_BIRTH_YEAR direction the UI shows: fixed at -1 (fork #11). Both directions still enter the
    published criterion, and fixture_check --strict fails an AUTO_LINK in either."""
    return HERO_BIRTH_YEAR_DELTA


def intake_rendering(er: Record) -> Record:
    """The fields a patient would type, passed through as propose_new_chart arguments would be."""
    out: Record = {k: er.get(k) for k in INTAKE_FIELDS}
    out.update(record_id=f"{er['record_id']}-intake", person_id=er["person_id"], source_system=INTAKE_SOURCE,
               language=er.get("language"), categories=[], donor_person_ids=[])
    return out


def score_candidate(entity_id: str, er: Record, clinic: Record, match: MatchFn, weights: Mapping[str, float],
                    thresholds: Mapping[str, float], language: str) -> Candidate:
    base = match(er, clinic, weights, thresholds)
    what: dict[str, Scored] = {
        whatifs.REMOVE_ADDRESS: Scored.of(match(whatifs.remove_address(er), clinic, weights, thresholds)),
        f"{whatifs.CHANGE_BIRTH_YEAR}:+1": Scored.of(match(whatifs.change_birth_year(er, 1), clinic, weights, thresholds)),
        f"{whatifs.CHANGE_BIRTH_YEAR}:-1": Scored.of(match(whatifs.change_birth_year(er, -1), clinic, weights, thresholds)),
        whatifs.SWAP_DOB_DAY_MONTH: Scored.of(match(whatifs.swap_dob_day_month(er), clinic, weights, thresholds)),
        whatifs.ACCENT_HYPHEN_SURNAME: Scored.of(match(whatifs.accent_plus_hyphen(er), clinic, weights, thresholds)),
    }
    intake = Scored.of(match(intake_rendering(er), clinic, weights, thresholds))
    return Candidate(entity_id=entity_id, person_id=er["person_id"], language=language, er_record_id=er["record_id"],
                     clinic_record_id=clinic["record_id"], baseline=Scored.of(base), what_ifs=what, intake=intake,
                     tie_break=hashlib.sha256(entity_id.encode()).hexdigest())


def evaluate(c: Candidate, level: Level, midpoint: float) -> Candidate:
    base_p = c.baseline.p
    plus, minus = c.what_ifs[f"{whatifs.CHANGE_BIRTH_YEAR}:+1"], c.what_ifs[f"{whatifs.CHANGE_BIRTH_YEAR}:-1"]
    year_drops = [plus.band == BAND_KEEP_SEPARATE, minus.band == BAND_KEEP_SEPARATE]
    every = [c.baseline, c.intake, *c.what_ifs.values()]
    c.criteria = {
        "baseline_review": c.baseline.band == BAND_REVIEW,
        "remove_address_keep_separate": c.what_ifs[whatifs.REMOVE_ADDRESS].band == BAND_KEEP_SEPARATE,
        "change_birth_year_keep_separate": all(year_drops) if level.birth_year_both else any(year_drops),
        "swap_dob_day_month_robust": abs(c.what_ifs[whatifs.SWAP_DOB_DAY_MONTH].p - base_p) <= level.tolerance,
        "accent_hyphen_surname_robust": abs(c.what_ifs[whatifs.ACCENT_HYPHEN_SURNAME].p - base_p) <= level.tolerance,
        "intake_rendering_review": c.intake.band == BAND_REVIEW,
        "fixture_check_bounds": (all(0.0 <= s.p <= 1.0 for s in every) and all(s.band != BAND_AUTO_LINK for s in every)
                                 and all(s.p <= base_p + P_RAISE_BOUND for s in c.what_ifs.values())
                                 and not c.baseline.negative_rules_fired),
        "spanish_name": c.language == "ES",  # a fact; required only at level 0
    }
    c.level = level.index
    c.required = [k for k in c.criteria if k != "spanish_name" or level.require_spanish]
    c.distance_to_midpoint = round(abs(c.baseline.raw_score - midpoint), 6)
    return c


def _entities_in(corpus: Corpus, assignment: Assignment, partition: str) -> dict[str, dict[str, list[Record]]]:
    """entity id -> source system -> records, for entities whose person sits in the partition."""
    out: dict[str, dict[str, list[Record]]] = {}
    entity_of = corpus.entity_of()
    for rec in corpus.records:
        if assignment.partition_of_person(rec["person_id"]) != partition:
            continue
        out.setdefault(entity_of[rec["record_id"]], {}).setdefault(rec["source_system"], []).append(rec)
    return out


def _rank_key(c: Candidate) -> tuple[float, str]:
    return (c.distance_to_midpoint, c.tie_break)


def select_hero(corpus: Corpus, assignment: Assignment, match: MatchFn, weights: Mapping[str, float],
                c_low: float, c_high: float, seed: int, scorer_version: str, thresholds_id: str,
                allow_test_fallback: bool = False, require_spanish: bool = True) -> HeroSelection:
    midpoint = (c_low + c_high) / 2.0
    thresholds = {"c_low": c_low, "c_high": c_high}
    criteria_text = {
        "baseline_review": "baseline band is REVIEW (never relaxed)",
        "remove_address_keep_separate": "REMOVE_ADDRESS drops to KEEP_SEPARATE (abstention: not enough to link)",
        "change_birth_year_keep_separate": "CHANGE_BIRTH_YEAR +1 and -1 each drop to KEEP_SEPARATE (level 3: either)",
        "swap_dob_day_month_robust": "SWAP_DOB_DAY_MONTH moves p by at most the tolerance (0.05; level 2: 0.10)",
        "accent_hyphen_surname_robust": "ACCENT_HYPHEN_SURNAME moves p by at most the tolerance (0.05; level 2: 0.10)",
        "intake_rendering_review": "the intake rendering of the ER fragment lands in REVIEW against the Clinic record",
        "fixture_check_bounds": "p in [0,1]; no AUTO_LINK; no what-if raises p above baseline + 0.005; no negative rule",
        "spanish_name": "Spanish-language name (reported as a fact; required at level 0 only)",
    }
    levels = list(LEVELS) if require_spanish else [lv for lv in LEVELS if not lv.require_spanish]

    def attempt(partition: str) -> tuple[list[Candidate], Candidate | None, int | None, dict[str, int], int]:
        by_entity = _entities_in(corpus, assignment, partition)
        candidates: list[Candidate] = []
        for entity_id in sorted(by_entity):
            systems = by_entity[entity_id]
            if len(systems.get(ER_FHIR, [])) != 1 or len(systems.get(CLINIC_CSV, [])) != 1:
                continue  # prefer one ER FHIR and one Clinic CSV record: the pair the demo shows
            er, clinic = systems[ER_FHIR][0], systems[CLINIC_CSV][0]
            candidates.append(score_candidate(entity_id, er, clinic, match, weights, thresholds,
                                              corpus.person_language.get(er["person_id"], "EN")))
        counts: dict[str, int] = {}
        for level in levels:
            qualifiers = [evaluate(c, level, midpoint) for c in candidates]
            qualifiers = [c for c in qualifiers if c.qualifies()]
            counts[str(level.index)] = len(qualifiers)
            if qualifiers:
                return candidates, min(qualifiers, key=_rank_key), level.index, counts, len(by_entity)
        for c in candidates:  # leave every candidate evaluated at the most relaxed level for the report
            evaluate(c, levels[-1], midpoint)
        return candidates, None, None, counts, len(by_entity)

    candidates, hero, level, counts, pool_size = attempt(PARTITION_SHOWCASE)
    drawn_from_test = False
    if hero is None and allow_test_fallback:
        candidates, hero, level, counts, _ = attempt(PARTITION_TEST)
        drawn_from_test = hero is not None
    # best partial: a REVIEW baseline first (the demo path needs it), then most criteria met, then the midpoint
    best_partial = max(candidates, key=lambda c: (c.criteria.get("baseline_review", False), c.passed,
                                                 -c.distance_to_midpoint, c.tie_break)) if candidates else None
    if hero is None:
        reason = (f"no hero qualifies at any relaxation level in the showcase pool ({pool_size} entities, "
                  f"{len(candidates)} with one ER FHIR and one Clinic CSV record)"
                  + ("; test-split fallback also found none" if allow_test_fallback else
                     "; test-split fallback not enabled (--allow-test-fallback)"))
        if best_partial is not None:
            reason += f"; best partial {best_partial.entity_id} misses {best_partial.unmet()}"
    else:
        reason = (f"hero {hero.entity_id} qualifies at relaxation level {level}; "
                  f"{counts[str(level)]} qualifier(s) at that level; closest to the REVIEW midpoint {midpoint:.4f}"
                  + ("; DRAWN FROM THE TEST SPLIT: headline metrics were frozen before selection and the hero is "
                     "excluded from per-button recall" if drawn_from_test else ""))
    return HeroSelection(ok=hero is not None, reason=reason, seed=seed, scorer_version=scorer_version,
                         thresholds_id=thresholds_id, c_low=c_low, c_high=c_high, review_midpoint=round(midpoint, 6),
                         pool_size=pool_size, candidate_count=len(candidates), relaxation_level=level,
                         relaxation_levels=list(RELAXATION_LEVELS), qualifier_count_per_level=counts,
                         drawn_from_test=drawn_from_test, hero=hero, best_partial=best_partial,
                         criteria=criteria_text, candidates=sorted(candidates, key=_rank_key))


def development_run(seed: int, engine: Engine, corpus_loader=None, fixture: FixtureConfig | None = None,
                    operating_point: CurrentThresholds | None = None) -> RunResult:
    """The development run with the same seed (fast config) through ``engine``, banded at the current row."""
    cfg = RunConfig(name="hero-select", seed=seed, fast=True, out_dir=Path(tempfile.mkdtemp(prefix="hero-select-")),
                    fixture=fixture or FixtureConfig(seed=seed), corpus_loader=corpus_loader, match=engine.match,
                    fit=engine.fit, block=engine.block, scorer_version=engine.scorer_version,
                    provenance={"engine": engine.provenance}, operating_point=operating_point or from_migrations())
    return run(cfg)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=20261017)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-test-fallback", action="store_true")
    parser.add_argument("--no-require-spanish", action="store_true",
                        help="skip level 0 when the 12:30 census failed the Spanish gate")
    parser.add_argument("--engine", choices=("product", "standin"), default="product",
                        help="product (default): W1's corpus and W2's engine; standin: harness self-test only")
    parser.add_argument("--raw", type=Path, default=None, help="extracted Synthea sample (data/download.py)")
    parser.add_argument("--allow-partial", action="store_true",
                        help="when no hero qualifies, export the best partial candidate with its unmet criteria "
                             "(architecture 9.1: the pitch narrates the band changes that actually occur); exit 0")
    args = parser.parse_args(argv)
    from data.hero_export import export  # local import: the exporter pulls in the contract models
    from eval.harness import product

    op = from_migrations()
    try:
        if args.engine == "product":
            engine = product.load_engine()
            raw = args.raw or product.DEFAULT_RAW_DIR
            result = development_run(args.seed, engine, corpus_loader=lambda: product.load_corpus(args.seed, raw)[0],
                                     operating_point=op)
        else:
            engine = product.standin_engine()
            result = development_run(args.seed, engine, operating_point=op)
    except product.ProductUnavailable as exc:
        print(f"PRODUCT UNAVAILABLE: {exc}", file=sys.stderr)
        return EXIT_PRODUCT_UNAVAILABLE
    # the hero is scored with the weights the app ships, banded at the app's current threshold row
    selection = select_hero(result.corpus, result.assignment, engine.match, engine.shipped_weights,
                            op.c_low, op.c_high, args.seed, engine.scorer_version, op.thresholds_id,
                            allow_test_fallback=args.allow_test_fallback, require_spanish=not args.no_require_spanish)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "selection.json").write_text(json.dumps(selection.as_json(), indent=2, ensure_ascii=False) + "\n")
    print(selection.reason)
    if selection.ok:
        export(selection, result, args.out, provisional=True, engine=engine)
        print(f"hero {selection.hero.entity_id} exported to {args.out}")
        return 0
    partial = selection.best_partial
    if args.allow_partial and partial is not None and partial.criteria.get("baseline_review"):
        export(selection, result, args.out, provisional=True, hero=partial, engine=engine)
        print(f"NO QUALIFIER: best partial {partial.entity_id} exported with unmet criteria {partial.unmet()}; "
              "the pitch narrates only the band changes that occur", file=sys.stderr)
        return 0
    print("HERO SELECTION FAILED: see selection.json for the best partial candidate", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
