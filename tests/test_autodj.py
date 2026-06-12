"""Tests for the Auto-DJ engine circuit breaker."""

from __future__ import annotations

from core.autodj.engine import AutoDJEngine


def test_circuit_breaker_trips_after_threshold_and_resets_on_success():
    engine = AutoDJEngine()
    name = "youtube_mix"

    assert engine._source_available(name) is True

    for _ in range(AutoDJEngine._BREAKER_THRESHOLD):
        engine._record_source_outcome(name, success=False)
    assert engine._source_available(name) is False  # tripped

    engine._record_source_outcome(name, success=True)
    assert engine._source_available(name) is True  # reset


def test_failures_below_threshold_keep_source_available():
    engine = AutoDJEngine()
    name = "lastfm"

    for _ in range(AutoDJEngine._BREAKER_THRESHOLD - 1):
        engine._record_source_outcome(name, success=False)
    assert engine._source_available(name) is True
