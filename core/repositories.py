"""Repository pattern for database operations. Cogs use these, never SQLAlchemy directly."""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any


from loguru import logger
from sqlalchemy import delete, select, update
from sqlalchemy import func as sa_func

from core.database import get_session
from core.filters import (
    build_ffmpeg_filter_string,
    deserialize_preset_definition,
    legacy_filter_string_to_definition,
    normalize_preset_definition,
    serialize_preset_definition,
)
from core.models import (
    AutoDJFeedback,
    FXPreset,
    GuildSettings,
    History,
    Permission,
    Stats,
)


class GuildSettingsRepo:
    """Repository for guild settings CRUD."""

    @staticmethod
    async def get(guild_id: int) -> GuildSettings | None:
        """Get settings for a guild."""
        async with get_session() as session:
            result = await session.execute(
                select(GuildSettings).where(GuildSettings.guild_id == guild_id)
            )
            return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create(guild_id: int) -> GuildSettings:
        """Get settings for a guild, creating defaults if not found."""
        async with get_session() as session:
            result = await session.execute(
                select(GuildSettings).where(GuildSettings.guild_id == guild_id)
            )
            settings = result.scalar_one_or_none()
            if settings is None:
                settings = GuildSettings(guild_id=guild_id)
                session.add(settings)
                await session.flush()
                logger.debug("Created default settings for guild {}", guild_id)
            return settings

    @staticmethod
    async def update(guild_id: int, **kwargs) -> None:
        """Update specific settings fields for a guild."""
        async with get_session() as session:
            await session.execute(
                update(GuildSettings)
                .where(GuildSettings.guild_id == guild_id)
                .values(**kwargs, updated_at=datetime.now(UTC))
            )

    @staticmethod
    async def delete(guild_id: int) -> None:
        """Delete settings for a guild."""
        async with get_session() as session:
            await session.execute(
                delete(GuildSettings).where(GuildSettings.guild_id == guild_id)
            )


