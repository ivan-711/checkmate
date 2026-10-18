"""Import boundaries (architecture §22.5, ADR-016 §1) and the prompt/template invariants."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from backend.frontdesk.prompts import PROMPT_VERSION, system_instruction
from backend.frontdesk.templates import TEMPLATE_LINE, banned_phrase, message_for
from contracts.models.policy import Language, PolicyOutcome, PolicyReason

BACKEND = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names |= {f"{node.module}.{a.name}" for a in node.names}
    return names


def test_only_gemini_py_imports_the_sdk():
    offenders = []
    for path in BACKEND.rglob("*.py"):
        if "tests" in path.parts:
            continue
        if any(n == "google" or n.startswith("google.") for n in _imports(path)):
            offenders.append(path.relative_to(BACKEND).as_posix())
    assert offenders == ["frontdesk/gemini.py"]


def test_only_the_executor_imports_chart_store_writes():
    offenders = []
    for path in BACKEND.rglob("*.py"):
        if "tests" in path.parts or path.parts[-2] == "chart_store":
            continue
        if any(n.startswith("backend.chart_store") for n in _imports(path)):
            offenders.append(path.relative_to(BACKEND).as_posix())
    assert offenders == ["frontdesk/executor.py"]


def test_importing_the_frontdesk_package_and_the_api_does_not_load_the_sdk():
    code = (
        "import os, sys; os.environ['DATABASE_URL']='postgresql://x:x@127.0.0.1:1/checkmate_test_import'; "
        "import backend.frontdesk, backend.frontdesk.loop, backend.frontdesk.adapters, backend.api.intake; "
        "print('google.genai' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=BACKEND.parent, check=True)
    assert out.stdout.strip() == "False"


def test_prompt_version_and_rules():
    text = system_instruction()
    assert PROMPT_VERSION == "fd-prompt/1"
    assert "NEW_CHART_CREATED" in text and "UNKNOWN" in text and "verbatim" in text
    assert "---" not in text[:5]  # front matter stripped


@pytest.mark.parametrize(
    "text, created, hit",
    [
        ("Listo, creé su expediente.", False, True),
        ("Listo, creé su expediente.", True, False),
        ("I created your chart, please sit down.", False, True),
        ("Your chart has been created.", True, False),
        ("Un momento, una persona de registro le va a ayudar.", False, False),
        ("This system is HIPAA-compliant.", True, True),
        ("The AI caught the duplicate.", True, True),
        ("Gracias, María. Una persona de registro confirmará su expediente.", False, False),
    ],
)
def test_banned_phrases(text, created, hit):
    assert (banned_phrase(text, new_chart_created=created) is not None) is hit


def test_messages_exist_for_every_reason_in_both_languages():
    for reason in PolicyReason:
        for lang in Language:
            msg = message_for(f"gate.deny.{reason.value.lower()}", PolicyOutcome.DENY, reason, lang)
            assert msg and msg != TEMPLATE_LINE[lang], (reason, lang)
    for key in ("gate.allow.search", "gate.allow.propose", "gate.allow.attach"):
        assert message_for(key, PolicyOutcome.ALLOW, None, Language.ES) != TEMPLATE_LINE[Language.ES]
