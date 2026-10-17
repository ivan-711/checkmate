"""The CI workflow stays pinned and lock-file only (CLAUDE.md reviewer checklist 15; no secrets in CI)."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "ci.yml"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def _steps():
    for name, job in _jobs().items():
        for step in job.get("steps", []):
            yield name, step


def test_every_action_is_pinned_by_commit_sha():
    for job, step in _steps():
        uses = step.get("uses")
        if uses:
            ref = uses.split("@", 1)[1]
            assert SHA40.match(ref), f"{job}: {uses} is not pinned by SHA"


def test_installs_only_from_lock_files():
    text = WORKFLOW.read_text()
    assert "uv sync --frozen" in text
    assert "npm ci" in text
    assert re.search(r"\buv sync(?! --frozen)", text) is None
    assert re.search(r"\bnpm install\b", text) is None
    assert re.search(r"\bpip install\b", text) is None
    assert re.search(r"\buvx\b", text) is None, "uvx resolves dependencies live; run tools from the lock with uv run"


def test_required_jobs_present():
    jobs = _jobs()
    for name in ("lint-and-tests", "contract-test", "fixture-check", "frontend-build", "secret-scan",
                 "harness-on-main", "acceptance-typecheck", "protected-paths"):
        assert name in jobs, name
    text = WORKFLOW.read_text()
    assert "cmp CLAUDE.md AGENTS.md" in text
    assert "python -m contracts.build_openapi --check" in text
    assert "--exclude-checks not_a_server_error" in text
    assert "eval.compare" in text and "--label revert" in text


def test_no_secrets_and_replay_only():
    text = WORKFLOW.read_text()
    assert "GEMINI_API_KEY" not in text
    assert "secrets." not in text
    assert "FRONTDESK_AGENT_MODE: REPLAY" in text


def test_database_image_is_pinned_by_digest():
    for job in _jobs().values():
        for service in job.get("services", {}).values():
            assert "@sha256:" in service["image"], service["image"]


def test_designed_422_exclusion_is_exactly_the_cursor_since_and_idempotency_operations():
    """The schemathesis exclusion covers exactly the operations whose correct 422s it would flag, no more."""
    import json

    step = next(s for s in _jobs()["contract-test"]["steps"] if "DESIGNED_422_OPERATIONS" in (s.get("env") or {}))
    listed = set(step["env"]["DESIGNED_422_OPERATIONS"].split("|"))
    spec = json.loads((WORKFLOW.parents[2] / "contracts" / "openapi.json").read_text())
    expected = {f"{method.upper()} {path}" for path, ops in spec["paths"].items() for method, op in ops.items()
                if {p["name"] for p in op.get("parameters", [])} & {"cursor", "since", "Idempotency-Key"}}
    assert listed == expected, listed ^ expected
    run = step["run"]
    assert "--exclude-checks not_a_server_error,positive_data_acceptance" in run and '"${include[@]}"' in run
    assert "--checks all --exclude-checks not_a_server_error \"${exclude[@]}\"" in run


def test_request_log_check_reads_the_structured_status_not_the_query_string(tmp_path):
    """A fuzzed `?status=517` on uvicorn's access line is not a 5xx (seen in CI at 29bae25)."""
    import subprocess

    step = next(s for s in _jobs()["contract-test"]["steps"] if "status=5" in (s.get("run") or ""))
    log = tmp_path / "request.log"
    log.write_text(
        "INFO checkmate.request method=GET path=/api/v1/alerts status=422 latency_ms=3 mode=REPLAY request_id=x\n"
        'INFO:     127.0.0.1:51024 - "GET /api/v1/alerts?status=517&limit=150 HTTP/1.1" 422 Unprocessable Entity\n'
        "INFO checkmate.request method=GET path=/api/v1/events status=501 latency_ms=1 mode=REPLAY request_id=y\n")
    ok = subprocess.run(["bash", "-c", step["run"]], check=False, cwd=tmp_path, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    log.write_text(log.read_text() + "INFO checkmate.request method=GET path=/x status=500 latency_ms=2 mode=REPLAY\n")
    bad = subprocess.run(["bash", "-c", step["run"]], check=False, cwd=tmp_path, capture_output=True, text=True)
    assert bad.returncode != 0 and "status=500" in bad.stdout
    log.write_text('INFO:     127.0.0.1:1 - "GET /?status=500 HTTP/1.1" 200 OK\n')
    empty = subprocess.run(["bash", "-c", step["run"]], check=False, cwd=tmp_path, capture_output=True, text=True)
    assert empty.returncode != 0 and "vacuous" in empty.stdout
