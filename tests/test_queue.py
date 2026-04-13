"""Tests for the MusicQueue data structure."""

from __future__ import annotations

import pytest

from core.queue import LoopMode, MusicQueue
from core.track import Track


def _make_track(title: str = "Test", url: str = "https://example.com") -> Track:
    return Track(title=title, url=url, duration=180)


class TestMusicQueue:
    def test_add_and_size(self):
        q = MusicQueue()
        assert q.is_empty
        q.add(_make_track("Song 1"))
        assert q.size == 1
        assert not q.is_empty

    def test_add_returns_position(self):
        q = MusicQueue()
        pos1 = q.add(_make_track("Song 1"))
        pos2 = q.add(_make_track("Song 2"))
        assert pos1 == 1
        assert pos2 == 2

    def test_add_top(self):
        q = MusicQueue()
        q.add(_make_track("Song 1"))
        q.add_top(_make_track("Song 0"))
        assert q.peek().title == "Song 0"

    def test_next_off_mode(self):
        q = MusicQueue()
        t1 = _make_track("Song 1")
        t2 = _make_track("Song 2")
        q.add(t1)
        q.add(t2)

        result = q.next(None)
        assert result.title == "Song 1"
        assert q.size == 1

        result = q.next(t1)
        assert result.title == "Song 2"
        assert q.size == 0

    def test_next_returns_none_when_empty(self):
        q = MusicQueue()
        assert q.next(None) is None

    def test_loop_track_mode(self):
        q = MusicQueue()
        t1 = _make_track("Song 1")
        q.add(t1)
        q.loop_mode = LoopMode.TRACK

        # First call gets t1 from queue
        result = q.next(None)
        assert result.title == "Song 1"

        # Subsequent calls return the same track
        result = q.next(t1)
        assert result.title == "Song 1"
        result = q.next(t1)
        assert result.title == "Song 1"

    def test_loop_queue_mode(self):
        q = MusicQueue()
        t1 = _make_track("Song 1")
        t2 = _make_track("Song 2")
        q.add(t1)
        q.add(t2)
        q.loop_mode = LoopMode.QUEUE

        r1 = q.next(None)
        assert r1.title == "Song 1"

        r2 = q.next(r1)
        assert r2.title == "Song 2"
        # t1 should be at the back
        assert q.size == 1

        r3 = q.next(r2)
        assert r3.title == "Song 1"

    def test_remove(self):
        q = MusicQueue()
        t1 = _make_track("Song 1")
        t2 = _make_track("Song 2")
        q.add(t1)
        q.add(t2)

        removed = q.remove(0)
        assert removed.title == "Song 1"
        assert q.size == 1

    def test_remove_invalid_index(self):
        q = MusicQueue()
        assert q.remove(0) is None
        assert q.remove(-1) is None

    def test_move(self):
        q = MusicQueue()
        q.add(_make_track("Song 1"))
        q.add(_make_track("Song 2"))
        q.add(_make_track("Song 3"))

        assert q.move(2, 0)
        assert q.peek().title == "Song 3"

    def test_shuffle(self):
        q = MusicQueue()
        for i in range(20):
            q.add(_make_track(f"Song {i}"))

        original = [t.title for t in q.tracks]
        q.shuffle()
        shuffled = [t.title for t in q.tracks]

        assert q.size == 20
        # Very unlikely to be the same order (1/20! chance)
        assert sorted(original) == sorted(shuffled)

    def test_clear(self):
        q = MusicQueue()
        for i in range(5):
            q.add(_make_track(f"Song {i}"))

        count = q.clear()
        assert count == 5
        assert q.is_empty

    def test_max_size(self):
        q = MusicQueue(max_size=3)
        q.add(_make_track("1"))
        q.add(_make_track("2"))
        q.add(_make_track("3"))

        assert q.is_full
        with pytest.raises(Exception):  # QueueFull
            q.add(_make_track("4"))

    def test_get_page(self):
        q = MusicQueue()
        for i in range(25):
            q.add(_make_track(f"Song {i}"))

        tracks, pages = q.get_page(1, per_page=10)
        assert len(tracks) == 10
        assert pages == 3

        tracks, pages = q.get_page(3, per_page=10)
        assert len(tracks) == 5

    def test_history(self):
        q = MusicQueue()
        t1 = _make_track("Song 1")
        q.add(t1)

        q.next(None)  # Gets t1
        q.next(t1)  # Moves t1 to history

        assert len(q.history) == 1
        assert q.history[0].title == "Song 1"

    def test_previous(self):
        q = MusicQueue()
        t1 = _make_track("Song 1")
        t2 = _make_track("Song 2")
        q.add(t1)
        q.add(t2)

        q.next(None)
        q.next(t1)

        prev = q.previous()
        assert prev.title == "Song 1"

    def test_total_duration(self):
        q = MusicQueue()
        q.add(Track(title="A", url="a", duration=100))
        q.add(Track(title="B", url="b", duration=200))
        q.add(Track(title="C", url="c", duration=None))

        assert q.total_duration == 300
