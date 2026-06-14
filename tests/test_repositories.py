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
class TestPlaylistReorder:
    async def test_bulk_reorder_sets_contiguous_positions(self, db):
        from core.database import get_session
        from core.playlists.repository import PlaylistItemRepository, PlaylistRepository

        async with get_session() as session:
            pl = await PlaylistRepository.create(session, 1, 100, "P", "p")
            items = [
                await PlaylistItemRepository.add_item(
                    session,
                    pl.id,
                    position=i + 1,
                    title=f"t{i}",
                    url=f"u{i}",
                    duration=None,
                    added_by=100,
                    source="youtube",
                )
                for i in range(3)
            ]
            new_order = [items[2].id, items[0].id, items[1].id]
            await PlaylistItemRepository.reorder(session, pl.id, new_order)
            await session.flush()

            ordered = await PlaylistItemRepository.list_items(session, pl.id)
            assert [it.id for it in ordered] == new_order
            assert [it.position for it in ordered] == [1, 2, 3]


@pytest.mark.asyncio
class TestPlaylistService:
    async def test_create_list_and_share_code(self, db):
        from core.playlists.service import PlaylistService

        playlist = await PlaylistService.create_playlist(1, 100, "My Playlist")
        code = await PlaylistService.generate_share_code(1, 100, playlist.name)
        playlists = await PlaylistService.list_user_playlists(1, 100)

        assert playlists[0].name == "My_Playlist"
        assert playlists[0].visibility == "private"
        assert len(code) == 8

    async def test_remove_middle_track_compacts_positions(self, db):
        from core.playlists.service import PlaylistService

        await PlaylistService.create_playlist(1, 100, "Positions")
        for title in ("A", "B", "C"):
            await PlaylistService.add_item(
                1,
                100,
                "Positions",
                PlaylistService.item_from_mapping(
                    {"title": title, "url": f"http://{title}", "duration": 100}
                ),
            )

        await PlaylistService.remove_item(1, 100, "Positions", 2)
        await PlaylistService.add_item(
            1,
            100,
            "Positions",
            PlaylistService.item_from_mapping({"title": "D", "url": "http://d", "duration": 100}),
        )
        detail = await PlaylistService.get_playlist_detail(1, 100, "Positions")

        assert [(item.title, item.position) for item in detail.items] == [
            ("A", 1),
            ("C", 2),
            ("D", 3),
        ]
        assert detail.playlist.track_count == 3

    async def test_private_playlist_requires_owner_or_share_code(self, db):
        from core.errors import PlaylistNotFoundError
        from core.playlists.service import PlaylistService

        await PlaylistService.create_playlist(1, 100, "Private")
        await PlaylistService.add_item(
            1,
            100,
            "Private",
            PlaylistService.item_from_mapping(
                {"title": "Song", "url": "http://song", "duration": 100}
            ),
        )

        with pytest.raises(PlaylistNotFoundError):
            await PlaylistService.get_playlist_detail(1, 200, "Private")

        code = await PlaylistService.generate_share_code(1, 100, "Private")
        copied = await PlaylistService.copy_playlist(1, 200, code, "Private Copy")

        assert copied.name == "Private_Copy"
        assert copied.track_count == 1

    async def test_copy_generates_non_conflicting_name(self, db):
        from core.playlists.service import PlaylistService

        await PlaylistService.create_playlist(1, 100, "Original")
        await PlaylistService.create_playlist(1, 100, "Copy")
        copied = await PlaylistService.copy_playlist(1, 100, "Original", "Copy")

        assert copied.name == "Copy_2"

    async def test_vote_counts_are_aggregated(self, db):
        from core.playlists.service import PlaylistService

        await PlaylistService.create_playlist(1, 100, "Votes")
        await PlaylistService.add_item(
            1,
            100,
            "Votes",
            PlaylistService.item_from_mapping(
                {"title": "Song", "url": "http://song", "duration": 100}
            ),
        )

        _, counts = await PlaylistService.vote_item(1, 100, "Votes", 1, 200, 1)
        assert counts == (1, 0)

        _, counts = await PlaylistService.vote_item(1, 100, "Votes", 1, 200, -1)
        assert counts == (0, 1)


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


def test_track_roundtrip():
    from core.track import Track

    track = Track(
        title="X",
        url="u",
        duration=10,
        requester_id=5,
        requester_name="bob",
        source="youtube",
        thumbnail="th",
        lazy_query="q",
    )
    restored = Track.from_dict(track.to_dict())
    assert (
        restored.title,
        restored.url,
        restored.duration,
        restored.requester_id,
        restored.requester_name,
        restored.source,
        restored.thumbnail,
        restored.lazy_query,
    ) == ("X", "u", 10, 5, "bob", "youtube", "th", "q")


@pytest.mark.asyncio
class TestHistoryAggregates:
    async def test_requesters_and_user_stats(self, db):
        from core.repositories import HistoryRepo

        await HistoryRepo.add(1, "Song A", "u1", 100, 50)
        await HistoryRepo.add(1, "Song A", "u2", 100, 50)
        await HistoryRepo.add(1, "Song B", "u3", 100, 60)

        top = await HistoryRepo.get_top_requesters(1)
        assert top[0] == (50, 2)

        assert await HistoryRepo.get_user_play_count(1, 50) == 2
        assert await HistoryRepo.get_user_play_count(1, 999) == 0

        user_top = await HistoryRepo.get_user_top_tracks(1, 50)
        assert user_top[0] == ("Song A", 2)


@pytest.mark.asyncio
class TestQueueStateRepo:
    async def test_save_upsert_get_delete(self, db):
        from core.repositories import QueueStateRepo

        await QueueStateRepo.save(7, '{"a": 1}')
        await QueueStateRepo.save(7, '{"a": 2}')  # upsert, not a second row
        rows = await QueueStateRepo.get_all()
        assert len(rows) == 1
        assert rows[0].guild_id == 7
        assert rows[0].data == '{"a": 2}'

        await QueueStateRepo.delete(7)
        assert await QueueStateRepo.get_all() == []


@pytest.mark.asyncio
class TestSoundboardRepo:
    async def test_add_get_delete(self, db):
        from core.repositories import SoundboardRepo

        # Add sound
        sound = await SoundboardRepo.add(
            guild_id=1, name="test_sound", url="http://test.url/sound.mp3", created_by=100
        )
        assert sound is not None
        assert sound.name == "test_sound"
        assert sound.url == "http://test.url/sound.mp3"

        # Get sound
        res = await SoundboardRepo.get(guild_id=1, name="test_sound")
        assert res is not None
        assert res.url == "http://test.url/sound.mp3"

        # List sounds
        all_sounds = await SoundboardRepo.get_all(guild_id=1)
        assert len(all_sounds) == 1

        # Delete sound
        deleted = await SoundboardRepo.delete(guild_id=1, name="test_sound")
        assert deleted is True

        res = await SoundboardRepo.get(guild_id=1, name="test_sound")
        assert res is None
