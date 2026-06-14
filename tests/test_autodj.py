"""Tests for the Auto-DJ engine circuit breaker."""

from __future__ import annotations

import pytest

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


def test_artist_feedback_signals():
    from core.autodj.models import ScoredTrack, SessionContext
    from core.autodj.scorer import score_candidates
    from core.track import Track

    context = SessionContext(guild_id=123)
    # 2 skips = -0.10 penalty
    context.skip_artists["artist a"] = 2
    # 1 completion = +0.10 bonus
    context.completion_artists["artist a"] = 1

    track_a = Track(title="Artist A - Song A", url="u1", duration=180)
    candidate_a = ScoredTrack(track=track_a, score=1.0, artist_name="Artist A")

    track_b = Track(title="Artist B - Song B", url="u2", duration=180)
    candidate_b = ScoredTrack(track=track_b, score=1.0, artist_name="Artist B")

    scored = score_candidates([candidate_a, candidate_b], context)

    # Find the scored candidates
    scored_a = next(c for c in scored if c.track.url == "u1")
    scored_b = next(c for c in scored if c.track.url == "u2")

    # Base for both: 1.0 (base) + 0.3 (diversity) + 0.2 (recency) = 1.5
    # scored_b has no penalties or bonuses: 1.5
    # scored_a has: 1.5 - (0.05 * 2) + 0.1 = 1.5
    assert scored_b.score == pytest.approx(1.5)
    assert scored_a.score == pytest.approx(1.5)

    # If we add another skip, scored_a should go down by 0.05
    context.skip_artists["artist a"] = 3
    candidate_a.score = 1.0  # Reset mutated state from the previous run
    scored_retry = score_candidates([candidate_a], context)
    assert scored_retry[0].score == pytest.approx(1.45)
