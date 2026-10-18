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


# Never-say link claims (feature plan of 2026-10-18, item D4): the agent has no tool that links records,
# so a first-person link claim is never true. The list is substring-matched on the folded text;
# banned_phrase() maps the apostrophe code points the model types onto the ASCII one first.
LINK_CLAIMS = (
    "I linked you to that record.",
    "Done, I've linked your records.",
    "Done, I’ve linked your records to your old chart.",
    "I have linked your records.",
    "We've linked your records to your existing chart.",
    "We have linked your records.",
    "I've now linked you to your existing chart.",
    "I've just linked your records.",
    "I've successfully linked your records.",
    "I've already linked your records to your old chart.",
    "I already linked you to that record.",
    "We have already linked your records.",
    "Your records are now linked.",
    "Listo, lo vinculé a su expediente.",
    "La vinculé con su expediente anterior.",
    "Encontré dos expedientes y los vinculé.",
    "He vinculado sus expedientes.",
    "Hemos vinculado su expediente.",
    "Ya vinculé su expediente con el anterior.",
    "Acabo de vincular su expediente.",
    "Acabamos de vincular sus expedientes.",
    "Su expediente ahora está vinculado.",
    "Sus expedientes ahora están vinculados.",
)

# True statements about a link, or about who links: the registrar's past action ("already linked"),
# the prompt's ALREADY_LINKED reply, the gate's own tool message, and a refusal to link.
LINK_TALK_ALLOWED = (
    "Your record was found and a registrar will help with the rest.",
    "Your record was found and linked. A registrar will help with the rest.",
    "Your records are already linked; a registrar will help with the rest.",
    "A registrar will confirm whether your records should be linked.",
    "I cannot link records. Only a registrar can.",
    "Su expediente fue encontrado y vinculado. Una persona de registro le ayudará.",
    "Su expediente ya está vinculado; una persona de registro le ayudará.",
    "Una persona de registro decide si se vincula su expediente.",
    "No puedo vincular expedientes; una persona de registro lo hará.",
)


@pytest.mark.parametrize("text", LINK_CLAIMS)
def test_first_person_link_claims_are_never_allowed(text):
    # Never-say, not an effect claim: a chart created this turn does not license a link claim.
    assert banned_phrase(text, new_chart_created=False) is not None
    assert banned_phrase(text, new_chart_created=True) is not None


@pytest.mark.parametrize("text", LINK_TALK_ALLOWED)
def test_talk_about_a_registrar_link_is_allowed(text):
    assert banned_phrase(text, new_chart_created=False) is None


@pytest.mark.parametrize(
    "apostrophe", ["\u2018", "\u2019", "\u02bc"], ids=["left-quote", "right-quote", "modifier-letter"]
)
def test_apostrophe_code_points_match_the_ascii_entry(apostrophe):
    """The model types curly or modifier-letter apostrophes; one ASCII entry must catch them all."""
    assert banned_phrase(f"I{apostrophe}ve linked your records.", new_chart_created=False) == "i've linked"
    assert banned_phrase(f"This can{apostrophe}t be jailbroken.", new_chart_created=True) == "can't be jailbroken"
