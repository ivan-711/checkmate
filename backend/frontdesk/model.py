"""Model adapter interface shared by the LIVE (Gemini) and REPLAY adapters.

Pinned in Q1-INTERFACES.md (Q1.2 -> Q1.4). Adapters never raise to the loop: every failure is an
``ErrorStep``. Author: Christian Flores (Q1.2 builder).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from contracts.models.intake import AgentMode
from contracts.models.policy import Language

ErrorKind = Literal[
    "TIMEOUT",
    "UNAVAILABLE",
    "MALFORMED",
    "SAFETY_BLOCKED",
    "REPLAY_DIVERGED",
    "REPLAY_INPUT_MISMATCH",
]

MessageRole = Literal["user", "model", "function"]


@dataclass(frozen=True)
class ToolCallStep:
    tool_name: str
    args: dict
    model_call_id: str | None
    latency_ms: int
    mode: AgentMode


@dataclass(frozen=True)
class TextStep:
    text: str
    latency_ms: int
    mode: AgentMode


@dataclass(frozen=True)
class ErrorStep:
    kind: ErrorKind
    retryable: bool
    mode: AgentMode


ModelStep = ToolCallStep | TextStep | ErrorStep


@dataclass(frozen=True)
class Message:
    role: MessageRole
    text: str | None = None
    tool_call: ToolCallStep | None = None
    tool_result: dict | None = None


@dataclass(frozen=True)
class ModelRequest:
    session_id: UUID
    turn_index: int
    step_index: int
    language: Language
    prompt_version: str
    tool_schema_version: str
    system_instruction: str
    messages: tuple[Message, ...]
    tools: tuple[dict, ...]  # the three contracts/tools/*.json declarations
    user_text_folded: str  # this turn's typed text, folded (for replay matching)
    last_tool_result_sha256: str | None  # sha256 of the previous step's minimal ToolResult


class AgentModel(Protocol):
    mode: AgentMode

    def next_step(self, req: ModelRequest) -> ModelStep: ...
