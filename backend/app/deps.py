"""FastAPI dependencies that hand routers the one engine and the settings from app state."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.engine import Engine

from backend.app.config import Settings


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


EngineDep = Annotated[Engine, Depends(get_engine)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
