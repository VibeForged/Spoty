"""Optimized lyrics fetching with prioritized sources (LRCLib first)."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
from loguru import logger

# Suppress verbose logging from other libs during lyrics fetch
logging.getLogger("urllib3").setLevel(logging.WARNING)

# A single reused HTTP session avoids a TLS handshake per lyrics lookup.
_session: aiohttp.ClientSession | None = None


async def get_session() -> aiohttp.ClientSession:
    """Return a lazily-created, reused aiohttp session."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def close_session() -> None:
    """Close the reused session (call on shutdown)."""
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None


class LyricsProvider:
    """Base class for lyrics providers."""

    async def search(
        self,
        query: str,
        artist: str = "",
        title: str = "",
        album: str = "",
        duration: int | None = None,
    ) -> str | None:
        """Fetch lyrics from this provider. Return LRC format or None."""
        raise NotImplementedError


class LRCLibProvider(LyricsProvider):
    """LRCLib provider using the newer signature-based API."""

    BASE_URL = "https://lrclib.net/api"

    async def search(
        self,
        query: str,
        artist: str = "",
        title: str = "",
        album: str = "",
        duration: int | None = None,
    ) -> str | None:
        """Search LRCLib API."""
        try:
            session = await get_session()
            if artist and title and album and duration is not None:
                lyrics = await self._fetch_by_signature(session, artist, title, album, duration)
                if lyrics:
                    logger.info("Found lyrics on LRCLib via exact signature")
                    return lyrics

            if title:
                lyrics = await self._search_records(
                    session,
                    track_name=title,
                    artist_name=artist,
                    album_name=album,
                )
                if lyrics:
                    logger.info("Found lyrics on LRCLib via track search")
                    return lyrics

            if query:
                lyrics = await self._search_records(session, q=query)
                if lyrics:
                    logger.info("Found lyrics on LRCLib via general search")
                    return lyrics
        except TimeoutError:
            logger.debug("LRCLib search timed out")
        except Exception as e:
            logger.debug("LRCLib search error: {}", e)
        return None

    async def _fetch_by_signature(
        self,
        session: aiohttp.ClientSession,
        artist: str,
        title: str,
        album: str,
        duration: int,
    ) -> str | None:
        params = {
            "artist_name": artist,
            "track_name": title,
            "album_name": album,
            "duration": duration,
        }
        try:
            async with session.get(
                f"{self.BASE_URL}/get",
                params=params,
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return self._extract_lyrics(data)
                if resp.status == 404:
                    return None
        except TimeoutError:
            raise
        except Exception as e:
            logger.debug("LRCLib signature fetch error: {}", e)
        return None

    async def _search_records(
        self,
        session: aiohttp.ClientSession,
        q: str | None = None,
        track_name: str | None = None,
        artist_name: str | None = None,
        album_name: str | None = None,
    ) -> str | None:
        params: dict[str, str] = {}
        if q:
            params["q"] = q
        elif track_name:
            params["track_name"] = track_name
        if artist_name:
            params["artist_name"] = artist_name
        if album_name:
            params["album_name"] = album_name

        if not params:
            return None

        try:
            async with session.get(
                f"{self.BASE_URL}/search",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    records = await resp.json()
                    if records and isinstance(records, list):
                        for record in records:
                            lyrics = self._extract_lyrics(record)
                            if lyrics:
                                return lyrics
        except TimeoutError:
            raise
        except Exception as e:
            logger.debug("LRCLib record search error: {}", e)
        return None

    @staticmethod
    def _extract_lyrics(record: dict[str, object]) -> str | None:
        return record.get("syncedLyrics") or record.get("plainLyrics") or None


class SyncedLyricsProvider(LyricsProvider):
    """Fallback to syncedlyrics library with safer source priority."""

    async def search(
        self,
        query: str,
        artist: str = "",
        title: str = "",
        album: str = "",
        duration: int | None = None,
    ) -> str | None:
        """Use syncedlyrics with limited sources."""
        try:
            # Reduce verbosity and timeouts
            import logging as std_logging

            std_logging.getLogger("syncedlyrics").setLevel(std_logging.ERROR)

            # Search with timeout
            loop = asyncio.get_running_loop()
            # Run syncedlyrics in executor to avoid blocking
            lrc = await loop.run_in_executor(
                None,
                self._syncedlyrics_search,
                query,
            )
            if lrc:
                logger.info("Found lyrics via syncedlyrics fallback")
                return lrc
        except ImportError:
            logger.debug("syncedlyrics not available")
        except Exception as e:
            logger.debug("syncedlyrics fallback error: {}", e)
        return None

    @staticmethod
    def _syncedlyrics_search(query: str) -> str | None:
        """Wrapper for syncedlyrics.search with error handling."""
        try:
            import syncedlyrics

            # Just try to search - syncedlyrics will try its sources
            result = syncedlyrics.search(query)
            return result if result else None
        except Exception:
            return None


class LyricsManager:
    """Manages lyrics fetching with multiple providers in priority order."""

    def __init__(self):
        self.providers: list[LyricsProvider] = [
            LRCLibProvider(),
            SyncedLyricsProvider(),
        ]

    async def fetch(
        self,
        query: str,
        artist: str = "",
        title: str = "",
        album: str = "",
        duration: int | None = None,
    ) -> str | None:
        """Fetch lyrics from available providers in priority order.

        Args:
            query: Main search query (usually "artist - title")
            artist: Optional artist name
            title: Optional song title

        Returns:
            Lyrics in LRC format if found, otherwise None
        """
        for provider in self.providers:
            logger.debug(f"Trying {provider.__class__.__name__}...")
            try:
                lyrics = await provider.search(query, artist, title, album, duration)
                if lyrics:
                    return lyrics
            except Exception as e:
                logger.debug(f"{provider.__class__.__name__} failed: {e}")
                continue

        logger.debug("No lyrics found from any provider")
        return None


# Global instance
_manager = LyricsManager()


async def fetch_lyrics(
    query: str,
    artist: str = "",
    title: str = "",
    album: str = "",
    duration: int | None = None,
) -> str | None:
    """Fetch lyrics with optimized source priority.

    Args:
        query: Main search query (usually "artist - title")
        artist: Optional artist name for registry music lookup
        title: Optional song title for registry music lookup

    Returns:
        Lyrics in LRC format if found, otherwise None
    """
    return await _manager.fetch(query, artist, title, album, duration)
