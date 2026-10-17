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
import csv
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
from data import hero_overlay as overlay
from data.hero_export import iso_date
from data.hero_select import P_RAISE_BOUND, ROBUSTNESS_TOLERANCE, intake_rendering
from eval.harness import product, standin, whatifs
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
    engine, reason = _engine_for(hero["scorerVersion"])
    if engine is None:
        checks.append(Check("re-score with the named scorer", _skip(strict), reason))
        base, what, intake = hero["baseline"], hero["whatIfs"], hero["intake"]
    else:
        match, weights = engine.match, engine.shipped_weights
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
    exported_keys = hero.get("exportedWhatIfKeys") or {}
    year_key = exported_keys.get(whatifs.CHANGE_BIRTH_YEAR)
    if year_key is None:  # older exports: the direction whose raw score was shipped
        shipped_raw = scenario["whatIfs"][whatifs.CHANGE_BIRTH_YEAR]["whatIf"]["rawScore"]
        year_key = next(k for k, v in what.items() if k.startswith(whatifs.CHANGE_BIRTH_YEAR)
                        and abs(v["raw_score"] - shipped_raw) < 1e-6)
    shown = {k: v for k, v in what.items() if not k.startswith(whatifs.CHANGE_BIRTH_YEAR) or k == year_key}
    unshipped = {k: v for k, v in what.items() if k not in shown}
    every = [base, intake, *shown.values()]
    checks.append(Check("p in [0, 1] everywhere", PASS if all(0.0 <= v["p"] <= 1.0 for v in every) else FAIL))
    shown_auto = [k for k, v in shown.items() if v["band"] == BAND_AUTO_LINK]
    if base["band"] == BAND_AUTO_LINK or intake["band"] == BAND_AUTO_LINK:
        shown_auto.append("baseline or intake")
    unshipped_auto = [k for k, v in unshipped.items() if v["band"] == BAND_AUTO_LINK]
    # both birth-year directions count (independent review #1): a shipped AUTO_LINK always fails; the
    # direction not shipped warns on the provisional hero and fails the 20:00 gate (--strict)
    status = FAIL if shown_auto else _soft(bool(unshipped_auto), strict)
    checks.append(Check("no AUTO_LINK anywhere (both birth-year directions)", status,
                        ", ".join(shown_auto + [f"{k} (not shipped)" for k in unshipped_auto])))
    raised = [k for k, v in shown.items() if v["p"] > base["p"] + P_RAISE_BOUND]
    checks.append(Check(f"no what-if raises p above baseline + {P_RAISE_BOUND}", _soft(bool(raised), strict), ", ".join(raised)))
    checks.extend(_caption_checks(scenario, hero, strict))
    checks.append(Check("no negative rule fires on the baseline", PASS if not base["negative_rules_fired"] else FAIL,
                        ", ".join(base["negative_rules_fired"])))
    checks.append(Check("bands come from the raw cutoffs", PASS if all(
        s["band"] == band_for(s["raw_score"], c_low, c_high, s["negative_rules_fired"]) for s in every) else FAIL))

    # the selection criteria
    er_iso = {**er, "birth_date": iso_date(er.get("birth_date"))}
    criteria = {
        "baseline in REVIEW": base["band"] == BAND_REVIEW,
        "REMOVE_ADDRESS drops to KEEP_SEPARATE": what[whatifs.REMOVE_ADDRESS]["band"] == BAND_KEEP_SEPARATE,
        "CHANGE_BIRTH_YEAR +1 and -1 drop to KEEP_SEPARATE": all(
            what[f"{whatifs.CHANGE_BIRTH_YEAR}:{d}"]["band"] == BAND_KEEP_SEPARATE for d in ("+1", "-1")),
        # robustness is met only when the edit applies to the ER record (an unapplied edit is not evidence)
        f"SWAP_DOB_DAY_MONTH applies and moves p by <= {ROBUSTNESS_TOLERANCE}":
            whatifs.is_applicable(whatifs.SWAP_DOB_DAY_MONTH, er_iso)
            and abs(what[whatifs.SWAP_DOB_DAY_MONTH]["p"] - base["p"]) <= ROBUSTNESS_TOLERANCE,
        f"ACCENT_HYPHEN_SURNAME applies and moves p by <= {ROBUSTNESS_TOLERANCE}":
            whatifs.is_applicable(whatifs.ACCENT_HYPHEN_SURNAME, er_iso)
            and abs(what[whatifs.ACCENT_HYPHEN_SURNAME]["p"] - base["p"]) <= ROBUSTNESS_TOLERANCE,
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

    checks.extend(_overlay_checks(d, hero))

    # v0.4 checks: skip with a reason until their lanes land
    checks.append(_policy_check(scenario, strict))
    checks.append(Check("after a scripted approve, attach_history is ALLOWed and BL-AMOX-01 fires", _skip(strict),
                        "rule and chart store land with lanes W3b and Q1.1"))
    transcript = d / "frontdesk_transcript.json"
    checks.append(Check("frontdesk_transcript.json replays with zero REPLAY_DIVERGED", _skip(strict),
                        "transcript authored before 16:00 (ADR-016 section 7)" if not transcript.exists()
                        else "replay adapter lands with lane Q1"))
    return checks


def _overlay_checks(d: Path, hero: dict) -> list[Check]:
    """The constructed overlay is present, labeled, placed as specified and leaves identity untouched."""
    name = "constructed overlay present, labeled and placed (Synthea data plan section 4)"
    problems: list[str] = []
    manifest_path, fhir_path = d / overlay.MANIFEST_FILE, d / overlay.FHIR_FILE
    patients_path, allergies_path = d / overlay.PATIENTS_FILE, d / overlay.ALLERGIES_FILE
    missing = [p.name for p in (manifest_path, fhir_path, patients_path, allergies_path) if not p.exists()]
    if missing:
        return [Check(name, FAIL, f"missing {missing}; run `python -m data.hero_select`")]
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("provenance") != overlay.PROVENANCE_SENTENCE or not manifest.get("constructed") or any(
            item.get("provenance") != overlay.PROVENANCE_SENTENCE for item in manifest["constructed"]):
        problems.append("scenario_manifest.json lacks the provenance sentence on every constructed item")
    resources = [e["resource"] for e in json.loads(fhir_path.read_text()).get("entry", [])]
    tag = {"system": overlay.PROVENANCE_SYSTEM, "code": overlay.PROVENANCE_CODE}
    untagged = [r["resourceType"] for r in resources if tag not in (r.get("meta") or {}).get("tag", [])]
    if untagged:
        problems.append(f"FHIR overlay resources without the provenance tag: {untagged}")
    if any(r["resourceType"] == "AllergyIntolerance" for r in resources):
        problems.append("the ER source carries an AllergyIntolerance (it must be registered without the history)")
    orders = [r for r in resources if r["resourceType"] == "MedicationRequest" and r.get("status") == "active"
              and any(c.get("code") == overlay.ORDER_RXNORM for c in r["medicationCodeableConcept"]["coding"])]
    if len(orders) != 1:
        problems.append(f"expected one active RxNorm {overlay.ORDER_RXNORM} order in the ER source, found {len(orders)}")
    with allergies_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if "CONSTRUCTED" not in (rows[0] if rows else {}):
        problems.append("allergies.csv has no CONSTRUCTED column")
    severe = [r for r in rows if r.get("CODE") == overlay.ALLERGY_RXNORM and r.get("TYPE") == "allergy"
              and not r.get("STOP") and "SEVERE" in (r.get("SEVERITY1"), r.get("SEVERITY2"))]
    if not severe:
        problems.append(f"no active SEVERE RxNorm {overlay.ALLERGY_RXNORM} allergy row in the Clinic CSV")
    elif orders and not all(orders[0]["authoredOn"][:10] > r["START"] for r in severe):
        problems.append("the order is not authored after the allergy START")
    er_patient = next((r for r in resources if r["resourceType"] == "Patient"), {})
    er, clinic = hero["records"]["ER_FHIR"], hero["records"]["CLINIC_CSV"]
    er_name = (er_patient.get("name") or [{}])[0]
    if (er_name.get("given"), er_name.get("family"), er_patient.get("birthDate")) != (
            [er["given_name"]], er["family_name"], er["birth_date"]):
        problems.append("ER overlay identity differs from the selected ER record")
    with patients_path.open(newline="", encoding="utf-8") as fh:
        prow = next(csv.DictReader(fh), {})
    if (prow.get("FIRST"), prow.get("LAST"), prow.get("BIRTHDATE"), prow.get("ADDRESS") or None) != (
            clinic["given_name"], clinic["family_name"], clinic["birth_date"], clinic["address_line"]):
        problems.append("Clinic overlay identity differs from the selected Clinic record")
    return [Check(name, FAIL if problems else PASS, "; ".join(problems))]


def _caption_checks(scenario: dict, hero: dict, strict: bool) -> list[Check]:
    """Every shipped caption and alert flag matches the band it ships with (R5 #1/#13; independent #2)."""
    out: list[Check] = []
    mismatched, hidden_wrong, unchanged = [], [], []
    er = dict(hero["records"]["ER_FHIR"])
    er["birth_date"] = iso_date(er.get("birth_date"))
    for button, wi in scenario["whatIfs"].items():
        base_band, band = wi["baseline"]["band"], wi["whatIf"]["band"]
        # recomputed from what the button does on the ER record: a caption claiming an effect that the
        # numbers (or an inapplicable edit) do not show fails
        expected = whatifs.caption_of(button, er, base_band, band, wi["whatIf"]["p"] - wi["baseline"]["p"])
        if wi["caption"] != expected or ("not enough to link" in wi["caption"].lower() and band != BAND_KEEP_SEPARATE):
            mismatched.append(f"{button}: {wi['caption']!r} ships with {band}")
        if wi["alertWouldBeHidden"] != (band == BAND_KEEP_SEPARATE):
            hidden_wrong.append(f"{button}: alertWouldBeHidden={wi['alertWouldBeHidden']} with {band}")
        if whatifs.BUTTON_KIND[button] == "band_changer" and band == base_band:
            unchanged.append(button)
    out.append(Check("captions match the band each what-if ships with", FAIL if mismatched else PASS,
                     "; ".join(mismatched)))
    out.append(Check("alertWouldBeHidden matches KEEP_SEPARATE", FAIL if hidden_wrong else PASS, "; ".join(hidden_wrong)))
    criterion = {whatifs.REMOVE_ADDRESS: "remove_address_keep_separate",
                 whatifs.CHANGE_BIRTH_YEAR: "change_birth_year_keep_separate"}
    labelled = set(hero.get("unmetCriteria") or ())
    honest = all(criterion[b] in labelled for b in unchanged) and not hero.get("qualified")
    # a band-changer whose band did not change fails, unless the export is a best-partial hero that names
    # this criterion as unmet (then it warns, and the 20:00 gate fails it)
    status = PASS if not unchanged else (WARN if honest and not strict else FAIL)
    out.append(Check("band-changers change the band", status,
                     ", ".join(unchanged) + (" (best partial; listed in unmetCriteria)" if unchanged and honest else "")))
    return out


def _engine_for(scorer_version: str):
    """The engine that produced the export: the stand-in for harness self-tests, else W2's engine."""
    if scorer_version == standin.SCORER_VERSION:
        return product.standin_engine(), ""
    try:
        engine = product.load_engine()
    except product.ProductUnavailable as exc:
        return None, f"export names scorer {scorer_version}; {exc}"
    if engine.scorer_version != scorer_version:
        return None, f"export names scorer {scorer_version} but the engine ships {engine.scorer_version}; re-export"
    return engine, ""


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
