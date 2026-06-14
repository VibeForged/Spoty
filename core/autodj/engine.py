"""Auto-DJ engine — main orchestrator for intelligent autoplay.

Manages per-guild sessions, coordinates recommendation sources,
and handles the full pipeline: fetch → score → filter → inject.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from loguru import logger

from core.autodj.dedup import filter_duplicates
from core.autodj.models import ScoredTrack, SessionContext, SourceResult
from core.autodj.scorer import score_candidates
from core.autodj.sources.history import HistorySource
from core.autodj.sources.lastfm import LastFmSource
from core.autodj.sources.search import SearchFallbackSource
from core.autodj.sources.youtube_mix import YouTubeMixSource
from core.autodj.utils import parse_artist_title
from core.track import Track

if TYPE_CHECKING:
    from core.autodj.sources.base import RecommendationSource
    from core.queue import MusicQueue


class AutoDJEngine:
    """Central orchestrator for the Auto-DJ recommendation system.

    Maintains per-guild sessions and coordinates the recommendation pipeline:
        1. Build/update session context
        2. Fetch candidates from all sources in parallel
        3. Score and rank candidates
        4. Filter duplicates
        5. Return top picks for queue injection
    """

    # Circuit breaker: after this many consecutive failures, pause a source for the cooldown.
    _BREAKER_THRESHOLD = 3
    _BREAKER_COOLDOWN = 300.0  # seconds

    def __init__(self) -> None:
        self._sessions: dict[int, SessionContext] = {}
        self._sources: list[RecommendationSource] = [
            YouTubeMixSource(),
            LastFmSource(),
            HistorySource(),
            SearchFallbackSource(),
        ]
        # Per-source circuit-breaker state.
        self._source_fail_counts: dict[str, int] = {}
        self._source_open_until: dict[str, float] = {}

    def _source_available(self, name: str) -> bool:
        """Whether a source is allowed to run (not currently paused by the breaker)."""
        return time.monotonic() >= self._source_open_until.get(name, 0.0)

    def _record_source_outcome(self, name: str, *, success: bool) -> None:
        """Update breaker state after a source responds or fails."""
        if success:
            self._source_fail_counts[name] = 0
            self._source_open_until.pop(name, None)
            return
        count = self._source_fail_counts.get(name, 0) + 1
        self._source_fail_counts[name] = count
        if count >= self._BREAKER_THRESHOLD:
            self._source_open_until[name] = time.monotonic() + self._BREAKER_COOLDOWN
            logger.info(
                "Auto-DJ: pausing source '{}' for {:.0f}s after {} consecutive failures",
                name,
                self._BREAKER_COOLDOWN,
                count,
            )

    def get_session(self, guild_id: int) -> SessionContext | None:
        """Get the current session for a guild, if one exists."""
        return self._sessions.get(guild_id)

    async def get_or_create_session(
        self, guild_id: int, seed_track: Track | None = None
    ) -> SessionContext:
        """Get or create an Auto-DJ session for a guild."""
        session = self._sessions.get(guild_id)

        if session is None or session.should_reset():
            if session and session.should_reset():
                logger.info(
                    "Auto-DJ: resetting stale session for guild {} (served {})",
                    guild_id,
                    session.tracks_served,
                )
            session = SessionContext(guild_id=guild_id, seed_track=seed_track)

            # Load persistent learning signals from database
            try:
                from core.repositories import AutoDJFeedbackRepo

                signals = await AutoDJFeedbackRepo.get_signals_for_session(guild_id)
                for s in signals:
                    if s.signal == "skip":
                        session.skip_signals[s.track_url] = (
                            session.skip_signals.get(s.track_url, 0) + 1
                        )
                        if s.artist_hint:
                            artist_lower = s.artist_hint.lower().strip()
                            session.skip_artists[artist_lower] = (
                                session.skip_artists.get(artist_lower, 0) + 1
                            )
                    elif s.signal == "complete":
                        session.completion_signals[s.track_url] = (
                            session.completion_signals.get(s.track_url, 0) + 1
                        )
                        if s.artist_hint:
                            artist_lower = s.artist_hint.lower().strip()
                            session.completion_artists[artist_lower] = (
                                session.completion_artists.get(artist_lower, 0) + 1
                            )
            except Exception:
                logger.debug(
                    "Auto-DJ: failed to load persistent signals for guild {}",
                    guild_id,
                    exc_info=True,
                )

            self._sessions[guild_id] = session
        elif seed_track:
            session.seed_track = seed_track

        return session

    def destroy_session(self, guild_id: int) -> None:
        """Remove the session for a guild (e.g., on disconnect)."""
        self._sessions.pop(guild_id, None)

    async def get_recommendations(
        self,
        guild_id: int,
        seed_track: Track,
        queue: MusicQueue,
        *,
        db_recent_urls: set[str] | None = None,
    ) -> list[Track]:
        """Run the full recommendation pipeline and return tracks to add.

        Args:
            guild_id: The guild requesting recommendations.
            seed_track: The track to base recommendations on (usually last played).
            queue: The current music queue (used for batch sizing).
            db_recent_urls: Optional set of recently played URLs from DB for dedup.

        Returns:
            List of Track objects ready to add to the queue (may be empty).
        """
        session = await self.get_or_create_session(guild_id, seed_track)

        # Phase 1: Update context with seed track info
        artist, _ = parse_artist_title(seed_track.title)
        if artist:
            session.record_artist(artist)
        session.record_played_url(seed_track.url)

        # Phase 2: Fetch candidates from all sources in parallel
        candidates = await self._fetch_all_sources(session)

        if not candidates:
            logger.info("Auto-DJ: no candidates from any source for guild {}", guild_id)
            return []

        # Phase 3: Score candidates
        scored = score_candidates(candidates, session)

        # Phase 4: Filter duplicates
        filtered = filter_duplicates(scored, session, db_urls=db_recent_urls)

        if not filtered:
            logger.info("Auto-DJ: all candidates filtered out for guild {}", guild_id)
            return []

        # Phase 5: Select top picks based on dynamic batch size
        batch_size = self._calculate_batch_size(queue, session)
        top_picks = filtered[:batch_size]

        # Update session state
        for pick in top_picks:
            session.record_played_url(pick.track.url)
            if pick.artist_name:
                session.record_artist(pick.artist_name)
            session.tracks_served += 1

        logger.info(
            "Auto-DJ: selected {} tracks for guild {} (batch_size={}, candidates={}, filtered={})",
            len(top_picks),
            guild_id,
            batch_size,
            len(candidates),
            len(filtered),
        )

        return [pick.track for pick in top_picks]

    async def record_skip(self, guild_id: int, track: Track) -> None:
        """Record that a track was skipped (negative signal)."""
        session = self._sessions.get(guild_id)
        artist, _ = parse_artist_title(track.title)
        if session:
            session.record_skip(track.url, artist)

        from core.repositories import AutoDJFeedbackRepo

        await AutoDJFeedbackRepo.add_signal(
            guild_id=guild_id,
            track_url=track.url,
            signal="skip",
            source=track.source or "unknown",
            artist_hint=artist,
        )

    async def record_completion(self, guild_id: int, track: Track) -> None:
        """Record that a track played to completion (positive signal)."""
        session = self._sessions.get(guild_id)
        artist, _ = parse_artist_title(track.title)
        if session:
            session.record_completion(track.url, artist)

        from core.repositories import AutoDJFeedbackRepo

        await AutoDJFeedbackRepo.add_signal(
            guild_id=guild_id,
            track_url=track.url,
            signal="complete",
            source=track.source or "unknown",
            artist_hint=artist,
        )

    async def _fetch_all_sources(self, context: SessionContext) -> list[ScoredTrack]:
        """Fetch candidates from available sources in parallel with individual timeouts."""
        # Skip any source the circuit breaker has temporarily paused.
        active = [s for s in self._sources if self._source_available(s.name)]
        tasks = [
            asyncio.create_task(self._fetch_with_timeout(s, context), name=f"autodj-{s.name}")
            for s in active
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_candidates: list[ScoredTrack] = []
        for source, result in zip(active, results, strict=False):
            if isinstance(result, Exception):
                # Timeouts surface here too (wait_for raises TimeoutError).
                self._record_source_outcome(source.name, success=False)
                logger.warning("Auto-DJ: source '{}' failed: {}", source.name, result)
                continue

            self._record_source_outcome(source.name, success=True)
            if result.tracks:
                logger.debug(
                    "Auto-DJ: source '{}' returned {} candidates (confidence={:.1f}, latency={:.0f}ms)",
                    source.name,
                    len(result.tracks),
                    result.confidence,
                    result.latency_ms,
                )
                all_candidates.extend(result.tracks)

        # Merge duplicates across sources — boost score for tracks found by multiple sources
        seen_urls: dict[str, ScoredTrack] = {}
        merged: list[ScoredTrack] = []
        for candidate in all_candidates:
            url = candidate.track.url
            if url in seen_urls:
                # Boost: found by multiple sources = more relevant
                seen_urls[url].score += 0.15
            else:
                seen_urls[url] = candidate
                merged.append(candidate)

        return merged

    async def _fetch_with_timeout(
        self, source: RecommendationSource, context: SessionContext
    ) -> SourceResult:
        """Fetch from a single source with a timeout guard.

        A timeout raises ``TimeoutError`` so the caller records it as a failure
        for the circuit breaker.
        """
        return await asyncio.wait_for(source.fetch(context), timeout=source.timeout)

    @staticmethod
    def _calculate_batch_size(queue: MusicQueue, session: SessionContext) -> int:
        """Determine how many tracks to add based on queue state and session age."""
        if queue.size == 0 and session.tracks_served == 0:
            return 3  # First autoplay trigger — add a small starter batch
        if queue.size == 0:
            return 2  # Subsequent triggers — smaller for freshness
        if queue.size <= 2:
            return 1  # Pre-fill — just keep a buffer
        return 0  # Queue is healthy, no action needed
