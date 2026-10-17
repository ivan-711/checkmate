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


def test_planted_auto_link_and_banned_word_fail(tmp_path: Path):
    for name in ("scenario.json", "hero.json", "selection.json"):
        shutil.copy(HERO_DIR / name, tmp_path / name)
    hero = json.loads((tmp_path / "hero.json").read_text())
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
    for name in ("scenario.json", "hero.json", "selection.json"):
        shutil.copy(HERO_DIR / name, tmp_path / name)
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


def test_unshipped_birth_year_auto_link_warns_and_strict_fails():
    loose = _statuses(fc.run_checks(HERO_DIR))
    strict = _statuses(fc.run_checks(HERO_DIR, strict=True))
    name = "no AUTO_LINK anywhere (both birth-year directions)"
    assert loose[name] == fc.WARN and strict[name] == fc.FAIL
