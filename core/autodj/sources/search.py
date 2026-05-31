"""Keyword-based YouTube search fallback source."""

from __future__ import annotations

import time

from loguru import logger

from core.autodj.models import ScoredTrack, SessionContext, SourceResult
from core.autodj.sources.base import RecommendationSource
from core.autodj.utils import extract_keywords, parse_artist_title


class SearchFallbackSource(RecommendationSource):
    """Last-resort source: search YouTube by keywords derived from the seed track.

    Used when YouTube Mix and other sources fail or return empty results.
    Lower confidence than direct recommendation sources.
    """

    name = "search"
    weight = 0.5
    timeout = 15.0

    async def fetch(self, context: SessionContext) -> SourceResult:
        start = time.monotonic()

        if context.seed_track is None:
            return SourceResult([], self.name, confidence=0.0)

        keywords = extract_keywords(context.seed_track.title)
        if not keywords or len(keywords) < 3:
            logger.debug("SearchFallbackSource: insufficient keywords from title")
            return SourceResult([], self.name, confidence=0.0)

        query = f"{keywords} music"
        logger.debug("SearchFallbackSource: searching '{}'", query[:60])

        from core.extractor import extract_info, YDL_SEARCH_OPTS

        try:
            # We must use YDL_SEARCH_OPTS to enforce flat extraction, otherwise it fetches all formats
            info = await extract_info(f"ytsearch5:{query}", opts=YDL_SEARCH_OPTS)
        except Exception as exc:
            logger.warning("SearchFallbackSource: search failed: {}", exc)
            return SourceResult([], self.name, confidence=0.0)

        if info is None:
            return SourceResult([], self.name, confidence=0.0)

        entries = info.get("entries", [])
        scored = []
        for entry in entries:
            if entry is None:
                continue
            title = entry.get("title")
            url = entry.get("webpage_url") or entry.get("url") or entry.get("id")
            if not title or not url:
                continue
            if not url.startswith("http"):
                url = f"https://www.youtube.com/watch?v={url}"

            from core.track import Track

            artist, _ = parse_artist_title(title)
            track = Track(
                title=title,
                url=url,
                duration=int(entry["duration"]) if entry.get("duration") is not None else None,
                source=entry.get("extractor_key", "youtube").lower(),
                thumbnail=entry.get("thumbnail"),
            )
            scored.append(
                ScoredTrack(
                    track=track,
                    score=self.weight,
                    source=self.name,
                    artist_name=artist,
                )
            )

        latency = (time.monotonic() - start) * 1000
        confidence = 0.5 if scored else 0.0
        logger.debug("SearchFallbackSource: {} candidates in {:.0f}ms", len(scored), latency)
        return SourceResult(scored, self.name, confidence=confidence, latency_ms=latency)
