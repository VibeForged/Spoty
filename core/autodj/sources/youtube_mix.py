"""YouTube Mix recommendation source — migrated and improved from the original autoplay."""

from __future__ import annotations

import re
import time

from loguru import logger

from core.autodj.models import ScoredTrack, SessionContext, SourceResult
from core.autodj.sources.base import RecommendationSource
from core.autodj.utils import parse_artist_title


class YouTubeMixSource(RecommendationSource):
    """Fetch related tracks via YouTube's auto-generated Mix playlist.

    This is the strongest signal source — YouTube's recommendation algorithm
    is genre-aware and context-sensitive. Corresponds to the ``RD{video_id}``
    playlist that YouTube generates for each video.
    """

    name = "youtube_mix"
    weight = 1.0
    timeout = 20.0  # YouTube extraction can be slow

    async def fetch(self, context: SessionContext) -> SourceResult:
        start = time.monotonic()

        if context.seed_track is None:
            return SourceResult([], self.name, confidence=0.0)

        video_id = _extract_video_id(context.seed_track.url)
        if not video_id:
            logger.debug("YouTubeMixSource: no video ID from URL {}", context.seed_track.url[:80])
            return SourceResult([], self.name, confidence=0.0)

        from core.extractor import get_related_tracks

        try:
            related = await get_related_tracks(video_id, limit=10)
        except Exception as exc:
            logger.warning("YouTubeMixSource: extraction failed: {}", exc)
            return SourceResult([], self.name, confidence=0.0)

        scored = []
        for track in related:
            artist, _ = parse_artist_title(track.title)
            scored.append(
                ScoredTrack(
                    track=track,
                    score=self.weight,
                    source=self.name,
                    artist_name=artist,
                )
            )

        latency = (time.monotonic() - start) * 1000
        confidence = 0.9 if scored else 0.0
        logger.debug("YouTubeMixSource: {} candidates in {:.0f}ms", len(scored), latency)
        return SourceResult(scored, self.name, confidence=confidence, latency_ms=latency)


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from a URL."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None
