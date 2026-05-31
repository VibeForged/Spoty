"""Abstract base class for all recommendation sources."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.autodj.models import SessionContext, SourceResult


class RecommendationSource(ABC):
    """Base class for Auto-DJ recommendation sources.

    Each source is responsible for fetching candidate tracks from a single
    upstream provider (YouTube Mix, Last.fm, guild history, etc.).
    """

    name: str = "base"
    weight: float = 1.0  # Base weight applied to all tracks from this source
    timeout: float = 8.0  # Per-source timeout in seconds

    @abstractmethod
    async def fetch(self, context: SessionContext) -> SourceResult:
        """Fetch candidate tracks from this source.

        Args:
            context: The current Auto-DJ session context.

        Returns:
            A SourceResult containing scored candidates.
        """
