"""Tests for the track dataclass and extractor utilities."""

from __future__ import annotations

import pytest

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


@pytest.mark.asyncio
class TestExtractorSecurity:
    async def test_ssrf_risk_detection(self):
        from core.extractor import _is_ssrf_risk

        assert _is_ssrf_risk("http://127.0.0.1/abc") is True
        assert _is_ssrf_risk("http://localhost/abc") is True
        assert _is_ssrf_risk("https://169.254.169.254/latest/meta-data") is True
        assert _is_ssrf_risk("https://www.google.com") is False

    async def test_disallowed_schemes(self):
        from core.extractor import _has_disallowed_scheme

        assert _has_disallowed_scheme("file:///etc/passwd") is True
        assert _has_disallowed_scheme("ftp://example.com") is True
        assert _has_disallowed_scheme("https://example.com") is False

    async def test_extract_info_blocks_ssrf(self):
        from core.extractor import extract_info

        res = await extract_info("http://127.0.0.1/test")
        assert res is None
