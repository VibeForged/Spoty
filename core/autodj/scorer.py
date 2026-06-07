"""Composite scoring logic for Auto-DJ track candidates."""

from __future__ import annotations

from loguru import logger

from core.autodj.models import ScoredTrack, SessionContext


def score_candidates(candidates: list[ScoredTrack], context: SessionContext) -> list[ScoredTrack]:
    """Apply composite scoring to all candidates and return sorted by score (descending).

    Score formula per track:
        base_score (from source weight)
        + artist_diversity_bonus  (+0.3 if artist not in recent 10)
        + recency_bonus           (+0.2 if URL not recently played)
        + duration_match_bonus    (+0.1 if duration within ±50% of seed)
        - skip_penalty            (-0.15 per skip of this URL)
        - artist_skip_penalty     (-0.05 per skip of any track by this artist)
        + completion_bonus        (+0.1 if this artist's tracks usually complete)
    """
    if not candidates:
        return []

    seed_duration = None
    if context.seed_track and context.seed_track.duration:
        seed_duration = context.seed_track.duration

    recent_artists_lower = set(context.recent_artists)

    # Build per-artist skip/completion counts from signals
    artist_skip_counts: dict[str, int] = {}
    artist_complete_counts: dict[str, int] = {}
    for url, count in context.skip_signals.items():
        # We don't have artist for every URL in signals, so this is best-effort
        artist_skip_counts[url] = count
    for url, count in context.completion_signals.items():
        artist_complete_counts[url] = count

    for candidate in candidates:
        score = candidate.score  # Start with base source weight

        artist_lower = candidate.artist_name.lower().strip() if candidate.artist_name else None

        # Artist diversity bonus
        if artist_lower and artist_lower not in recent_artists_lower:
            score += 0.3
        elif artist_lower:
            # Penalize repeated artists proportionally to how recently they appeared
            recent_list = list(context.recent_artists)
            try:
                idx = recent_list.index(artist_lower)
                # More recent = bigger penalty (idx 0 = most recent)
                penalty = 0.15 * (1.0 - idx / max(len(recent_list), 1))
                score -= penalty
            except ValueError:
                pass

        # Recency bonus (not recently played)
        if candidate.track.url not in context.recent_urls:
            score += 0.2

        # Duration compatibility
        if seed_duration and candidate.track.duration:
            ratio = candidate.track.duration / seed_duration
            if 0.5 <= ratio <= 2.0:
                score += 0.1
            elif ratio > 3.0 or ratio < 0.25:
                score -= 0.1  # Very different duration = slight penalty

        # Skip penalty for this specific URL
        url_skip_count = context.skip_signals.get(candidate.track.url, 0)
        if url_skip_count > 0:
            score -= 0.15 * url_skip_count

        # Completion bonus
        url_complete_count = context.completion_signals.get(candidate.track.url, 0)
        if url_complete_count > 0:
            score += 0.1

        # Filter out very short tracks (< 30s) unless seed is also short
        if candidate.track.duration and candidate.track.duration < 30 and (not seed_duration or seed_duration >= 60):
            score -= 0.5

        # Filter out live streams
        if candidate.track.duration is None:
            score -= 0.3

        candidate.score = max(score, 0.0)

    # Sort descending by score
    candidates.sort(key=lambda c: c.score, reverse=True)

    if candidates:
        logger.debug(
            "Scoring: top={} (score={:.2f}), bottom={} (score={:.2f}), total={}",
            candidates[0].track.short_title,
            candidates[0].score,
            candidates[-1].track.short_title,
            candidates[-1].score,
            len(candidates),
        )

    return candidates
