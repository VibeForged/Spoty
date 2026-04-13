"""Tests for FX preset filter building."""

from __future__ import annotations

import pytest

from core.filters import (
    BUILTIN_PRESETS,
    build_ffmpeg_filter_string,
    build_wavelink_filters,
    combine_preset_definitions,
    get_all_preset_names,
    parse_preset_input,
    preset_requires_ffmpeg,
)


class TestFilters:
    def test_all_builtin_presets_have_values(self):
        for name, value in BUILTIN_PRESETS.items():
            assert isinstance(value, dict)
            assert value["version"] == 1

    def test_build_single_preset(self):
        result = combine_preset_definitions(["nightcore"])
        assert result["timescale"]["speed"] == 1.25

    def test_build_multiple_presets(self):
        result = combine_preset_definitions(["bassboost", "tremolo"])
        ffmpeg = build_ffmpeg_filter_string(result)
        assert "equalizer=" in ffmpeg
        assert "tremolo=f=6.00" in ffmpeg

    def test_build_with_custom(self):
        custom = {"mypreset": {"version": 1, "volume_multiplier": 2.0}}
        result = combine_preset_definitions(["mypreset"], custom)
        assert result["volume_multiplier"] == 2.0

    def test_build_mixed_builtin_and_custom(self):
        custom = {"mypreset": {"version": 1, "volume_multiplier": 2.0}}
        result = combine_preset_definitions(["bassboost", "mypreset"], custom)
        ffmpeg = build_ffmpeg_filter_string(result)
        assert "equalizer=" in ffmpeg
        assert "volume=2.00" in ffmpeg

    def test_build_unknown_preset_raises(self):
        with pytest.raises(ValueError, match="Unknown preset"):
            combine_preset_definitions(["nonexistent"])

    def test_wavelink_filters_supported_preset(self):
        filters = build_wavelink_filters(BUILTIN_PRESETS["tremolo"])
        assert filters is not None

    def test_ffmpeg_only_preset_requires_fallback(self):
        assert preset_requires_ffmpeg(BUILTIN_PRESETS["echo"]) is True
        assert build_wavelink_filters(BUILTIN_PRESETS["echo"]) is None

    def test_parse_preset_input(self):
        parsed = parse_preset_input('{"timescale":{"speed":1.1,"pitch":1.1}}')
        assert parsed["timescale"]["speed"] == 1.1

    def test_parse_legacy_filter_input(self):
        parsed = parse_preset_input("aecho=0.8:0.88:60:0.4")
        assert parsed["ffmpeg_only_filters"] == ["aecho=0.8:0.88:60:0.4"]

    def test_get_all_preset_names(self):
        names = get_all_preset_names()
        assert "nightcore" in names
        assert "bassboost" in names
        assert len(names) == len(BUILTIN_PRESETS)

    def test_get_all_preset_names_with_custom(self):
        custom = {"mypreset": {"version": 1, "volume_multiplier": 2.0}}
        names = get_all_preset_names(custom)
        assert "mypreset" in names
        assert len(names) == len(BUILTIN_PRESETS) + 1

    def test_expected_preset_count(self):
        assert len(BUILTIN_PRESETS) == 12
