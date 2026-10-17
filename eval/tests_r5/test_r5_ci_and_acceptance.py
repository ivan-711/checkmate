"""R5: CI workflow and acceptance-script checks beyond the builder's own (merge rules; G16 steps)."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SPEC = ROOT / "eval" / "acceptance" / "g16.spec.ts"
README = ROOT / "eval" / "acceptance" / "README.md"


def _run_steps(job: str):
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    return [s.get("run", "") for s in jobs[job]["steps"]]


def test_request_log_5xx_check_cannot_pass_on_an_empty_log():
    """The 'no non-501 5xx' assertion is vacuous when the API logs nowhere: the step must also require at
    least one status= line (schemathesis generated hundreds of requests)."""
    for job in ("contract-test", "acceptance-run"):
        step = next(s for s in _run_steps(job) if "status=5" in s)
        assert re.search(r"grep -c(?: -E)? ['\"]?status=", step) and re.search(r"-eq 0|== 0|-lt 1|-le 0|\[ \"?\$\w+\"? ", step), \
            f"{job}: the request-log check does not fail when no request was logged"


def test_baseline_download_failure_is_distinguished_from_no_previous_run():
    """harness-on-main: on a flaky network 'gh run download' fails and the job silently falls back to
    'invariants only', so a merge beyond tolerance is never reverted. A download failure for an existing
    green run must retry or fail the job, never skip the tolerance check."""
    step = next(s for s in _run_steps("harness-on-main") if "gh run download" in s)
    assert "retry" in step.lower() or "exit 1" in step.split("else")[0], step


def test_fast_harness_posts_the_resample_count_with_the_intervals():
    """The posted table carries 95% intervals; the number of resamples behind them must be on the comment."""
    from eval.harness.summary import render
    from eval.harness.testing import fast_run

    r = fast_run()
    text = render(r.numbers, r.manifest)
    assert str(r.manifest["bootstrapResamples"]) in text and "resample" in text.lower()


def test_acceptance_script_binds_to_the_hero_identity_not_just_the_shape():
    """G16 steps 3 and 6: the two cards and the golden record must be the hero's. A stub rendering any two
    cards, 'REVIEW', 'BL-AMOX-01' and a non-zero tile would pass today's script."""
    text = SPEC.read_text()
    assert re.search(r"hero\.json|scenario\.json|givenName|familyName|displayName", text), \
        "the script never reads the hero export nor asserts a name/DOB on the cards or golden record"


def test_acceptance_readme_lists_every_testid_and_attribute_the_script_reads():
    spec = SPEC.read_text()
    readme = README.read_text()
    ids = set(re.findall(r"^\s+\w+:\s+'([a-z0-9-]+)'", spec, re.MULTILINE))
    documented = set(re.findall(r"^\| `([a-z0-9-]+)` \|", readme, re.MULTILINE))
    assert ids == documented, (ids ^ documented)
    for attr in set(re.findall(r"\[data-([a-z-]+)=", spec)):
        assert f"data-{attr}" in readme, attr


def test_protected_paths_job_covers_both_protected_trees_and_the_hero_dir_is_named():
    step = next(s for s in _run_steps("protected-paths") if "git diff" in s)
    assert "eval/acceptance" in step and "eval/expectations" in step
