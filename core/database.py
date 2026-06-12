"""Async database engine and session factory."""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from loguru import logger
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(database_url: str, create_schema: bool = False) -> None:
    """Initialize the database engine and session factory.

    Schema is owned by Alembic in production (see :func:`run_migrations`). The
    ``create_schema`` flag is for tests / throwaway databases that build tables
    directly from model metadata instead of running migrations.

    Args:
        database_url: SQLAlchemy-compatible async database URL.
        create_schema: If True, create all tables from model metadata.
    """
    global _engine, _session_factory

    logger.info("Initializing database: {}", database_url.split("@")[-1] if "@" in database_url else database_url)

    engine_kwargs: dict = {"echo": False, "pool_pre_ping": True}
    # SQLite uses a single file and ignores server-style pooling; tune only for
    # real client/server databases (Postgres) to avoid pool exhaustion at scale.
    if not database_url.startswith("sqlite"):
        engine_kwargs.update(pool_size=20, max_overflow=10, pool_recycle=3600)

    _engine = create_async_engine(database_url, **engine_kwargs)

    if _engine.dialect.name == "sqlite":
        @event.listens_for(_engine.sync_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    if create_schema:
        await create_all_tables()

    logger.info("Database initialized successfully")


async def create_all_tables() -> None:
    """Create all tables directly from model metadata.

    Intended for tests and throwaway databases. Production schema is managed by
    Alembic migrations (:func:`run_migrations`).
    """
    from core.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _migrations_dir() -> Path:
    """Resolve the Alembic ``migrations`` directory for source and frozen builds."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "migrations"


def run_migrations(database_url: str) -> None:
    """Apply Alembic migrations up to ``head``.

    Runs synchronously (Alembic's env spins up its own event loop), so call this
    from a sync context at startup before the bot event loop starts. Idempotent.

    Args:
        database_url: SQLAlchemy-compatible async database URL.
    """
    from alembic import command
    from alembic.config import Config

    if database_url.startswith("sqlite"):
        from pathlib import Path

        # Extract path from URL like sqlite+aiosqlite:///data/bot.db
        path_str = database_url.split("///")[-1]
        db_path = Path(path_str)
        if db_path.parent and str(db_path.parent) != ".":
            db_path.parent.mkdir(parents=True, exist_ok=True)

    cfg = Config()
    cfg.set_main_option("script_location", str(_migrations_dir()))
    cfg.set_main_option("sqlalchemy.url", database_url)
    logger.info("Applying database migrations (alembic upgrade head)...")
    command.upgrade(cfg, "head")
    logger.info("Database migrations applied")


async def close_db() -> None:
    """Close the database engine."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        logger.info("Database connection closed")
    _engine = None
    _session_factory = None


def get_engine() -> AsyncEngine:
    """Get the database engine. Raises RuntimeError if not initialized."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the session factory. Raises RuntimeError if not initialized."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session as a context manager.

    Usage:
        async with get_session() as session:
            result = await session.execute(...)
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
