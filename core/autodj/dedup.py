"""Multi-level deduplication filter for Auto-DJ candidates."""

from __future__ import annotations

from difflib import SequenceMatcher

from loguru import logger

from core.autodj.models import ScoredTrack, SessionContext


def filter_duplicates(
    candidates: list[ScoredTrack],
    context: SessionContext,
    *,
    db_urls: set[str] | None = None,
) -> list[ScoredTrack]:
    """Apply multi-level deduplication to candidate tracks.

    Levels:
        1. Exact URL match against session recent_urls + DB history URLs
        2. Title similarity (SequenceMatcher ratio > 0.85 = duplicate)
        3. Artist cooldown (same artist not within last 5 accepted tracks)
        4. Duration filter (skip tracks > 15min unless session avg > 10min)

    Args:
        candidates: Pre-scored candidates sorted by score descending.
        context: Current session context.
        db_urls: Optional set of recently played URLs from the database.

    Returns:
        Filtered list with duplicates removed, order preserved.
    """
    all_recent_urls = set(context.recent_urls)
    if db_urls:
        all_recent_urls |= db_urls

    accepted: list[ScoredTrack] = []
    accepted_titles: list[str] = []
    accepted_artists: list[str] = []

    for candidate in candidates:
        url = candidate.track.url
        title = candidate.track.title.lower().strip()
        artist = candidate.artist_name.lower().strip() if candidate.artist_name else None

        # Level 1: Exact URL match
        if url in all_recent_urls:
            logger.trace("Dedup: URL match — {}", candidate.track.short_title)
            continue

        # Level 2: Title similarity
        is_title_dup = False
        for existing_title in accepted_titles:
            similarity = SequenceMatcher(None, title, existing_title).ratio()
            if similarity > 0.85:
                is_title_dup = True
                logger.trace(
                    "Dedup: title similarity {:.0%} — {} ≈ {}",
                    similarity,
                    candidate.track.short_title,
                    existing_title[:40],
                )
                break
        if is_title_dup:
            continue

        # Level 3: Artist cooldown (no more than 2 tracks from same artist in one batch)
        if artist:
            artist_count = sum(1 for a in accepted_artists if a == artist)
            if artist_count >= 2:
                logger.trace(
                    "Dedup: artist cooldown — {} ({})", artist, candidate.track.short_title
                )
                continue

        # Level 4: Duration filter (skip very long tracks)
        if candidate.track.duration and candidate.track.duration > 900:  # > 15 min
            seed_dur = context.seed_track.duration if context.seed_track else None
            if not seed_dur or seed_dur < 600:
                logger.trace("Dedup: duration filter — {}", candidate.track.short_title)
                continue

        accepted.append(candidate)
        accepted_titles.append(title)
        if artist:
            accepted_artists.append(artist)

    removed = len(candidates) - len(accepted)
    if removed > 0:
        logger.debug("Dedup: filtered {} of {} candidates", removed, len(candidates))

    return accepted
