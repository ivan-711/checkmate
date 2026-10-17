"""fixture_check: passes on the committed export, fails on a planted violation, strict mode fails skips."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from data import fixture_check as fc

HERO_DIR = Path(__file__).resolve().parents[1] / "scenarios" / "hero"


def _statuses(checks):
    return {c.name: c.status for c in checks}


def test_committed_export_passes_without_strict():
    checks = fc.run_checks(HERO_DIR)
    assert not [c for c in checks if c.status == fc.FAIL], [c.line() for c in checks if c.status == fc.FAIL]
    names = _statuses(checks)
    assert names["scenario.json validates against the contract models"] == fc.PASS
    assert names["never-say words absent"] == fc.PASS
    assert names["criterion: baseline in REVIEW"] == fc.PASS
    assert names["bands come from the raw cutoffs"] == fc.PASS
    assert any(c.status == fc.SKIP and "policy.decide" in c.detail for c in checks)


def test_strict_mode_turns_skips_and_warns_into_failures():
    checks = fc.run_checks(HERO_DIR, strict=True)
    failed = [c for c in checks if c.status == fc.FAIL]
    assert failed and all(c.status in (fc.PASS, fc.FAIL) for c in checks)


def _plant(hero: dict) -> None:
    """An unknown scorer version makes fixture_check read the exported scores instead of re-scoring them."""
    hero["scorerVersion"] = "planted-scorer"


def test_planted_auto_link_and_banned_word_fail(tmp_path: Path):
    for name in ("scenario.json", "hero.json", "selection.json"):
        shutil.copy(HERO_DIR / name, tmp_path / name)
    hero = json.loads((tmp_path / "hero.json").read_text())
    _plant(hero)
    hero["baseline"]["band"] = "AUTO_LINK"
    hero["cHigh"] = hero["baseline"]["raw_score"] - 0.1  # the baseline now sits above c_high
    (tmp_path / "hero.json").write_text(json.dumps(hero))
    scenario = json.loads((tmp_path / "scenario.json").read_text())
    scenario["alertIfApproved"]["cardText"] += " The AI caught it."
    (tmp_path / "scenario.json").write_text(json.dumps(scenario))
    names = _statuses(fc.run_checks(tmp_path))
    assert names["never-say words absent"] == fc.FAIL
    assert names["no AUTO_LINK anywhere (both birth-year directions)"] == fc.FAIL
    assert names["criterion: baseline in REVIEW"] == fc.FAIL


def test_missing_export_is_a_failure(tmp_path: Path):
    checks = fc.run_checks(tmp_path)
    assert checks[0].status == fc.FAIL and "hero_select" in checks[0].detail


def test_cli_exit_codes():
    assert fc.main(["--dir", str(HERO_DIR)]) == 0
    assert fc.main(["--dir", str(HERO_DIR), "--strict"]) == 1


def _copy(tmp_path: Path) -> tuple[dict, dict]:
    shutil.copytree(HERO_DIR, tmp_path, dirs_exist_ok=True)
    return (json.loads((tmp_path / "scenario.json").read_text()), json.loads((tmp_path / "hero.json").read_text()))


def test_caption_that_claims_a_band_change_the_export_denies_fails(tmp_path: Path):
    scenario, _ = _copy(tmp_path)
    wi = scenario["whatIfs"]["CHANGE_BIRTH_YEAR"]
    assert wi["whatIf"]["band"] == "REVIEW"
    wi["caption"] = "A different birth year: not enough to link."
    (tmp_path / "scenario.json").write_text(json.dumps(scenario))
    names = _statuses(fc.run_checks(tmp_path))
    assert names["captions match the band each what-if ships with"] == fc.FAIL


def test_alert_flag_must_follow_the_band(tmp_path: Path):
    scenario, _ = _copy(tmp_path)
    scenario["whatIfs"]["REMOVE_ADDRESS"]["alertWouldBeHidden"] = False
    (tmp_path / "scenario.json").write_text(json.dumps(scenario))
    assert _statuses(fc.run_checks(tmp_path))["alertWouldBeHidden matches KEEP_SEPARATE"] == fc.FAIL


def test_unchanged_band_changer_fails_when_the_hero_claims_to_qualify(tmp_path: Path):
    scenario, hero = _copy(tmp_path)
    hero["qualified"], hero["unmetCriteria"] = True, []
    scenario["hero"]["qualified"], scenario["hero"]["unmetCriteria"] = True, []
    (tmp_path / "hero.json").write_text(json.dumps(hero))
    (tmp_path / "scenario.json").write_text(json.dumps(scenario))
    assert _statuses(fc.run_checks(tmp_path))["band-changers change the band"] == fc.FAIL


def test_unshipped_birth_year_auto_link_warns_and_strict_fails(tmp_path: Path):
    _, hero = _copy(tmp_path)
    _plant(hero)
    unshipped = next(k for k in hero["whatIfs"] if k.startswith("CHANGE_BIRTH_YEAR")
                     and k != hero["exportedWhatIfKeys"]["CHANGE_BIRTH_YEAR"])
    hero["whatIfs"][unshipped]["band"] = "AUTO_LINK"
    (tmp_path / "hero.json").write_text(json.dumps(hero))
    name = "no AUTO_LINK anywhere (both birth-year directions)"
    assert _statuses(fc.run_checks(tmp_path))[name] == fc.WARN
    assert _statuses(fc.run_checks(tmp_path, strict=True))[name] == fc.FAIL


OVERLAY = "constructed overlay present, labeled and placed (Synthea data plan section 4)"


def test_overlay_passes_on_the_committed_export():
    assert _statuses(fc.run_checks(HERO_DIR))[OVERLAY] == fc.PASS


def test_missing_overlay_fails(tmp_path: Path):
    _copy(tmp_path)
    (tmp_path / "fhir" / "hero_er.json").unlink()
    assert _statuses(fc.run_checks(tmp_path))[OVERLAY] == fc.FAIL


def test_untagged_order_and_er_allergy_history_fail(tmp_path: Path):
    _copy(tmp_path)
    path = tmp_path / "fhir" / "hero_er.json"
    bundle = json.loads(path.read_text())
    order = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "MedicationRequest")
    order["meta"] = {}
    bundle["entry"].append({"resource": {"resourceType": "AllergyIntolerance", "id": "x", "meta": order["meta"]}})
    path.write_text(json.dumps(bundle))
    check = next(c for c in fc.run_checks(tmp_path) if c.name == OVERLAY)
    assert check.status == fc.FAIL and "provenance tag" in check.detail and "AllergyIntolerance" in check.detail


def test_overlay_must_not_touch_identity_or_drop_the_manifest_sentence(tmp_path: Path):
    _copy(tmp_path)
    given = json.loads((tmp_path / "hero.json").read_text())["records"]["CLINIC_CSV"]["given_name"]
    patients = tmp_path / "csv" / "patients.csv"
    patients.write_text(patients.read_text().replace(f",{given},", f",{given}x,"))
    manifest = tmp_path / "scenario_manifest.json"
    m = json.loads(manifest.read_text())
    m["provenance"] = "constructed"
    manifest.write_text(json.dumps(m))
    check = next(c for c in fc.run_checks(tmp_path) if c.name == OVERLAY)
    assert "identity differs" in check.detail and "provenance sentence" in check.detail


def test_allergy_overlay_keeps_a_natural_severe_row_and_adds_only_when_needed():
    from data.hero_overlay import allergy_rows

    natural = [{"START": "2019-01-01", "CODE": "7984", "TYPE": "allergy", "SEVERITY1": "SEVERE", "DESCRIPTION": "penicillin V"}]
    rows = allergy_rows("p", natural)
    assert len(rows) == 1 and rows[0]["CONSTRUCTED"] == "false"
    mild = [{**natural[0], "SEVERITY1": "MILD"}]
    rows = allergy_rows("p", mild)
    assert [r["CONSTRUCTED"] for r in rows] == ["false", "true"] and rows[1]["START"] == "2019-01-01"
    assert rows[1]["SEVERITY1"] == "SEVERE" and rows[1]["REACTION1"] == "39579001"
    assert allergy_rows("p", [])[0]["CONSTRUCTED"] == "true"
