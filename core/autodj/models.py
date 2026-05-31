"""Data models for the Auto-DJ recommendation engine."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from core.track import Track


@dataclass
class ScoredTrack:
    """A candidate track with recommendation metadata and composite score."""

    track: Track
    score: float = 0.0
    source: str = "unknown"  # "youtube_mix" | "lastfm" | "history" | "search"
    artist_name: str | None = None
    genre_hint: str | None = None

    def __repr__(self) -> str:
        return f"ScoredTrack({self.track.short_title}, score={self.score:.2f}, src={self.source})"


@dataclass
class SourceResult:
    """Result bundle from a single recommendation source."""

    tracks: list[ScoredTrack]
    source_name: str
    confidence: float = 1.0  # 0.0-1.0
    latency_ms: float = 0.0


@dataclass
class SessionContext:
    """Accumulated state for a per-guild Auto-DJ session.

    Tracks recent artists, URLs, skip signals, and genre affinity to produce
    better recommendations over the lifetime of a listening session.
    """

    guild_id: int
    seed_track: Track | None = None
    recent_artists: deque[str] = field(default_factory=lambda: deque(maxlen=20))
    recent_urls: set[str] = field(default_factory=set)
    skip_signals: dict[str, int] = field(default_factory=dict)  # url -> skip_count
    completion_signals: dict[str, int] = field(default_factory=dict)  # url -> complete_count
    tracks_served: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    genre_affinity: dict[str, float] = field(default_factory=dict)  # genre -> weight
    _max_recent_urls: int = field(default=200, repr=False)

    def record_played_url(self, url: str) -> None:
        """Add a URL to the recent set, evicting oldest if over capacity."""
        self.recent_urls.add(url)
        if len(self.recent_urls) > self._max_recent_urls:
            # Remove an arbitrary element to keep bounded
            self.recent_urls.pop()

    def record_artist(self, artist: str) -> None:
        """Track a recently played artist for diversity scoring."""
        self.recent_artists.append(artist.lower().strip())

    def record_skip(self, url: str) -> None:
        """Record that a track was skipped by the user."""
        self.skip_signals[url] = self.skip_signals.get(url, 0) + 1

    def record_completion(self, url: str) -> None:
        """Record that a track was played to completion."""
        self.completion_signals[url] = self.completion_signals.get(url, 0) + 1

    def should_reset(self) -> bool:
        """Check if the session has gone stale and should re-seed."""
        return self.tracks_served >= 50
