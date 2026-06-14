"""Track dataclass representing a single audio track."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Track:
    """Represents a single audio track in the queue or playlist."""

    title: str
    url: str  # Original URL or search query
    duration: int | None = None  # Duration in seconds
    requester_id: int | None = None  # Discord user ID who requested the track
    requester_name: str = "Unknown"
    source: str = "youtube"  # youtube, soundcloud, bandcamp, direct, spotify
    thumbnail: str | None = None
    stream_url: str | None = None  # Direct audio stream URL (from yt-dlp extraction)
    lazy_query: str | None = None
    added_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def duration_str(self) -> str:
        """Format duration as HH:MM:SS or MM:SS."""
        if self.duration is None:
            return "LIVE"
        duration_int = int(self.duration)
        hours, remainder = divmod(duration_int, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @property
    def short_title(self) -> str:
        """Truncate title to 50 characters."""
        if len(self.title) <= 50:
            return self.title
        return self.title[:47] + "..."

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict (for queue persistence).

        Omits ``stream_url`` (expires and is re-resolved) and ``added_at``.
        """
        return {
            "title": self.title,
            "url": self.url,
            "duration": self.duration,
            "requester_id": self.requester_id,
            "requester_name": self.requester_name,
            "source": self.source,
            "thumbnail": self.thumbnail,
            "lazy_query": self.lazy_query,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Track:
        """Reconstruct a Track from :meth:`to_dict` output."""
        return cls(
            title=data["title"],
            url=data["url"],
            duration=data.get("duration"),
            requester_id=data.get("requester_id"),
            requester_name=data.get("requester_name", "Unknown"),
            source=data.get("source", "youtube"),
            thumbnail=data.get("thumbnail"),
            lazy_query=data.get("lazy_query"),
        )

    def __str__(self) -> str:
        return f"{self.title} [{self.duration_str}]"
