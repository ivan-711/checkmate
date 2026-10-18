"""The versioned FrontDesk system instruction, loaded once from ``fd-prompt-<n>.md``."""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

PROMPT_VERSION = "fd-prompt/1"
_PROMPT_FILE = Path(__file__).with_name("fd-prompt-1.md")
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


@cache
def system_instruction() -> str:
    """The prompt body without its front matter. Cached: the file is read once per process."""
    raw = _PROMPT_FILE.read_text(encoding="utf-8")
    match = _FRONT_MATTER.match(raw)
    if match is None or f"version: {PROMPT_VERSION}" not in match.group(1):
        raise RuntimeError(f"{_PROMPT_FILE.name} must declare version: {PROMPT_VERSION}")
    return raw[match.end() :].strip()
