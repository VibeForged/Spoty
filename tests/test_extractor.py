"""Tests for the track dataclass and extractor utilities."""

from __future__ import annotations

from core.track import Track


class TestTrack:
    def test_duration_str_minutes(self):
        t = Track(title="Test", url="https://example.com", duration=90)
        assert t.duration_str == "1:30"

    def test_duration_str_hours(self):
        t = Track(title="Test", url="https://example.com", duration=3661)
        assert t.duration_str == "1:01:01"

    def test_duration_str_none(self):
        t = Track(title="Test", url="https://example.com", duration=None)
        assert t.duration_str == "LIVE"

    def test_short_title_under_limit(self):
        t = Track(title="Short Title", url="https://example.com")
        assert t.short_title == "Short Title"

    def test_short_title_over_limit(self):
        long_title = "A" * 60
        t = Track(title=long_title, url="https://example.com")
        assert len(t.short_title) == 50
        assert t.short_title.endswith("...")

    def test_str_representation(self):
        t = Track(title="Test Song", url="https://example.com", duration=120)
        assert str(t) == "Test Song [2:00]"
