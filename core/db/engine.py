from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from core.config import ConfigManager


DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/meetyou"


def get_database_url(config: ConfigManager | None = None) -> str:
    env_value = str(os.environ.get("MEETYOU_DATABASE_URL") or "").strip()
    if env_value:
        return env_value
    if config is None:
        try:
            config = ConfigManager()
        except Exception:
            return DEFAULT_DATABASE_URL
    return str(config.get("database_url") or DEFAULT_DATABASE_URL).strip() or DEFAULT_DATABASE_URL


def create_db_engine(database_url: str, *, echo: bool = False) -> Engine:
    return create_engine(database_url, echo=echo, future=True)


def create_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
