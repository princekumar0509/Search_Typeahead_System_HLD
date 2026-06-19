"""Database engine and session management (SQLAlchemy 2.0 style)."""
from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# ``pool_pre_ping`` guards against stale connections (common with containers
# restarting Postgres underneath a long-lived pool).
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped session.

    The session is always closed, and rolled back on error, to avoid leaking
    connections back to the pool in a dirty state.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they do not exist (safe for repeated calls).

    In production migrations would be handled by Alembic; for this assignment
    we create the schema declaratively on startup for convenience.
    """
    from app.models import db_models  # noqa: F401  (import registers the model)

    Base.metadata.create_all(bind=engine)
    logger.info("Database schema ensured.")
