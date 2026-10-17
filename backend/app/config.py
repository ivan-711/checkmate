"""Settings from the environment (.env is gitignored; .env.example documents the keys)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


@dataclass(frozen=True)
class Settings:
    database_url: str
    cors_origins: tuple[str, ...]
    frontdesk_agent_mode: str
    gemini_model_id: str | None
    gemini_api_key_present: bool
    capture_dir: str | None
    git_sha: str | None


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "postgresql://checkmate:checkmate@127.0.0.1:5432/checkmate"),
        cors_origins=tuple(o.strip() for o in os.environ.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if o.strip()),
        frontdesk_agent_mode=os.environ.get("FRONTDESK_AGENT_MODE", "REPLAY"),
        gemini_model_id=os.environ.get("GEMINI_MODEL_ID") or None,
        gemini_api_key_present=bool(os.environ.get("GEMINI_API_KEY")),
        capture_dir=os.environ.get("CHARTGUARD_CAPTURE_DIR") or None,
        git_sha=os.environ.get("GIT_SHA") or None,
    )
