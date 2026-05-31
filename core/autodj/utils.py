"""Utility helpers shared across Auto-DJ components."""

from __future__ import annotations

import re


def parse_artist_title(raw_title: str) -> tuple[str | None, str]:
    """Extract artist and title from common YouTube title formats.

    Handles patterns like:
        "Artist - Title (Official Video)"
        "Artist — Title [Lyrics]"
        "Artist | Title"

    Returns:
        (artist, clean_title) or (None, raw_title) if unparseable.
    """
    # Common suffixes to strip
    _SUFFIXES = [
        "(Official Video)",
        "(Official Music Video)",
        "(Official Audio)",
        "(Lyrics)",
        "(Lyric Video)",
        "(Audio)",
        "(Visualizer)",
        "(Performance Video)",
        "[Official Video]",
        "[Official Music Video]",
        "[Official Audio]",
        "[Lyrics]",
        "[Audio]",
        "(HD)",
        "(HQ)",
        "| Official Video",
        "| Official Music Video",
    ]

    cleaned = raw_title.strip()
    for suffix in _SUFFIXES:
        cleaned = cleaned.replace(suffix, "").strip()

    # Also strip trailing year patterns like "(2024)" or "[2023]"
    cleaned = re.sub(r"[\(\[]\d{4}[\)\]]$", "", cleaned).strip()

    # Try "Artist - Title" (most common)
    for sep in (" - ", " – ", " — ", " | "):
        if sep in cleaned:
            parts = cleaned.split(sep, 1)
            artist = parts[0].strip()
            title = parts[1].strip()
            if artist and title:
                return artist, title

    return None, cleaned


def extract_keywords(title: str) -> str:
    """Extract search-friendly keywords from a track title.

    Strips common noise words, punctuation, and parenthetical content.
    Used by SearchFallbackSource to build YouTube search queries.
    """
    artist, clean_title = parse_artist_title(title)

    # Remove parenthetical content
    text = re.sub(r"[\(\[][^\)\]]*[\)\]]", "", clean_title).strip()

    # Remove special characters
    text = re.sub(r"[^\w\s]", " ", text).strip()

    # Remove common noise words
    noise = {"official", "video", "audio", "lyrics", "hd", "hq", "ft", "feat", "featuring", "music"}
    words = [w for w in text.lower().split() if w not in noise and len(w) > 1]

    if artist:
        artist_clean = re.sub(r"[^\w\s]", " ", artist).strip()
        keywords = f"{artist_clean} {' '.join(words)}"
    else:
        keywords = " ".join(words)

    return keywords.strip()