class HistoryRepo:
    """Repository for play history."""

    @staticmethod
    async def add(
        guild_id: int,
        track_title: str,
        track_url: str,
        duration: int | None,
        requested_by: int,
    ) -> None:
        """Record a played track in history."""
        async with get_session() as session:
            entry = History(
                guild_id=guild_id,
                track_title=track_title,
                track_url=track_url,
                duration=duration,
                requested_by=requested_by,
            )
            session.add(entry)

    @staticmethod
    async def get_recent(guild_id: int, limit: int = 25) -> list[History]:
        """Get recent play history for a guild."""
        async with get_session() as session:
            result = await session.execute(
                select(History)
                .where(History.guild_id == guild_id)
                .order_by(History.played_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_top_tracks(
        guild_id: int,
        limit: int = 30,
        exclude_recent: int = 100,
    ) -> list[dict[str, Any]]:
        """Get most-played tracks for a guild, excluding recently played ones.

        Used by Auto-DJ HistorySource for guild-aware recommendations.

        Returns:
            List of dicts with keys: track_title, track_url, duration, play_count.
        """
        async with get_session() as session:
            # Subquery: get URLs of the N most recently played tracks
            recent_sub = (
                select(History.track_url)
                .where(History.guild_id == guild_id)
                .order_by(History.played_at.desc())
                .limit(exclude_recent)
                .subquery()
            )

            # Main query: aggregate play counts, excluding recent
            stmt = (
                select(
                    History.track_title,
                    History.track_url,
                    History.duration,
                    sa_func.count(History.id).label("play_count"),
                )
                .where(
                    History.guild_id == guild_id,
                    History.track_url.notin_(select(recent_sub.c.track_url)),
                )
                .group_by(History.track_title, History.track_url, History.duration)
                .order_by(sa_func.count(History.id).desc())
                .limit(limit)
            )

            result = await session.execute(stmt)
            return [
                {
                    "track_title": row.track_title,
                    "track_url": row.track_url,
                    "duration": row.duration,
                    "play_count": row.play_count,
                }
                for row in result.all()
            ]

    @staticmethod
    async def get_recent_urls(guild_id: int, limit: int = 200) -> set[str]:
        """Get the set of recently played track URLs for deduplication.

        Used by Auto-DJ engine to avoid recommending recently played tracks.
        """
        async with get_session() as session:
            result = await session.execute(
                select(History.track_url)
                .where(History.guild_id == guild_id)
                .order_by(History.played_at.desc())
                .limit(limit)
            )
            return {row[0] for row in result.all()}


class FXPresetRepo:
    """Repository for custom FX presets."""

    @staticmethod
    async def create(
        guild_id: int,
        name: str,
        preset_definition: dict[str, Any],
        created_by: int,
        *,
        is_compatible: bool = True,
    ) -> FXPreset:
        """Create a new custom FX preset."""
        async with get_session() as session:
            normalized = normalize_preset_definition(preset_definition)
            preset = FXPreset(
                guild_id=guild_id,
                name=name,
                filter_string=build_ffmpeg_filter_string(normalized) or "",
                preset_data=serialize_preset_definition(normalized),
                is_compatible=is_compatible,
                created_by=created_by,
            )
            session.add(preset)
            await session.flush()
            return preset

    @staticmethod
    async def get_by_name(guild_id: int, name: str) -> FXPreset | None:
        """Get a custom preset by name."""
        async with get_session() as session:
            result = await session.execute(
                select(FXPreset).where(
                    FXPreset.guild_id == guild_id, FXPreset.name == name
                )
            )
            preset = result.scalar_one_or_none()
            if preset:
                await FXPresetRepo._migrate_loaded_preset(session, preset)
            return preset

    @staticmethod
    async def list_for_guild(guild_id: int) -> list[FXPreset]:
        """List all custom presets for a guild."""
        async with get_session() as session:
            result = await session.execute(
                select(FXPreset)
                .where(FXPreset.guild_id == guild_id)
                .order_by(FXPreset.name)
            )
            presets = list(result.scalars().all())
            for preset in presets:
                await FXPresetRepo._migrate_loaded_preset(session, preset)
            return presets

    @staticmethod
    async def delete_preset(guild_id: int, name: str) -> bool:
        """Delete a custom preset. Returns True if deleted."""
        async with get_session() as session:
            result = await session.execute(
                delete(FXPreset).where(
                    FXPreset.guild_id == guild_id, FXPreset.name == name
                )
            )
            return result.rowcount > 0

    @staticmethod
    async def rename(guild_id: int, old_name: str, new_name: str) -> bool:
        """Rename a custom preset."""
        async with get_session() as session:
            result = await session.execute(
                update(FXPreset)
                .where(FXPreset.guild_id == guild_id, FXPreset.name == old_name)
                .values(name=new_name)
            )
            return result.rowcount > 0

    @staticmethod
    async def _migrate_loaded_preset(session, preset: FXPreset) -> None:
        """Backfill structured preset data for legacy rows."""
        if preset.preset_data:
            return

        definition = legacy_filter_string_to_definition(preset.filter_string)
        if definition is None:
            return

        normalized = normalize_preset_definition(definition)
        preset.preset_data = serialize_preset_definition(normalized)
        preset.is_compatible = True
        if not preset.filter_string:
            preset.filter_string = build_ffmpeg_filter_string(normalized) or ""
        await session.flush()

    @staticmethod
    def get_definition(preset: FXPreset) -> dict[str, Any] | None:
        """Return the structured definition for a preset model."""
        definition = deserialize_preset_definition(preset.preset_data)
        if definition is not None:
            return definition
        return legacy_filter_string_to_definition(preset.filter_string)


class StatsRepo:
    """Repository for guild statistics."""

    @staticmethod
    async def increment(guild_id: int, duration: int = 0) -> None:
        """Increment play count and duration for a guild."""
        async with get_session() as session:
            result = await session.execute(
                select(Stats).where(Stats.guild_id == guild_id)
            )
            stats = result.scalar_one_or_none()
            if stats is None:
                stats = Stats(
                    guild_id=guild_id,
                    total_plays=1,
                    total_seconds_played=duration,
                )
                session.add(stats)
            else:
                stats.total_plays += 1
                stats.total_seconds_played += duration

    @staticmethod
    async def get(guild_id: int) -> Stats | None:
        """Get stats for a guild."""
        async with get_session() as session:
            result = await session.execute(
                select(Stats).where(Stats.guild_id == guild_id)
            )
            return result.scalar_one_or_none()


class PermissionRepo:
    """Repository for per-guild command permission overrides."""

    @staticmethod
    async def get_overrides(guild_id: int) -> list[Permission]:
        """Get all permission overrides for a guild."""
        async with get_session() as session:
            result = await session.execute(
                select(Permission)
                .where(Permission.guild_id == guild_id)
                .order_by(Permission.command_name)
            )
            return list(result.scalars().all())

    @staticmethod
    async def get_for_command(guild_id: int, command_name: str) -> list[Permission]:
        """Get all permission overrides for a specific command in a guild."""
        async with get_session() as session:
            result = await session.execute(
                select(Permission).where(
                    Permission.guild_id == guild_id,
                    Permission.command_name == command_name,
                )
            )
            return list(result.scalars().all())

    @staticmethod
    async def set_override(
        guild_id: int, command_name: str, role_id: int, allowed: bool
    ) -> None:
        """Upsert a permission override for a command and role."""
        async with get_session() as session:
            result = await session.execute(
                select(Permission).where(
                    Permission.guild_id == guild_id,
                    Permission.command_name == command_name,
                    Permission.role_id == role_id,
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.allowed = allowed
            else:
                session.add(
                    Permission(
                        guild_id=guild_id,
                        command_name=command_name,
                        role_id=role_id,
                        allowed=allowed,
                    )
                )

    @staticmethod
    async def remove_override(guild_id: int, command_name: str, role_id: int) -> bool:
        """Remove a specific permission override. Returns True if deleted."""
        async with get_session() as session:
            result = await session.execute(
                delete(Permission).where(
                    Permission.guild_id == guild_id,
                    Permission.command_name == command_name,
                    Permission.role_id == role_id,
                )
            )
            return result.rowcount > 0

    @staticmethod
    async def reset_command(guild_id: int, command_name: str) -> int:
        """Delete all overrides for a command. Returns count deleted."""
        async with get_session() as session:
            result = await session.execute(
                delete(Permission).where(
                    Permission.guild_id == guild_id,
                    Permission.command_name == command_name,
                )
            )
            return result.rowcount

    @staticmethod
    async def reset_all(guild_id: int) -> int:
        """Delete all permission overrides for a guild. Returns count deleted."""
        async with get_session() as session:
            result = await session.execute(
                delete(Permission).where(Permission.guild_id == guild_id)
            )
            return result.rowcount


class AutoDJFeedbackRepo:
    """Repository for Auto-DJ learning signals."""

    @staticmethod
    async def add_signal(
        guild_id: int,
        track_url: str,
        signal: str,
        source: str,
        artist_hint: str | None = None,
    ) -> None:
        """Record a user signal (skip/complete) for a recommendation."""
        async with get_session() as session:
            entry = AutoDJFeedback(
                guild_id=guild_id,
                track_url=track_url,
                artist_hint=artist_hint,
                signal=signal,
                source=source,
            )
            session.add(entry)

    @staticmethod
    async def get_signals_for_session(
        guild_id: int, limit: int = 500
    ) -> list[AutoDJFeedback]:
        """Get recent feedback signals for a guild's scoring context."""
        async with get_session() as session:
            result = await session.execute(
                select(AutoDJFeedback)
                .where(AutoDJFeedback.guild_id == guild_id)
                .order_by(AutoDJFeedback.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())
