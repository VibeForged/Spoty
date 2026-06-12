"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import pytest

from core.track import Track


@pytest.fixture
def sample_track():
    """Create a sample Track for testing."""
    return Track(
        title="Test Song",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        duration=212,
        requester_id=123456789,
        requester_name="TestUser",
        source="youtube",
        thumbnail="https://img.youtube.com/vi/dQw4w9WgXcQ/0.jpg",
    )


@pytest.fixture
async def db():
    """Initialize an in-memory SQLite database for testing."""
    from core.database import close_db, init_db

    await init_db("sqlite+aiosqlite:///:memory:", create_schema=True)
    yield
    await close_db()
