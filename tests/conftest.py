"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_track():
    """Create a sample Track for testing."""
    from core.track import Track

    return Track(
        title="Test Song",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        duration=212,
        requester_id=123456789,
        requester_name="TestUser",
        source="youtube",
        thumbnail="https://img.youtube.com/vi/dQw4w9WgXcQ/0.jpg",
    )
