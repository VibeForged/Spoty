"""Tests for ORM model relationships and constraints."""

from __future__ import annotations

import pytest

from core.database import get_session


@pytest.mark.asyncio
class TestModelRelationships:
    async def test_playlist_tracks_cascade_delete(self, db):
        """Deleting a playlist via ORM should cascade delete its tracks."""
        from sqlalchemy import select

        from core.models import Playlist, PlaylistTrack
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        pl = await PlaylistRepo.create(1, 100, "Cascade Test")
        await PlaylistTrackRepo.add_track(pl.id, "Song", "http://url", 200, 100)

        # Use ORM-level delete (load then delete) so cascade is triggered
        async with get_session() as session:
            result = await session.execute(select(Playlist).where(Playlist.id == pl.id))
            playlist = result.scalar_one()
            await session.delete(playlist)

        tracks = await PlaylistTrackRepo.get_tracks(pl.id)
        assert len(tracks) == 0

    async def test_playlist_vote_cascade_delete(self, db):
        """Deleting a playlist track should cascade delete its votes."""
        from core.repositories import PlaylistRepo, PlaylistTrackRepo, PlaylistVoteRepo

        pl = await PlaylistRepo.create(1, 100, "Vote Cascade")
        await PlaylistTrackRepo.add_track(pl.id, "Song", "http://url", 200, 100)
        track = await PlaylistTrackRepo.get_track_at_position(pl.id, 1)
        await PlaylistVoteRepo.upsert_vote(track.id, 200, 1)
        await PlaylistTrackRepo.remove_track(pl.id, 1)
        likes, dislikes = await PlaylistVoteRepo.get_votes(track.id)
        assert likes == 0 and dislikes == 0

    async def test_unique_playlist_name_per_user_guild(self, db):
        """Same user+guild can't have duplicate playlist names."""
        from core.repositories import PlaylistRepo

        await PlaylistRepo.create(1, 100, "Unique")
        with pytest.raises(Exception):
            await PlaylistRepo.create(1, 100, "Unique")

    async def test_different_users_same_playlist_name(self, db):
        """Different users in same guild can have same playlist name."""
        from core.repositories import PlaylistRepo

        await PlaylistRepo.create(1, 100, "Shared Name")
        pl2 = await PlaylistRepo.create(1, 200, "Shared Name")
        assert pl2 is not None
