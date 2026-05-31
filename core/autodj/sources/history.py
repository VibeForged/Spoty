"""Guild play-history mining as a recommendation source."""

from __future__ import annotations

import time

from loguru import logger

from core.autodj.models import ScoredTrack, SessionContext, SourceResult
from core.autodj.sources.base import RecommendationSource
from core.autodj.utils import parse_artist_title
from core.track import Track


class HistorySource(RecommendationSource):
    """Recommend tracks from the guild's own play history.

    Surfaces popular tracks that members have previously enjoyed, weighted
    by play count. Excludes tracks played too recently to avoid repetition.
    """

    name = "history"
    weight = 0.7
    timeout = 3.0

    async def fetch(self, context: SessionContext) -> SourceResult:
        start = time.monotonic()

        from core.repositories import HistoryRepo

        try:
            history = await HistoryRepo.get_top_tracks(
                context.guild_id,
                limit=30,
                exclude_recent=100,
            )
        except Exception as exc:
            logger.warning("HistorySource: DB query failed: {}", exc)
            return SourceResult([], self.name, confidence=0.0)

        if not history:
            return SourceResult([], self.name, confidence=0.0)

        scored = []
        for row in history:
            play_count = row.get("play_count", 1)
            # Normalize play count to a 0-1 scale (10+ plays = max)
            count_score = min(play_count / 10.0, 1.0) * self.weight
            artist, _ = parse_artist_title(row["track_title"])
            track = Track(
                title=row["track_title"],
                url=row["track_url"],
                duration=row.get("duration"),
            )
            scored.append(
                ScoredTrack(
                    track=track,
                    score=count_score,
                    source=self.name,
                    artist_name=artist,
                )
            )

        latency = (time.monotonic() - start) * 1000
        confidence = 0.7 if scored else 0.0
        logger.debug("HistorySource: {} candidates in {:.0f}ms", len(scored), latency)
        return SourceResult(scored, self.name, confidence=confidence, latency_ms=latency)
