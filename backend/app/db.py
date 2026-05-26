"""SQLAlchemy engine, session factory, and declarative base.

A single Engine is created per process and shared across requests. Sessions
are short-lived and scoped per unit of work (one request, one ETL run).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_settings = get_settings()

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def init_db() -> None:
    """Create all tables if they do not already exist.

    For this POC we use create_all for simplicity. In production, schema
    changes would be managed by Alembic migrations to support zero-downtime
    deploys and reversible changes.
    """
    # Import models so they register on Base.metadata before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager that commits on success and rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
