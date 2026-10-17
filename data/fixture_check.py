"""``fixture_check``: the section 9.1 checks on the selected hero (architecture 9.1; the 20:00 gate).

Reads ``data/scenarios/hero/{scenario,hero,selection}.json``, validates the export against the
contract models, re-scores the hero with the scorer the export names, and checks:

- p in [0, 1]; no AUTO_LINK anywhere; every what-if p <= baseline p + 0.005; no negative rule fires;
- the selection criteria (baseline REVIEW, the two band-changers, the two robustness buttons, the
  intake rendering in REVIEW);
- bands compared through the raw cutoffs, never through re-derived p cutoffs;
- the never-say words are absent;
- (v0.4) the scripted ``propose_new_chart`` through ``policy.decide`` gives DENY
  CANDIDATE_IN_REVIEW_OR_HIGHER with the Clinic record in ``evidence_ids``; after a scripted approve,
  ``attach_history`` is allowed and BL-AMOX-01 fires; ``frontdesk_transcript.json`` replays with zero
  REPLAY_DIVERGED. These three SKIP with a reason until lanes Q1.1, W3b and Q1 land.

Exit 0 when every check passes or skips. Criteria the provisional best-partial hero does not meet
are WARN (the pitch narrates only the band changes that occur); ``--strict`` turns every WARN and
SKIP into a failure, which is how the 20:00 gate runs it.

    uv run python -m data.fixture_check [--dir data/scenarios/hero] [--strict]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from contracts.models.entities import Entity, TimelineEvent
from contracts.models.pairs import CandidatePairDetail
from contracts.models.sessions import SessionResponse
from contracts.models.thresholds import ThresholdSet
from contracts.models.tiles import TilesResponse
from contracts.models.whatifs import WhatIfResponse
from data.hero_select import P_RAISE_BOUND, ROBUSTNESS_TOLERANCE, intake_rendering
from eval.harness import standin, whatifs
from eval.harness.types import BAND_AUTO_LINK, BAND_KEEP_SEPARATE, BAND_REVIEW, band_for

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "data" / "scenarios" / "hero"
NEVER_SAY = ("prevented", "would have died", "the ai caught", "contraindicated for this patient", "fatal",
             "they look like two people", "typical patient")
PASS, WARN, SKIP, FAIL = "PASS", "WARN", "SKIP", "FAIL"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""

    def line(self) -> str:
        return f"[{self.status}] {self.name}" + (f": {self.detail}" if self.detail else "")


def _load(d: Path, name: str) -> dict:
    return json.loads((d / name).read_text())


def run_checks(d: Path, strict: bool = False) -> list[Check]:
    checks: list[Check] = []
    missing = [n for n in ("scenario.json", "hero.json", "selection.json") if not (d / n).exists()]
    if missing:
        return [Check("hero export present", FAIL, f"missing {missing} in {d}; run `python -m data.hero_select`")]
    scenario, hero, selection = _load(d, "scenario.json"), _load(d, "hero.json"), _load(d, "selection.json")

    # contract shape
    try:
        SessionResponse.model_validate(scenario["session"])
        CandidatePairDetail.model_validate(scenario["pair"])
        Entity.model_validate(scenario["entityIfApproved"])
        for ev in scenario["timelineIfApproved"]:
            TimelineEvent.model_validate(ev)
        from contracts.models.alerts import SafetyAlert

        alert = SafetyAlert.model_validate(scenario["alertIfApproved"])
        ThresholdSet.model_validate(scenario["thresholds"])
        TilesResponse.model_validate(scenario["tiles"])
        for wi in scenario["whatIfs"].values():
            WhatIfResponse.model_validate(wi)
        checks.append(Check("scenario.json validates against the contract models", PASS))
        checks.append(Check("alert is constructed-scenario tier A", PASS if alert.constructed_scenario and alert.tier == "A"
                            else FAIL))
    except (ValueError, KeyError, TypeError) as exc:  # pydantic ValidationError is a ValueError
        checks.append(Check("scenario.json validates against the contract models", FAIL, str(exc)[:300]))
        return checks
    checks.append(Check("what-if set is the four buttons", PASS if set(scenario["whatIfs"]) == set(whatifs.BUTTONS) else FAIL))

    text = json.dumps(scenario, ensure_ascii=False).lower()
    bad = [w for w in NEVER_SAY if w in text]
    checks.append(Check("never-say words absent", FAIL if bad else PASS, ", ".join(bad)))

    # re-score with the named scorer through the raw cutoffs
    er, clinic = hero["records"]["ER_FHIR"], hero["records"]["CLINIC_CSV"]
    c_low, c_high = float(hero["cLow"]), float(hero["cHigh"])
    thresholds = {"c_low": c_low, "c_high": c_high}
    weights = hero.get("weights") or standin.DEFAULT_WEIGHTS
    if hero["scorerVersion"] != standin.SCORER_VERSION:
        checks.append(Check("re-score with the named scorer", SKIP,
                            f"export names scorer {hero['scorerVersion']}; wire W2's match() here"))
        base, what, intake = hero["baseline"], hero["whatIfs"], hero["intake"]
    else:
        match = standin.match
        base = _as_dict(match(er, clinic, weights, thresholds))
        what = {
            whatifs.REMOVE_ADDRESS: _as_dict(match(whatifs.remove_address(er), clinic, weights, thresholds)),
            f"{whatifs.CHANGE_BIRTH_YEAR}:+1": _as_dict(match(whatifs.change_birth_year(er, 1), clinic, weights, thresholds)),
            f"{whatifs.CHANGE_BIRTH_YEAR}:-1": _as_dict(match(whatifs.change_birth_year(er, -1), clinic, weights, thresholds)),
            whatifs.SWAP_DOB_DAY_MONTH: _as_dict(match(whatifs.swap_dob_day_month(er), clinic, weights, thresholds)),
            whatifs.ACCENT_HYPHEN_SURNAME: _as_dict(match(whatifs.accent_plus_hyphen(er), clinic, weights, thresholds)),
        }
        intake = _as_dict(match(intake_rendering(er), clinic, weights, thresholds))
        drift = abs(base["raw_score"] - hero["baseline"]["raw_score"]) > 1e-6
        checks.append(Check("re-scored baseline equals the export", FAIL if drift else PASS,
                            f"{base['raw_score']:.6f} vs {hero['baseline']['raw_score']:.6f}"))
        exported_band = scenario["pair"]["pair"]["decision"]["band"]
        checks.append(Check("scenario pair band equals the re-scored band through the raw cutoffs",
                            PASS if exported_band == base["band"] else FAIL, f"{exported_band} vs {base['band']}"))

    # the exported CHANGE_BIRTH_YEAR direction is the one the UI shows; the other enters only the criterion
    exported_year = scenario["whatIfs"][whatifs.CHANGE_BIRTH_YEAR]["whatIf"]["rawScore"]
    shown = {k: s for k, s in what.items() if not k.startswith(whatifs.CHANGE_BIRTH_YEAR)
             or abs(s["raw_score"] - exported_year) < 1e-6}
    every = [base, intake, *shown.values()]
    checks.append(Check("p in [0, 1] everywhere", PASS if all(0.0 <= s["p"] <= 1.0 for s in every) else FAIL))
    checks.append(Check("no AUTO_LINK anywhere", PASS if all(s["band"] != BAND_AUTO_LINK for s in every) else FAIL,
                        ", ".join(k for k, s in shown.items() if s["band"] == BAND_AUTO_LINK)))
    raised = [k for k, s in shown.items() if s["p"] > base["p"] + P_RAISE_BOUND]
    checks.append(Check(f"no what-if raises p above baseline + {P_RAISE_BOUND}", _soft(bool(raised), strict), ", ".join(raised)))
    checks.append(Check("no negative rule fires on the baseline", PASS if not base["negative_rules_fired"] else FAIL,
                        ", ".join(base["negative_rules_fired"])))
    checks.append(Check("bands come from the raw cutoffs", PASS if all(
        s["band"] == band_for(s["raw_score"], c_low, c_high, s["negative_rules_fired"]) for s in every) else FAIL))

    # the selection criteria
    criteria = {
        "baseline in REVIEW": base["band"] == BAND_REVIEW,
        "REMOVE_ADDRESS drops to KEEP_SEPARATE": what[whatifs.REMOVE_ADDRESS]["band"] == BAND_KEEP_SEPARATE,
        "CHANGE_BIRTH_YEAR +1 and -1 drop to KEEP_SEPARATE": all(
            what[f"{whatifs.CHANGE_BIRTH_YEAR}:{d}"]["band"] == BAND_KEEP_SEPARATE for d in ("+1", "-1")),
        f"SWAP_DOB_DAY_MONTH moves p by <= {ROBUSTNESS_TOLERANCE}":
            abs(what[whatifs.SWAP_DOB_DAY_MONTH]["p"] - base["p"]) <= ROBUSTNESS_TOLERANCE,
        f"ACCENT_HYPHEN_SURNAME moves p by <= {ROBUSTNESS_TOLERANCE}":
            abs(what[whatifs.ACCENT_HYPHEN_SURNAME]["p"] - base["p"]) <= ROBUSTNESS_TOLERANCE,
        "intake rendering lands in REVIEW against the Clinic record": intake["band"] == BAND_REVIEW,
    }
    for name, ok in criteria.items():
        hard = name == "baseline in REVIEW"  # the demo path needs REVIEW even for a partial hero
        checks.append(Check(f"criterion: {name}", PASS if ok else (FAIL if hard or strict else WARN)))
    checks.append(Check("hero export labeled provisional/qualified consistently",
                        PASS if (scenario["hero"]["provisional"] == hero["provisional"]
                                 and scenario["hero"].get("qualified") == hero.get("qualified")
                                 and (hero.get("qualified") or hero.get("unmetCriteria"))) else FAIL))
    checks.append(Check("selection recorded seed, pool and per-criterion results",
                        PASS if all(k in selection for k in ("seed", "pool_size", "candidates", "criteria")) else FAIL))

    # v0.4 checks: skip with a reason until their lanes land
    checks.append(_policy_check(scenario, strict))
    checks.append(Check("after a scripted approve, attach_history is ALLOWed and BL-AMOX-01 fires", _skip(strict),
                        "rule and chart store land with lanes W3b and Q1.1"))
    transcript = d / "frontdesk_transcript.json"
    checks.append(Check("frontdesk_transcript.json replays with zero REPLAY_DIVERGED", _skip(strict),
                        "transcript authored before 16:00 (ADR-016 section 7)" if not transcript.exists()
                        else "replay adapter lands with lane Q1"))
    return checks


def _policy_check(scenario: dict, strict: bool) -> Check:
    name = "scripted propose_new_chart through policy.decide gives DENY CANDIDATE_IN_REVIEW_OR_HIGHER"
    try:
        from contracts.models.policy import decide

        decide(None, [])  # type: ignore[arg-type]
    except NotImplementedError:
        return Check(name, _skip(strict), "policy.decide lands with lane Q1.1")
    except (TypeError, AttributeError, ValueError) as exc:
        return Check(name, _skip(strict), f"policy.decide present but the scripted call is not wired here: {exc}")
    return Check(name, _skip(strict), "wire the scripted ProposeArgs call once Q1.1 merges")


def _skip(strict: bool) -> str:
    return FAIL if strict else SKIP


def _soft(failed: bool, strict: bool) -> str:
    return (FAIL if strict else WARN) if failed else PASS


def _as_dict(r) -> dict:
    return {"raw_score": r.raw_score, "p": r.p, "band": r.band, "negative_rules_fired": list(r.negative_rules_fired)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--strict", action="store_true", help="the 20:00 gate: WARN and SKIP fail")
    args = parser.parse_args(argv)
    checks = run_checks(args.dir, strict=args.strict)
    for c in checks:
        print(c.line())
    failed = [c for c in checks if c.status == FAIL]
    counts = {s: sum(1 for c in checks if c.status == s) for s in (PASS, WARN, SKIP, FAIL)}
    print(f"fixture_check: {counts}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
