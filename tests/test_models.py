"""Tests for ORM model relationships and constraints."""

from __future__ import annotations

import pytest

from core.database import get_session


@pytest.mark.asyncio
class TestModelRelationships:
    async def test_playlist_items_cascade_delete(self, db):
        """Deleting a playlist should cascade delete items and votes on SQLite."""
        from sqlalchemy import func, select

        from core.models import PlaylistItem, PlaylistItemVote
        from core.playlists.service import PlaylistService

        playlist = await PlaylistService.create_playlist(1, 100, "Cascade Test")
        await PlaylistService.add_item(
            1,
            100,
            playlist.name,
            PlaylistService.item_from_mapping(
                {"title": "Song", "url": "http://url", "duration": 200}
            ),
        )
        await PlaylistService.vote_item(1, 100, playlist.name, 1, 200, 1)
        await PlaylistService.delete_playlist(1, 100, playlist.name)

        async with get_session() as session:
            item_count = (
                await session.execute(select(func.count()).select_from(PlaylistItem))
            ).scalar_one()
            vote_count = (
                await session.execute(select(func.count()).select_from(PlaylistItemVote))
            ).scalar_one()

        assert item_count == 0
        assert vote_count == 0

    async def test_unique_playlist_name_key_per_user_guild(self, db):
        """Playlist names are unique per user+guild case-insensitively."""
        from core.errors import PlaylistAlreadyExistsError
        from core.playlists.service import PlaylistService

        await PlaylistService.create_playlist(1, 100, "Unique")
        with pytest.raises(PlaylistAlreadyExistsError):
            await PlaylistService.create_playlist(1, 100, " unique ")

    async def test_playlist_name_spaces_become_underscores(self, db):
        """Playlist names are stored in a prefix-command-friendly form."""
        from core.playlists.service import PlaylistService

        playlist = await PlaylistService.create_playlist(1, 100, "My Cool Mix")

        assert playlist.name == "My_Cool_Mix"
        assert playlist.name_key == "my_cool_mix"

    async def test_different_users_same_playlist_name(self, db):
        """Different users in the same guild can use the same playlist name."""
        from core.playlists.service import PlaylistService

        await PlaylistService.create_playlist(1, 100, "Shared Name")
        playlist = await PlaylistService.create_playlist(1, 200, "Shared Name")

        assert playlist is not None
