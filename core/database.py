"""Async database engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from loguru import logger
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(database_url: str) -> None:
    """Initialize the database engine and create tables.

    Args:
        database_url: SQLAlchemy-compatible async database URL.
    """
    global _engine, _session_factory

    logger.info("Initializing database: {}", database_url.split("@")[-1] if "@" in database_url else database_url)

    _engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
    )

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

    # Create all tables
    from core.models import Base

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_schema_upgrades(conn)

    logger.info("Database initialized successfully")


async def _run_schema_upgrades(conn) -> None:
    """Apply lightweight additive schema upgrades for existing installations."""
    dialect = conn.dialect.name
    table_names = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
    if "playlists" in table_names:
        playlist_columns = await conn.run_sync(
            lambda sync_conn: {col["name"] for col in inspect(sync_conn).get_columns("playlists")}
        )
        if "name_key" not in playlist_columns or "playlist_items" not in table_names:
            logger.warning("Rebuilding playlist tables for the v2 playlist schema")
            for table_name in (
                "playlist_item_votes",
                "playlist_votes",
                "playlist_items",
                "playlist_tracks",
                "playlists",
            ):
                if table_name in table_names:
                    await conn.execute(text(f"DROP TABLE {table_name}"))

            from core.models import Playlist, PlaylistItem, PlaylistItemVote

            await conn.run_sync(Playlist.__table__.create)
            await conn.run_sync(PlaylistItem.__table__.create)
            await conn.run_sync(PlaylistItemVote.__table__.create)

    columns = await conn.run_sync(
        lambda sync_conn: {col["name"] for col in inspect(sync_conn).get_columns("fx_presets")}
    )

    statements: list[str] = []
    if "preset_data" not in columns:
        statements.append("ALTER TABLE fx_presets ADD COLUMN preset_data TEXT")
    if "is_compatible" not in columns:
        if dialect == "postgresql":
            statements.append("ALTER TABLE fx_presets ADD COLUMN is_compatible BOOLEAN DEFAULT TRUE")
        else:
            statements.append("ALTER TABLE fx_presets ADD COLUMN is_compatible BOOLEAN DEFAULT 1")

    for statement in statements:
        logger.info("Applying schema upgrade: {}", statement)
        await conn.execute(text(statement))

    # Check guild_settings table
    guild_settings_columns = await conn.run_sync(
        lambda sync_conn: {col["name"] for col in inspect(sync_conn).get_columns("guild_settings")}
    )
    if "panel_message_id" not in guild_settings_columns:
        if dialect == "postgresql":
            upgrade_stmt = "ALTER TABLE guild_settings ADD COLUMN panel_message_id BIGINT"
        else:
            upgrade_stmt = "ALTER TABLE guild_settings ADD COLUMN panel_message_id INTEGER"
        logger.info("Applying schema upgrade: {}", upgrade_stmt)
        await conn.execute(text(upgrade_stmt))


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
