"""Database Connection Pooling and Session Management for SchemaSense 2.0."""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from schemasense.config import get_platform_config
from schemasense.db.base import Base

logger = logging.getLogger("schemasense.db")

_ENGINE: Engine | None = None
_SESSION_FACTORY: sessionmaker[Session] | None = None


def get_engine(db_url: str | None = None) -> Engine:
    """Returns the platform database engine, initializing connection pooling."""
    global _ENGINE
    if _ENGINE is not None and db_url is None:
        return _ENGINE

    url = db_url or get_platform_config().platform_db_url
    if not url:
        # Simple Mode or unconfigured platform DB: raise descriptive error
        raise RuntimeError(
            "SchemaSense platform database is not configured. "
            "Set SCHEMASENSE_PLATFORM_DB_URL or configure Advanced Mode."
        )

    engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if "sqlite" in url:
        # SQLite concurrency flags for test & development
        engine_kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(url, **engine_kwargs)
    if db_url is None:
        _ENGINE = engine
    return engine


def get_session_factory(db_url: str | None = None) -> sessionmaker[Session]:
    """Returns the thread-safe sessionmaker bound to the platform engine."""
    global _SESSION_FACTORY
    if _SESSION_FACTORY is not None and db_url is None:
        return _SESSION_FACTORY

    engine = get_engine(db_url)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    if db_url is None:
        _SESSION_FACTORY = factory
    return factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding an isolated transaction session."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all_tables(engine: Engine | None = None) -> None:
    """Directly creates all declared platform schema tables (primarily for tests)."""
    target_engine = engine or get_engine()
    Base.metadata.create_all(bind=target_engine)


def drop_all_tables(engine: Engine | None = None) -> None:
    """Drops all declared platform schema tables (primarily for test teardown)."""
    target_engine = engine or get_engine()
    Base.metadata.drop_all(bind=target_engine)
