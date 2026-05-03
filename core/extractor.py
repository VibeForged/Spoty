"""Async yt-dlp wrapper with TTL caching for audio extraction."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import yt_dlp
from cachetools import TTLCache
from loguru import logger

from config import BotConfig
from core.track import Track

# Bounded thread pool for yt-dlp extraction (sync library)
_thread_pool = ThreadPoolExecutor(max_workers=3)

# Cache extracted info for 10 minutes (600s), max 200 entries (~1MB)
_extraction_cache: TTLCache[str, dict[str, Any]] = TTLCache(maxsize=200, ttl=600)

# yt-dlp options for audio extraction (no download)
def _get_ydl_opts() -> dict[str, Any]:
    """Get yt-dlp options with optional cookie support."""
    config = BotConfig()
    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "no_warnings": True,
        "quiet": True,
        "extract_flat": False,
        "source_address": "0.0.0.0",
        "default_search": "ytsearch",
        "geo_bypass": True,
    }
    if config.ytdlp_cookies_file:
        opts["cookiefile"] = config.ytdlp_cookies_file
    return opts

YDL_OPTS = _get_ydl_opts()

YDL_PLAYLIST_OPTS: dict[str, Any] = {
    **YDL_OPTS,
    "noplaylist": False,
    "extract_flat": True,
    "playlistend": 200,  # Limit to 200 tracks
}

YDL_SEARCH_OPTS: dict[str, Any] = {
    **YDL_OPTS,
    "default_search": "ytsearch5",  # Return up to 5 results
}


def _extract_sync(url: str, opts: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Synchronous yt-dlp extraction. Runs in a thread pool."""
    use_opts = opts or YDL_OPTS
    try:
        with yt_dlp.YoutubeDL(use_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info
    except Exception as e:
        logger.error("yt-dlp extraction failed for {}: {}", url, e)
        return None


async def extract_info(url: str, opts: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Extract info from a URL asynchronously using yt-dlp.

    Results are cached for 10 minutes by URL.

    Args:
        url: The URL or search query to extract.
        opts: Optional yt-dlp options override.

    Returns:
        The extracted info dict, or None on failure.
    """
    # Check cache
    cache_key = url
    if cache_key in _extraction_cache:
        logger.debug("Cache hit for: {}", url[:80])
        return _extraction_cache[cache_key]

    loop = asyncio.get_running_loop()
    logger.debug("Extracting: {}", url[:80])

    info = await loop.run_in_executor(_thread_pool, _extract_sync, url, opts)

    if info is not None:
        _extraction_cache[cache_key] = info

    return info


async def search_track(query: str) -> Track | None:
    """Search for a single track by query and return a Track object.

    Args:
        query: Search query or URL.

    Returns:
        A Track object, or None if no results found.
    """
    # If it looks like a URL, extract directly
    if query.startswith(("http://", "https://")):
        info = await extract_info(query)
    else:
        info = await extract_info(f"ytsearch:{query}")

    if info is None:
        return None

    # Handle search results (entries list)
    if "entries" in info:
        entries = info["entries"]
        if not entries:
            return None
        info = entries[0]

    return _info_to_track(info)


async def extract_track_url(track: Track) -> str | None:
    """Get a fresh stream URL for a track.

    This re-extracts if the cached URL has expired, since YouTube
    stream URLs expire after a few hours.

    Args:
        track: The track to get a stream URL for.

    Returns:
        Direct audio stream URL, or None on failure.
    """
    info = await extract_info(track.url)
    if info is None:
        return None

    if "entries" in info:
        entries = info["entries"]
        if not entries:
            return None
        info = entries[0]

    return info.get("url")


async def extract_playlist(url: str) -> tuple[str, list[Track]]:
    """Extract all tracks from a playlist URL.

    Args:
        url: YouTube/SoundCloud playlist URL.

    Returns:
        Tuple of (playlist_name, list of Track objects) (up to 200).
    """
    info = await extract_info(url, opts=YDL_PLAYLIST_OPTS)
    if info is None:
        return "Imported Playlist", []

    # Get playlist title if available
    playlist_name = info.get("title", "Imported Playlist")

    entries = info.get("entries", [])
    tracks = []
    
    for entry in entries:
        if entry is None:
            continue
        track = _info_to_track(entry)
        if track:
            tracks.append(track)

    logger.info("Extracted {} tracks from playlist: {} ({})", len(tracks), playlist_name, url[:80])
    return playlist_name, tracks


async def get_related_tracks(video_id: str, limit: int = 5) -> list[Track]:
    """Get related tracks for Auto-DJ by fetching YouTube Mix.

    Args:
        video_id: YouTube video ID.
        limit: Max number of tracks to return.

    Returns:
        List of related Track objects.
    """
    mix_url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
    info = await extract_info(mix_url, opts=YDL_PLAYLIST_OPTS)
    if info is None:
        return []

    entries = info.get("entries", [])
    tracks = []
    for entry in entries:
        if entry is None:
            continue
        # Skip the original track
        if entry.get("id") == video_id:
            continue
        track = _info_to_track(entry)
        if track:
            tracks.append(track)
        if len(tracks) >= limit:
            break

    return tracks


def _info_to_track(info: dict[str, Any]) -> Track | None:
    """Convert a yt-dlp info dict to a Track object."""
    if info is None:
        return None

    title = info.get("title")
    url = info.get("webpage_url") or info.get("url") or info.get("id")
    if not title or not url:
        return None

    # For flat extractions, url might be just the video ID
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={url}"

    return Track(
        title=title,
        url=url,
        duration=info.get("duration"),
        source=info.get("extractor_key", "youtube").lower(),
        thumbnail=info.get("thumbnail"),
        stream_url=info.get("url") if info.get("url", "").startswith("http") else None,
    )


def shutdown_pool() -> None:
    """Shut down the extraction thread pool."""
    _thread_pool.shutdown(wait=False)


async def update_ytdlp() -> bool:
    """Auto-update yt-dlp to the latest version.

    Returns:
        True if update was successful or not needed, False on error.
    """
    loop = asyncio.get_running_loop()

    def _update() -> bool:
        try:
            import subprocess
            result = subprocess.run(
                ["pip", "install", "--upgrade", "yt-dlp"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning("Failed to auto-update yt-dlp: {}", e)
            return False

    return await loop.run_in_executor(None, _update)
