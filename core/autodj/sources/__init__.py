"""Recommendation sources for Auto-DJ."""

from core.autodj.sources.base import RecommendationSource
from core.autodj.sources.history import HistorySource
from core.autodj.sources.lastfm import LastFmSource
from core.autodj.sources.search import SearchFallbackSource
from core.autodj.sources.youtube_mix import YouTubeMixSource

__all__ = [
    "RecommendationSource",
    "HistorySource",
    "LastFmSource",
    "SearchFallbackSource",
    "YouTubeMixSource",
]
