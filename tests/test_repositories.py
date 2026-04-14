"""Tests for repository CRUD operations."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
class TestGuildSettingsRepo:
    async def test_get_or_create(self, db):
        from core.repositories import GuildSettingsRepo

        settings = await GuildSettingsRepo.get_or_create(123456)
        assert settings is not None
        assert settings.guild_id == 123456
        assert settings.prefix == "!"

    async def test_update(self, db):
        from core.repositories import GuildSettingsRepo

        await GuildSettingsRepo.get_or_create(123456)
        await GuildSettingsRepo.update(123456, prefix="?", default_volume=75)
        settings = await GuildSettingsRepo.get(123456)
        assert settings.prefix == "?"
        assert settings.default_volume == 75

    async def test_delete(self, db):
        from core.repositories import GuildSettingsRepo

        await GuildSettingsRepo.get_or_create(123456)
        await GuildSettingsRepo.delete(123456)
        settings = await GuildSettingsRepo.get(123456)
        assert settings is None


@pytest.mark.asyncio
class TestPlaylistRepo:
    async def test_create_and_get(self, db):
        from core.repositories import PlaylistRepo

        pl = await PlaylistRepo.create(1, 100, "My Playlist")
        assert pl.name == "My Playlist"
        fetched = await PlaylistRepo.get_by_name(1, 100, "My Playlist")
        assert fetched is not None
        assert fetched.id == pl.id

    async def test_list_for_user(self, db):
        from core.repositories import PlaylistRepo

        await PlaylistRepo.create(1, 100, "Playlist A")
        await PlaylistRepo.create(1, 100, "Playlist B")
        playlists = await PlaylistRepo.list_for_user(1, 100)
        assert len(playlists) == 2

    async def test_share_code(self, db):
        from core.repositories import PlaylistRepo

        pl = await PlaylistRepo.create(1, 100, "Shared")
        await PlaylistRepo.update_share_code(pl.id, "abc12345")
        found = await PlaylistRepo.get_by_share_code("abc12345")
        assert found is not None
        assert found.id == pl.id

    async def test_rename(self, db):
        from core.repositories import PlaylistRepo

        pl = await PlaylistRepo.create(1, 100, "OldName")
        await PlaylistRepo.rename(pl.id, "NewName")
        found = await PlaylistRepo.get_by_name(1, 100, "NewName")
        assert found is not None

    async def test_delete_playlist(self, db):
        from core.repositories import PlaylistRepo

        pl = await PlaylistRepo.create(1, 100, "ToDelete")
        await PlaylistRepo.delete_playlist(pl.id)
        found = await PlaylistRepo.get_by_name(1, 100, "ToDelete")
        assert found is None


@pytest.mark.asyncio
class TestPlaylistTrackRepo:
    async def test_add_and_get_tracks(self, db):
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        pl = await PlaylistRepo.create(1, 100, "Test")
        await PlaylistTrackRepo.add_track(pl.id, "Song 1", "http://url1", 200, 100)
        await PlaylistTrackRepo.add_track(pl.id, "Song 2", "http://url2", 300, 100)
        tracks = await PlaylistTrackRepo.get_tracks(pl.id)
        assert len(tracks) == 2
        assert tracks[0].position == 1
        assert tracks[1].position == 2

    async def test_remove_track(self, db):
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        pl = await PlaylistRepo.create(1, 100, "Test")
        await PlaylistTrackRepo.add_track(pl.id, "Song 1", "http://url1", 200, 100)
        removed = await PlaylistTrackRepo.remove_track(pl.id, 1)
        assert removed is True
        assert await PlaylistTrackRepo.count(pl.id) == 0

    async def test_bulk_add_tracks(self, db):
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        pl = await PlaylistRepo.create(1, 100, "Test")
        tracks = [
            {"title": "A", "url": "http://a", "duration": 100},
            {"title": "B", "url": "http://b", "duration": 200},
            {"title": "C", "url": "http://c", "duration": 300},
        ]
        await PlaylistTrackRepo.bulk_add_tracks(pl.id, tracks, 100)
        all_tracks = await PlaylistTrackRepo.get_tracks(pl.id)
        assert len(all_tracks) == 3
        assert all_tracks[0].title == "A"
        assert all_tracks[2].position == 3

    async def test_get_track_at_position(self, db):
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        pl = await PlaylistRepo.create(1, 100, "Test")
        await PlaylistTrackRepo.add_track(pl.id, "Song 1", "http://url1", 200, 100)
        track = await PlaylistTrackRepo.get_track_at_position(pl.id, 1)
        assert track is not None
        assert track.title == "Song 1"
        none_track = await PlaylistTrackRepo.get_track_at_position(pl.id, 99)
        assert none_track is None

    async def test_reorder_tracks(self, db):
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        pl = await PlaylistRepo.create(1, 100, "Test")
        await PlaylistTrackRepo.add_track(pl.id, "A", "http://a", 100, 100)
        await PlaylistTrackRepo.add_track(pl.id, "B", "http://b", 200, 100)
        await PlaylistTrackRepo.add_track(pl.id, "C", "http://c", 300, 100)
        tracks = await PlaylistTrackRepo.get_tracks(pl.id)
        # Reverse order
        reversed_ids = [t.id for t in reversed(tracks)]
        await PlaylistTrackRepo.reorder_tracks(pl.id, reversed_ids)
        reordered = await PlaylistTrackRepo.get_tracks(pl.id)
        assert reordered[0].title == "C"
        assert reordered[1].title == "B"
        assert reordered[2].title == "A"


@pytest.mark.asyncio
class TestPlaylistVoteRepo:
    async def test_upsert_vote(self, db):
        from core.repositories import PlaylistRepo, PlaylistTrackRepo, PlaylistVoteRepo

        pl = await PlaylistRepo.create(1, 100, "Test")
        await PlaylistTrackRepo.add_track(pl.id, "Song", "http://url", 200, 100)
        track = await PlaylistTrackRepo.get_track_at_position(pl.id, 1)
        await PlaylistVoteRepo.upsert_vote(track.id, 200, 1)
        likes, dislikes = await PlaylistVoteRepo.get_votes(track.id)
        assert likes == 1
        assert dislikes == 0

    async def test_change_vote(self, db):
        from core.repositories import PlaylistRepo, PlaylistTrackRepo, PlaylistVoteRepo

        pl = await PlaylistRepo.create(1, 100, "Test")
        await PlaylistTrackRepo.add_track(pl.id, "Song", "http://url", 200, 100)
        track = await PlaylistTrackRepo.get_track_at_position(pl.id, 1)
        await PlaylistVoteRepo.upsert_vote(track.id, 200, 1)
        await PlaylistVoteRepo.upsert_vote(track.id, 200, -1)
        likes, dislikes = await PlaylistVoteRepo.get_votes(track.id)
        assert likes == 0
        assert dislikes == 1


@pytest.mark.asyncio
class TestHistoryRepo:
    async def test_add_and_get(self, db):
        from core.repositories import HistoryRepo

        await HistoryRepo.add(1, "Song 1", "http://url1", 200, 100)
        await HistoryRepo.add(1, "Song 2", "http://url2", 300, 100)
        entries = await HistoryRepo.get_recent(1, limit=10)
        assert len(entries) == 2
        # Most recent first
        assert entries[0].track_title == "Song 2"


@pytest.mark.asyncio
class TestFXPresetRepo:
    async def test_create_and_get(self, db):
        from core.repositories import FXPresetRepo

        definition = {"version": 1, "timescale": {"speed": 1.5, "pitch": 1.0, "rate": 1.0}}
        preset = await FXPresetRepo.create(1, "fast", definition, 100)
        assert preset.name == "fast"
        fetched = await FXPresetRepo.get_by_name(1, "fast")
        assert fetched is not None

    async def test_delete(self, db):
        from core.repositories import FXPresetRepo

        definition = {"version": 1, "timescale": {"speed": 1.5}}
        await FXPresetRepo.create(1, "temp", definition, 100)
        deleted = await FXPresetRepo.delete_preset(1, "temp")
        assert deleted is True

    async def test_rename(self, db):
        from core.repositories import FXPresetRepo

        definition = {"version": 1}
        await FXPresetRepo.create(1, "old", definition, 100)
        renamed = await FXPresetRepo.rename(1, "old", "new")
        assert renamed is True
        assert await FXPresetRepo.get_by_name(1, "new") is not None


@pytest.mark.asyncio
class TestStatsRepo:
    async def test_increment_and_get(self, db):
        from core.repositories import StatsRepo

        await StatsRepo.increment(1, duration=120)
        await StatsRepo.increment(1, duration=60)
        stats = await StatsRepo.get(1)
        assert stats.total_plays == 2
        assert stats.total_seconds_played == 180


@pytest.mark.asyncio
class TestPermissionRepo:
    async def test_set_and_get(self, db):
        from core.repositories import PermissionRepo

        await PermissionRepo.set_override(1, "play", 999, True)
        overrides = await PermissionRepo.get_for_command(1, "play")
        assert len(overrides) == 1
        assert overrides[0].allowed is True

    async def test_remove(self, db):
        from core.repositories import PermissionRepo

        await PermissionRepo.set_override(1, "play", 999, True)
        removed = await PermissionRepo.remove_override(1, "play", 999)
        assert removed is True
        overrides = await PermissionRepo.get_for_command(1, "play")
        assert len(overrides) == 0

    async def test_reset_command(self, db):
        from core.repositories import PermissionRepo

        await PermissionRepo.set_override(1, "play", 999, True)
        await PermissionRepo.set_override(1, "play", 888, False)
        count = await PermissionRepo.reset_command(1, "play")
        assert count == 2

    async def test_reset_all(self, db):
        from core.repositories import PermissionRepo

        await PermissionRepo.set_override(1, "play", 999, True)
        await PermissionRepo.set_override(1, "skip", 888, False)
        count = await PermissionRepo.reset_all(1)
        assert count == 2
