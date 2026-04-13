"""Tests for FX preset filter building."""

from __future__ import annotations

import pytest

from core.filters import BUILTIN_PRESETS, build_filter_chain, get_all_preset_names


class TestFilters:
    def test_all_builtin_presets_have_values(self):
        for name, value in BUILTIN_PRESETS.items():
            assert isinstance(value, str)
            assert len(value) > 0

    def test_build_single_preset(self):
        result = build_filter_chain(["nightcore"])
        assert result == BUILTIN_PRESETS["nightcore"]

    def test_build_multiple_presets(self):
        result = build_filter_chain(["bassboost", "tremolo"])
        assert "bass=g=15" in result
        assert "tremolo=f=6" in result
        assert "," in result

    def test_build_with_custom(self):
        custom = {"mypreset": "volume=2.0"}
        result = build_filter_chain(["mypreset"], custom)
        assert result == "volume=2.0"

    def test_build_mixed_builtin_and_custom(self):
        custom = {"mypreset": "volume=2.0"}
        result = build_filter_chain(["bassboost", "mypreset"], custom)
        assert "bass=g=15" in result
        assert "volume=2.0" in result

    def test_build_unknown_preset_raises(self):
        with pytest.raises(ValueError, match="Unknown preset"):
            build_filter_chain(["nonexistent"])

    def test_get_all_preset_names(self):
        names = get_all_preset_names()
        assert "nightcore" in names
        assert "bassboost" in names
        assert len(names) == len(BUILTIN_PRESETS)

    def test_get_all_preset_names_with_custom(self):
        custom = {"mypreset": "volume=2.0"}
        names = get_all_preset_names(custom)
        assert "mypreset" in names
        assert len(names) == len(BUILTIN_PRESETS) + 1

    def test_expected_preset_count(self):
        assert len(BUILTIN_PRESETS) == 12
