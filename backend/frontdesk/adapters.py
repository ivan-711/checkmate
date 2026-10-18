"""Adapter selection: ``make_model(mode, settings)`` is the one seam lane Q1.4 edits for REPLAY.

The Gemini SDK is imported lazily, only when a LIVE adapter is built, so importing this module
(and the API process in REPLAY mode) never loads it.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

from backend.app.config import Settings
from backend.frontdesk.model import AgentModel, ErrorStep, ModelRequest, ModelStep
from contracts.models.intake import AgentMode

log = logging.getLogger("checkmate.frontdesk.adapters")

MODE_AUTO = "AUTO"


class UnavailableAgentModel:
    """Every step is a non-retryable UNAVAILABLE: the turn degrades to the template through the
    same loop. Used when LIVE has no key or model id, and as the REPLAY placeholder until Q1.4's
    transcript player lands."""

    def __init__(self, mode: AgentMode) -> None:
        self.mode = mode

    def next_step(self, req: ModelRequest) -> ModelStep:
        return ErrorStep(kind="UNAVAILABLE", retryable=False, mode=self.mode)


class ModelFactory(Protocol):
    def __call__(self, mode: AgentMode, settings: Settings) -> AgentModel: ...


def make_model(mode: AgentMode, settings: Settings) -> AgentModel:
    if mode == AgentMode.LIVE:
        if not settings.gemini_api_key_present or not settings.gemini_model_id:
            log.warning("LIVE requested without GEMINI_API_KEY or GEMINI_MODEL_ID; turns degrade to the template")
            return UnavailableAgentModel(AgentMode.LIVE)
        from backend.frontdesk.gemini import GeminiAgentModel  # the only module importing the SDK

        # The key is read here and handed to the client; it is never logged, stored or returned.
        return GeminiAgentModel(api_key=os.environ["GEMINI_API_KEY"], model_id=settings.gemini_model_id)
    # Q1.4 replaces this with ReplayAgentModel(transcript) in backend/frontdesk/replay.py.
    return UnavailableAgentModel(AgentMode.REPLAY)


def pin_mode(settings: Settings) -> AgentMode:
    """FRONTDESK_AGENT_MODE: LIVE, REPLAY, or AUTO (LIVE only if a key exists and the probe answers)."""
    raw = (settings.frontdesk_agent_mode or "").upper()
    if raw == AgentMode.LIVE.value:
        return AgentMode.LIVE
    if raw == MODE_AUTO and settings.gemini_api_key_present and settings.gemini_model_id:
        from backend.frontdesk.gemini import probe_live

        return (
            AgentMode.LIVE
            if probe_live(api_key=os.environ["GEMINI_API_KEY"], model_id=settings.gemini_model_id)
            else AgentMode.REPLAY
        )
    return AgentMode.REPLAY
