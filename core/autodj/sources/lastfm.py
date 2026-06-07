"""Last.fm recommendation source using the free public API."""

from __future__ import annotations

import time

import aiohttp
from cachetools import TTLCache
from loguru import logger

from core.autodj.models import ScoredTrack, SessionContext, SourceResult
from core.autodj.sources.base import RecommendationSource
from core.autodj.utils import parse_artist_title
from core.track import Track

# Cache Last.fm API responses for 1 hour (same artist+track = same results)
_lastfm_cache: TTLCache[str, list[dict]] = TTLCache(maxsize=500, ttl=3600)


class LastFmSource(RecommendationSource):
    """Fetch similar tracks via Last.fm's free API.

    Uses ``track.getSimilar`` and ``artist.getSimilar`` endpoints.
    Requires a free API key from https://www.last.fm/api/account/create
    (rate limit: ~30 requests/min, no auth required for read-only).
    """

    name = "lastfm"
    weight = 0.9
    timeout = 6.0

    async def fetch(self, context: SessionContext) -> SourceResult:
        start = time.monotonic()

        # Need an API key configured
        try:
            from config import BotConfig

            config = BotConfig()
            api_key = config.lastfm_api_key
        except Exception:
            api_key = ""

        if not api_key:
            return SourceResult([], self.name, confidence=0.0)

        if context.seed_track is None:
            return SourceResult([], self.name, confidence=0.0)

        artist, title = parse_artist_title(context.seed_track.title)
        if not artist:
            # Try artist.getSimilar as fallback if we can't parse
            return SourceResult([], self.name, confidence=0.0)

        # Check cache first
        cache_key = f"{artist.lower()}|{title.lower()}"
        if cache_key in _lastfm_cache:
            cached = _lastfm_cache[cache_key]
            scored = self._convert_results(cached)
            latency = (time.monotonic() - start) * 1000
            return SourceResult(scored, self.name, confidence=0.85, latency_ms=latency)

        # Fetch similar tracks
        similar_tracks = await self._fetch_similar_tracks(api_key, artist, title)

        # If track.getSimilar returns nothing, try artist.getSimilar
        if not similar_tracks:
            similar_tracks = await self._fetch_similar_artists_top(api_key, artist)

        if similar_tracks:
            _lastfm_cache[cache_key] = similar_tracks

        scored = self._convert_results(similar_tracks)
        latency = (time.monotonic() - start) * 1000
        confidence = 0.85 if scored else 0.0
        logger.debug("LastFmSource: {} candidates in {:.0f}ms", len(scored), latency)
        return SourceResult(scored, self.name, confidence=confidence, latency_ms=latency)

    async def _fetch_similar_tracks(
        self, api_key: str, artist: str, track: str
    ) -> list[dict]:
        """Call Last.fm track.getSimilar API."""
        params = {
            "method": "track.getSimilar",
            "artist": artist,
            "track": track,
            "api_key": api_key,
            "format": "json",
            "limit": "10",
        }
        return await self._call_api(params, result_path=("similartracks", "track"))

    async def _fetch_similar_artists_top(self, api_key: str, artist: str) -> list[dict]:
        """Fallback: get similar artists and their top tracks."""
        # Step 1: Get similar artists
        params = {
            "method": "artist.getSimilar",
            "artist": artist,
            "api_key": api_key,
            "format": "json",
            "limit": "5",
        }
        similar_artists = await self._call_api(params, result_path=("similarartists", "artist"))

        if not similar_artists:
            return []

        # Step 2: Get top track from each similar artist
        results = []
        for sim_artist in similar_artists[:5]:
            artist_name = sim_artist.get("name")
            if not artist_name:
                continue

            top_params = {
                "method": "artist.getTopTracks",
                "artist": artist_name,
                "api_key": api_key,
                "format": "json",
                "limit": "2",
            }
            top_tracks = await self._call_api(top_params, result_path=("toptracks", "track"))
            for t in top_tracks[:2]:
                t["_artist_name"] = artist_name
                results.append(t)

        return results

    async def _call_api(self, params: dict, result_path: tuple[str, str]) -> list[dict]:
        """Make an HTTP GET request to the Last.fm API."""
        url = "https://ws.audioscrobbler.com/2.0/"
        try:
            async with aiohttp.ClientSession() as session, session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    logger.debug("Last.fm API returned status {}", resp.status)
                    return []
                data = await resp.json()

            # Navigate the nested response
            result = data
            for key in result_path:
                if not isinstance(result, dict) or key not in result:
                    return []
                result = result[key]

            if isinstance(result, list):
                return result
            return []
        except Exception as exc:
            logger.debug("Last.fm API call failed: {}", exc)
            return []

    def _convert_results(self, results: list[dict]) -> list[ScoredTrack]:
        """Convert Last.fm API results to ScoredTrack objects."""
        scored = []
        for item in results:
            name = item.get("name", "")
            artist_info = item.get("artist")
            artist_name = None

            if isinstance(artist_info, dict):
                artist_name = artist_info.get("name")
            elif isinstance(artist_info, str):
                artist_name = artist_info

            # Check for fallback artist name (from artist.getTopTracks)
            if not artist_name:
                artist_name = item.get("_artist_name")

            if not name:
                continue

            # Build a YouTube search query — Last.fm doesn't give us URLs
            search_title = f"{artist_name} - {name}" if artist_name else name
            f"https://www.youtube.com/results?search_query={search_title.replace(' ', '+')}"

            # Duration from Last.fm (in ms or seconds depending on endpoint)
            duration = None
            raw_duration = item.get("duration")
            if raw_duration:
                try:
                    dur_int = int(raw_duration)
                    # Last.fm returns duration in ms for track.getSimilar
                    duration = dur_int // 1000 if dur_int > 10000 else dur_int
                except (ValueError, TypeError):
                    pass

            track = Track(
                title=search_title,
                url=f"ytsearch:{search_title}",  # Will be resolved by extractor at play time
                duration=duration,
                source="lastfm",
            )
            scored.append(
                ScoredTrack(
                    track=track,
                    score=self.weight,
                    source=self.name,
                    artist_name=artist_name,
                )
            )

        return scored
