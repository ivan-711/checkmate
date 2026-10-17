"""One engine, one pool per process (architecture §2). Connections are short-lived."""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from contracts.version import POOL_MAX_OVERFLOW, POOL_SIZE, POOL_TIMEOUT_S, STATEMENT_TIMEOUT_S


def make_engine(database_url: str) -> Engine:
    url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(
        url,
        pool_size=POOL_SIZE,
        max_overflow=POOL_MAX_OVERFLOW,
        pool_timeout=POOL_TIMEOUT_S,
        pool_pre_ping=True,
        connect_args={"options": f"-c statement_timeout={STATEMENT_TIMEOUT_S * 1000}",
                      "connect_timeout": POOL_TIMEOUT_S},
    )


def db_is_up(engine: Engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False
