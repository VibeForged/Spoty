"""Business logic for persistent playlists."""

from __future__ import annotations

import random
import secrets
import string
from collections.abc import Iterable
from dataclasses import dataclass
from math import ceil

from loguru import logger
from sqlalchemy.exc import IntegrityError

from core.database import get_session
from core.errors import (
    InvalidPlaylistNameError,
    InvalidPlaylistPositionError,
    PlaylistAccessDeniedError,
    PlaylistAlreadyExistsError,
    PlaylistLimitExceededError,
    PlaylistNotFoundError,
)
from core.models import Playlist, PlaylistItem
from core.playlists.repository import (
    PlaylistItemRepository,
    PlaylistRepository,
    PlaylistVoteRepository,
)
from core.track import Track
from core.validation import validate_name

ALLOWED_SOURCES = {"youtube", "spotify", "soundcloud", "bandcamp", "direct", "unknown"}
MAX_PLAYLIST_ITEMS = 500
MAX_IMPORT_ITEMS = 200
VIEW_PAGE_SIZE = 10
SHARE_CODE_LENGTH = 8


@dataclass(frozen=True)
class PlaylistItemInput:
    """Validated input for a stored playlist item."""

    title: str
    url: str
    duration: int | None
    source: str
    thumbnail: str | None = None
    external_id: str | None = None


@dataclass(frozen=True)
class PlaylistDetail:
    """Playlist page plus vote counts."""

    playlist: Playlist
    items: list[PlaylistItem]
    vote_counts: dict[int, tuple[int, int]]
    page: int
    total_pages: int


@dataclass(frozen=True)
class PlaylistInfo:
    """Playlist metadata used by info displays."""

    playlist: Playlist
    total_duration: int


