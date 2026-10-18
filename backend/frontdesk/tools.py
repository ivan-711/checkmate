"""The three tool declarations and the ToolResult schema, read once from the frozen ``contracts/tools``."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from contracts.models.policy import ToolName

TOOLS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "tools"
TOOL_RESULT_SCHEMA_FILE = TOOLS_DIR / "tool_result.schema.json"


@cache
def tool_declarations() -> tuple[dict, ...]:
    return tuple(json.loads((TOOLS_DIR / f"{name.value}.json").read_text(encoding="utf-8")) for name in ToolName)


@cache
def tool_result_schema() -> dict:
    return json.loads(TOOL_RESULT_SCHEMA_FILE.read_text(encoding="utf-8"))
