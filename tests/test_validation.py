"""Tests for input validation: raw FFmpeg filters and user-supplied names."""

from __future__ import annotations

import pytest

from core.filters import parse_preset_input, validate_raw_ffmpeg_filters
from core.validation import validate_name


class TestRawFilterValidation:
    def test_allows_known_filter(self):
        assert validate_raw_ffmpeg_filters("aecho=0.8:0.88:60:0.4") == "aecho=0.8:0.88:60:0.4"

    def test_allows_chain_of_known_filters(self):
        assert validate_raw_ffmpeg_filters("atempo=1.2,volume=0.5")

    def test_rejects_unknown_filter(self):
        with pytest.raises(ValueError):
            validate_raw_ffmpeg_filters("rm=1")

    def test_rejects_forbidden_chars(self):
        with pytest.raises(ValueError):
            validate_raw_ffmpeg_filters('volume=1;"evil"')

    def test_rejects_overlong(self):
        with pytest.raises(ValueError):
            validate_raw_ffmpeg_filters("volume=1" + "0" * 600)

    def test_parse_preset_input_rejects_bad_raw(self):
        with pytest.raises(ValueError):
            parse_preset_input("notafilter=1")

    def test_parse_preset_input_accepts_good_raw(self):
        definition = parse_preset_input("aecho=0.8:0.88:60:0.4")
        assert definition["ffmpeg_only_filters"] == ["aecho=0.8:0.88:60:0.4"]


class TestNameValidation:
    def test_accepts_normal(self):
        assert validate_name("My Playlist", max_length=100) == "My Playlist"

    def test_strips_whitespace(self):
        assert validate_name("  hi  ", max_length=100) == "hi"

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_name("   ", max_length=100)

    def test_rejects_too_long(self):
        with pytest.raises(ValueError):
            validate_name("x" * 101, max_length=100)

    def test_rejects_bidi_override(self):
        # U+202E (right-to-left override) can spoof how a name renders.
        with pytest.raises(ValueError):
            validate_name("evil" + chr(0x202E) + "name", max_length=100)