class PlaylistService:
    """High-level playlist operations used by cogs and tests."""

    @staticmethod
    def normalize_name(name: str) -> tuple[str, str]:
        try:
            name = validate_name(name, max_length=100, label="Playlist name")
        except ValueError as exc:
            raise InvalidPlaylistNameError(str(exc)) from exc
        normalized = "_".join(name.split())
        if not normalized:
            raise InvalidPlaylistNameError()
        return normalized, normalized.casefold()

    @staticmethod
    def item_from_track(track: Track) -> PlaylistItemInput:
        return PlaylistService.item_from_mapping(
            {
                "title": track.title,
                "url": track.url,
                "duration": track.duration,
                "source": track.source,
                "thumbnail": track.thumbnail,
            }
        )

    @staticmethod
    def item_from_mapping(data: dict) -> PlaylistItemInput:
        title = str(data.get("title") or "").strip()
        url = str(data.get("url") or "").strip()
        if not title:
            raise InvalidPlaylistNameError("Track title is required.")
        if not url:
            raise InvalidPlaylistNameError("Track URL is required.")
        if len(title) > 300:
            title = title[:300]
        if len(url) > 1000:
            raise InvalidPlaylistNameError("Track URL must be 1000 characters or fewer.")

        duration = data.get("duration")
        if duration is not None:
            duration = int(duration)
            if duration < 0:
                raise InvalidPlaylistNameError("Track duration cannot be negative.")

        source = str(data.get("source") or "unknown").lower()
        if source not in ALLOWED_SOURCES:
            source = "unknown"

        thumbnail = data.get("thumbnail")
        if thumbnail is not None:
            thumbnail = str(thumbnail).strip()[:1000] or None

        external_id = data.get("external_id")
        if external_id is not None:
            external_id = str(external_id).strip()[:200] or None

        return PlaylistItemInput(
            title=title,
            url=url,
            duration=duration,
            source=source,
            thumbnail=thumbnail,
            external_id=external_id,
        )

    @staticmethod
    async def create_playlist(guild_id: int, owner_id: int, name: str) -> Playlist:
        name, name_key = PlaylistService.normalize_name(name)
        async with get_session() as session:
            existing = await PlaylistRepository.get_owned_by_name(
                session, guild_id, owner_id, name_key
            )
            if existing:
                raise PlaylistAlreadyExistsError(name)
            try:
                return await PlaylistRepository.create(session, guild_id, owner_id, name, name_key)
            except IntegrityError as exc:
                logger.warning("Playlist create integrity failure: {}", exc)
                raise PlaylistAlreadyExistsError(name) from exc

    @staticmethod
    async def delete_playlist(guild_id: int, owner_id: int, name: str) -> None:
        async with get_session() as session:
            playlist = await PlaylistService._get_owned_playlist(session, guild_id, owner_id, name)
            await PlaylistRepository.delete(session, playlist.id)

    @staticmethod
    async def rename_playlist(guild_id: int, owner_id: int, old_name: str, new_name: str) -> str:
        new_name, new_key = PlaylistService.normalize_name(new_name)
        async with get_session() as session:
            playlist = await PlaylistService._get_owned_playlist(
                session, guild_id, owner_id, old_name
            )
            existing = await PlaylistRepository.get_owned_by_name(
                session, guild_id, owner_id, new_key
            )
            if existing and existing.id != playlist.id:
                raise PlaylistAlreadyExistsError(new_name)
            try:
                await PlaylistRepository.rename(session, playlist.id, new_name, new_key)
            except IntegrityError as exc:
                logger.warning("Playlist rename integrity failure: {}", exc)
                raise PlaylistAlreadyExistsError(new_name) from exc
        return new_name

    @staticmethod
    async def list_user_playlists(guild_id: int, owner_id: int) -> list[Playlist]:
        async with get_session() as session:
            return await PlaylistRepository.list_for_user(session, guild_id, owner_id)

    @staticmethod
    async def get_playlist_detail(
        guild_id: int,
        owner_id: int,
        name: str,
        *,
        page: int = 1,
        per_page: int = VIEW_PAGE_SIZE,
    ) -> PlaylistDetail:
        async with get_session() as session:
            playlist = await PlaylistService._get_owned_playlist(session, guild_id, owner_id, name)
            total_pages = max(1, ceil(playlist.track_count / per_page))
            page = max(1, min(page, total_pages))
            items = await PlaylistItemRepository.list_items(
                session,
                playlist.id,
                offset=(page - 1) * per_page,
                limit=per_page,
            )
            vote_counts = await PlaylistVoteRepository.get_vote_counts(
                session, [item.id for item in items]
            )
            return PlaylistDetail(playlist, items, vote_counts, page, total_pages)

    @staticmethod
    async def get_playlist_info(guild_id: int, owner_id: int, name: str) -> PlaylistInfo:
        async with get_session() as session:
            playlist = await PlaylistService._get_owned_playlist(session, guild_id, owner_id, name)
            total_duration = await PlaylistItemRepository.total_duration(session, playlist.id)
            return PlaylistInfo(playlist, total_duration)

    @staticmethod
    async def add_item(guild_id: int, owner_id: int, name: str, item: PlaylistItemInput) -> int:
        async with get_session() as session:
            playlist = await PlaylistService._get_owned_playlist(session, guild_id, owner_id, name)
            if playlist.track_count >= MAX_PLAYLIST_ITEMS:
                raise PlaylistLimitExceededError(MAX_PLAYLIST_ITEMS)

            position = await PlaylistItemRepository.max_position(session, playlist.id) + 1
            await PlaylistItemRepository.add_item(
                session,
                playlist.id,
                position,
                item.title,
                item.url,
                item.duration,
                owner_id,
                source=item.source,
                external_id=item.external_id,
                thumbnail=item.thumbnail,
            )
            await PlaylistRepository.increment_track_count(session, playlist.id, 1)
            return position

    @staticmethod
    async def remove_item(guild_id: int, owner_id: int, name: str, position: int) -> None:
        if position < 1:
            raise InvalidPlaylistPositionError(position)

        async with get_session() as session:
            playlist = await PlaylistService._get_owned_playlist(session, guild_id, owner_id, name)
            removed = await PlaylistItemRepository.remove_at_position(
                session, playlist.id, position
            )
            if not removed:
                raise InvalidPlaylistPositionError(position)
            await PlaylistRepository.increment_track_count(session, playlist.id, -1)

    @staticmethod
    async def shuffle_items(guild_id: int, owner_id: int, name: str) -> int:
        async with get_session() as session:
            playlist = await PlaylistService._get_owned_playlist(session, guild_id, owner_id, name)
            item_ids = await PlaylistItemRepository.list_ids(session, playlist.id)
            if not item_ids:
                return 0
            random.shuffle(item_ids)
            await PlaylistService._reorder_items(session, playlist.id, item_ids)
            return len(item_ids)

    @staticmethod
    async def copy_playlist(
        guild_id: int,
        owner_id: int,
        source: str,
        new_name: str,
    ) -> Playlist:
        async with get_session() as session:
            src_playlist = await PlaylistService._get_copy_source(
                session, guild_id, owner_id, source
            )
            target_name = await PlaylistService._available_name(session, guild_id, owner_id, new_name)
            target_key = target_name.casefold()
            new_playlist = await PlaylistRepository.create(
                session, guild_id, owner_id, target_name, target_key
            )
            src_items = await PlaylistItemRepository.list_items(session, src_playlist.id)
            added = await PlaylistService._bulk_insert_items(
                session, new_playlist.id, owner_id, [PlaylistService._input_from_item(i) for i in src_items]
            )
            new_playlist.track_count = added
            return new_playlist

    @staticmethod
    async def import_items(
        guild_id: int,
        owner_id: int,
        name: str,
        items: Iterable[PlaylistItemInput | dict],
    ) -> Playlist:
        item_inputs = [
            item if isinstance(item, PlaylistItemInput) else PlaylistService.item_from_mapping(item)
            for item in list(items)[:MAX_IMPORT_ITEMS]
        ]
        target_name, _ = PlaylistService.normalize_name(name)
        async with get_session() as session:
            target_name = await PlaylistService._available_name(
                session, guild_id, owner_id, target_name
            )
            playlist = await PlaylistRepository.create(
                session, guild_id, owner_id, target_name, target_name.casefold()
            )
            added = await PlaylistService._bulk_insert_items(session, playlist.id, owner_id, item_inputs)
            playlist.track_count = added
            return playlist

    @staticmethod
    async def import_share_code(guild_id: int, owner_id: int, share_code: str) -> Playlist:
        async with get_session() as session:
            source = await PlaylistRepository.get_by_share_code(session, share_code)
            if source is None:
                raise PlaylistNotFoundError(share_code)
            name = await PlaylistService._available_name(
                session, guild_id, owner_id, f"{source.name}_imported"
            )
            playlist = await PlaylistRepository.create(
                session, guild_id, owner_id, name, name.casefold()
            )
            items = await PlaylistItemRepository.list_items(session, source.id, limit=MAX_IMPORT_ITEMS)
            added = await PlaylistService._bulk_insert_items(
                session, playlist.id, owner_id, [PlaylistService._input_from_item(i) for i in items]
            )
            playlist.track_count = added
            return playlist

    @staticmethod
    async def generate_share_code(guild_id: int, owner_id: int, name: str) -> str:
        alphabet = string.ascii_letters + string.digits
        async with get_session() as session:
            playlist = await PlaylistService._get_owned_playlist(session, guild_id, owner_id, name)
            if playlist.share_code:
                return playlist.share_code

            for _ in range(10):
                code = "".join(secrets.choice(alphabet) for _ in range(SHARE_CODE_LENGTH))
                if await PlaylistRepository.share_code_exists(session, code):
                    continue
                await PlaylistRepository.set_share_code(session, playlist.id, code)
                return code

        raise PlaylistAccessDeniedError()

    @staticmethod
    async def vote_item(
        guild_id: int,
        owner_id: int,
        name: str,
        position: int,
        user_id: int,
        vote: int,
    ) -> tuple[PlaylistItem, tuple[int, int]]:
        if vote not in (1, -1):
            raise InvalidPlaylistPositionError(position)
        if position < 1:
            raise InvalidPlaylistPositionError(position)

        async with get_session() as session:
            playlist = await PlaylistService._get_owned_playlist(session, guild_id, owner_id, name)
            item = await PlaylistItemRepository.get_at_position(session, playlist.id, position)
            if item is None:
                raise InvalidPlaylistPositionError(position)
            await PlaylistVoteRepository.upsert_vote(session, item.id, user_id, vote)
            counts = await PlaylistVoteRepository.get_vote_counts(session, [item.id])
            return item, counts.get(item.id, (0, 0))

    @staticmethod
    async def tracks_for_play(guild_id: int, owner_id: int, name: str) -> list[Track]:
        async with get_session() as session:
            playlist = await PlaylistService._get_owned_playlist(session, guild_id, owner_id, name)
            items = await PlaylistItemRepository.list_items(session, playlist.id)
            return [
                Track(
                    title=item.title,
                    url=item.url,
                    duration=item.duration,
                    requester_id=owner_id,
                    source=item.source,
                    thumbnail=item.thumbnail,
                    lazy_query=item.external_id if item.source == "spotify" and item.external_id else None
                )
                for item in items
            ]

    @staticmethod
    async def _get_owned_playlist(session, guild_id: int, owner_id: int, name: str) -> Playlist:
        if name.isdigit():
            idx = int(name) - 1
            if idx >= 0:
                playlists = await PlaylistRepository.list_for_user(session, guild_id, owner_id)
                if idx < len(playlists):
                    name = playlists[idx].name

        _, name_key = PlaylistService.normalize_name(name)
        playlist = await PlaylistRepository.get_owned_by_name(session, guild_id, owner_id, name_key)
        if playlist is None:
            raise PlaylistNotFoundError(name)
        return playlist

    @staticmethod
    async def _get_copy_source(session, guild_id: int, owner_id: int, source: str) -> Playlist:
        if source.isdigit():
            idx = int(source) - 1
            if idx >= 0:
                playlists = await PlaylistRepository.list_for_user(session, guild_id, owner_id)
                if idx < len(playlists):
                    source = playlists[idx].name

        try:
            _, name_key = PlaylistService.normalize_name(source)
        except InvalidPlaylistNameError:
            name_key = ""

        playlist = None
        if name_key:
            playlist = await PlaylistRepository.get_owned_by_name(
                session, guild_id, owner_id, name_key
            )
        if playlist is None and len(source) == SHARE_CODE_LENGTH and source.isalnum():
            playlist = await PlaylistRepository.get_by_share_code(session, source)
        if playlist is None:
            raise PlaylistNotFoundError(source)
        return playlist

    @staticmethod
    async def _available_name(session, guild_id: int, owner_id: int, base_name: str) -> str:
        base_name, base_key = PlaylistService.normalize_name(base_name)
        if await PlaylistRepository.get_owned_by_name(session, guild_id, owner_id, base_key) is None:
            return base_name

        for suffix in range(2, 1000):
            suffix_text = f"_{suffix}"
            trimmed = base_name[: 100 - len(suffix_text)]
            candidate = f"{trimmed}{suffix_text}"
            if await PlaylistRepository.get_owned_by_name(
                session, guild_id, owner_id, candidate.casefold()
            ) is None:
                return candidate
        raise PlaylistAlreadyExistsError(base_name)

    @staticmethod
    async def _bulk_insert_items(
        session,
        playlist_id: int,
        owner_id: int,
        items: list[PlaylistItemInput],
    ) -> int:
        if len(items) > MAX_PLAYLIST_ITEMS:
            raise PlaylistLimitExceededError(MAX_PLAYLIST_ITEMS)

        position = await PlaylistItemRepository.max_position(session, playlist_id)
        remaining = MAX_PLAYLIST_ITEMS - position
        if len(items) > remaining:
            raise PlaylistLimitExceededError(MAX_PLAYLIST_ITEMS)

        for item in items:
            position += 1
            await PlaylistItemRepository.add_item(
                session,
                playlist_id,
                position,
                item.title,
                item.url,
                item.duration,
                owner_id,
                source=item.source,
                external_id=item.external_id,
                thumbnail=item.thumbnail,
            )
        if items:
            await PlaylistRepository.increment_track_count(session, playlist_id, len(items))
        return len(items)

    @staticmethod
    async def _reorder_items(session, playlist_id: int, item_ids: list[int]) -> None:
        current_ids = await PlaylistItemRepository.list_ids(session, playlist_id)
        if set(current_ids) != set(item_ids) or len(current_ids) != len(item_ids):
            raise PlaylistAccessDeniedError()
        await PlaylistItemRepository.reorder(session, playlist_id, item_ids)

    @staticmethod
    def _input_from_item(item: PlaylistItem) -> PlaylistItemInput:
        return PlaylistItemInput(
            title=item.title,
            url=item.url,
            duration=item.duration,
            source=item.source,
            thumbnail=item.thumbnail,
            external_id=item.external_id,
        )
