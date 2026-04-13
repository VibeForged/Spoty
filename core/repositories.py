"""Repository pattern for database operations. Cogs use these, never SQLAlchemy directly."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import delete, select, update

from core.database import get_session
from core.filters import (
    build_ffmpeg_filter_string,
    deserialize_preset_definition,
    legacy_filter_string_to_definition,
    normalize_preset_definition,
    serialize_preset_definition,
)
from core.models import (
    FXPreset,
    GuildSettings,
    History,
    Playlist,
    PlaylistTrack,
    PlaylistVote,
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
                .values(**kwargs, updated_at=datetime.utcnow())
            )

    @staticmethod
    async def delete(guild_id: int) -> None:
        """Delete settings for a guild."""
        async with get_session() as session:
            await session.execute(
                delete(GuildSettings).where(GuildSettings.guild_id == guild_id)
            )


class PlaylistRepo:
    """Repository for playlist CRUD."""

    @staticmethod
    async def create(guild_id: int, owner_id: int, name: str) -> Playlist:
        """Create a new playlist."""
        async with get_session() as session:
            playlist = Playlist(guild_id=guild_id, owner_id=owner_id, name=name)
            session.add(playlist)
            await session.flush()
            return playlist

    @staticmethod
    async def get_by_name(guild_id: int, owner_id: int, name: str) -> Playlist | None:
        """Get a playlist by name for a specific user in a guild."""
        async with get_session() as session:
            result = await session.execute(
                select(Playlist).where(
                    Playlist.guild_id == guild_id,
                    Playlist.owner_id == owner_id,
                    Playlist.name == name,
                )
            )
            return result.scalar_one_or_none()

    @staticmethod
    async def get_by_share_code(share_code: str) -> Playlist | None:
        """Get a playlist by its share code."""
        async with get_session() as session:
            result = await session.execute(
                select(Playlist).where(Playlist.share_code == share_code)
            )
            return result.scalar_one_or_none()

    @staticmethod
    async def list_for_user(guild_id: int, owner_id: int) -> list[Playlist]:
        """List all playlists for a user in a guild."""
        async with get_session() as session:
            result = await session.execute(
                select(Playlist)
                .where(Playlist.guild_id == guild_id, Playlist.owner_id == owner_id)
                .order_by(Playlist.name)
            )
            return list(result.scalars().all())

    @staticmethod
    async def delete_playlist(playlist_id: int) -> None:
        """Delete a playlist and its tracks (cascade)."""
        async with get_session() as session:
            await session.execute(delete(Playlist).where(Playlist.id == playlist_id))

    @staticmethod
    async def update_share_code(playlist_id: int, share_code: str) -> None:
        """Set the share code for a playlist."""
        async with get_session() as session:
            await session.execute(
                update(Playlist)
                .where(Playlist.id == playlist_id)
                .values(share_code=share_code)
            )

    @staticmethod
    async def rename(playlist_id: int, new_name: str) -> None:
        """Rename a playlist."""
        async with get_session() as session:
            await session.execute(
                update(Playlist).where(Playlist.id == playlist_id).values(name=new_name)
            )


class PlaylistTrackRepo:
    """Repository for playlist track operations."""

    @staticmethod
    async def add_track(
        playlist_id: int, title: str, url: str, duration: int | None, added_by: int
    ) -> PlaylistTrack:
        """Add a track to the end of a playlist."""
        async with get_session() as session:
            # Get the next position
            result = await session.execute(
                select(PlaylistTrack.position)
                .where(PlaylistTrack.playlist_id == playlist_id)
                .order_by(PlaylistTrack.position.desc())
                .limit(1)
            )
            last_pos = result.scalar_one_or_none()
            next_pos = (last_pos or 0) + 1

            track = PlaylistTrack(
                playlist_id=playlist_id,
                position=next_pos,
                title=title,
                url=url,
                duration=duration,
                added_by=added_by,
            )
            session.add(track)
            await session.flush()
            return track

    @staticmethod
    async def get_tracks(playlist_id: int) -> list[PlaylistTrack]:
        """Get all tracks in a playlist, ordered by position."""
        async with get_session() as session:
            result = await session.execute(
                select(PlaylistTrack)
                .where(PlaylistTrack.playlist_id == playlist_id)
                .order_by(PlaylistTrack.position)
            )
            return list(result.scalars().all())

    @staticmethod
    async def remove_track(playlist_id: int, position: int) -> bool:
        """Remove a track at a given position. Returns True if removed."""
        async with get_session() as session:
            result = await session.execute(
                delete(PlaylistTrack).where(
                    PlaylistTrack.playlist_id == playlist_id,
                    PlaylistTrack.position == position,
                )
            )
            return result.rowcount > 0

    @staticmethod
    async def count(playlist_id: int) -> int:
        """Count tracks in a playlist."""
        async with get_session() as session:
            from sqlalchemy import func

            result = await session.execute(
                select(func.count()).where(PlaylistTrack.playlist_id == playlist_id)
            )
            return result.scalar_one()


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
