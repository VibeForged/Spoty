"""Track dataclass representing a single audio track."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
    added_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def duration_str(self) -> str:
        """Format duration as HH:MM:SS or MM:SS."""
        if self.duration is None:
            return "LIVE"
        hours, remainder = divmod(self.duration, 3600)
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

    def __str__(self) -> str:
        return f"{self.title} [{self.duration_str}]"
