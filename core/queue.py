"""Music queue data structure with loop modes and shuffle support."""

from __future__ import annotations

import random
from collections import deque
from enum import Enum

from core.track import Track


class LoopMode(Enum):
    """Queue loop mode."""

    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


class MusicQueue:
    """Per-guild music queue with loop, shuffle, and positional operations.

    Uses a deque for O(1) popleft. Supports three loop modes:
    - OFF: tracks are consumed and discarded
    - TRACK: current track repeats indefinitely
    - QUEUE: finished tracks move to the back of the queue
    """

    def __init__(self, max_size: int = 500) -> None:
        self._tracks: deque[Track] = deque()
        self._history: deque[Track] = deque(maxlen=100)
        self._loop_mode: LoopMode = LoopMode.OFF
        self._max_size: int = max_size

    @property
    def loop_mode(self) -> LoopMode:
        return self._loop_mode

    @loop_mode.setter
    def loop_mode(self, mode: LoopMode) -> None:
        self._loop_mode = mode

    @property
    def tracks(self) -> list[Track]:
        """Return a copy of the queue as a list."""
        return list(self._tracks)

    @property
    def history(self) -> list[Track]:
        """Return a copy of the history as a list."""
        return list(self._history)

    @property
    def size(self) -> int:
        return len(self._tracks)

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def remaining_capacity(self) -> int:
        return max(0, self._max_size - len(self._tracks))

    @property
    def is_empty(self) -> bool:
        return len(self._tracks) == 0

    @property
    def is_full(self) -> bool:
        return len(self._tracks) >= self._max_size

    @property
    def total_duration(self) -> int:
        """Total duration of all tracks in the queue in seconds."""
        return int(sum(t.duration or 0 for t in self._tracks))

    def add(self, track: Track) -> int:
        """Add a track to the end of the queue. Returns the position."""
        if self.is_full:
            from core.errors import QueueFull
            raise QueueFull(self._max_size)
        self._tracks.append(track)
        return len(self._tracks)

    def add_top(self, track: Track) -> None:
        """Insert a track at the front of the queue (position 1)."""
        if self.is_full:
            from core.errors import QueueFull
            raise QueueFull(self._max_size)
        self._tracks.appendleft(track)

    def add_at(self, position: int, track: Track) -> None:
        """Insert a track at a specific position (0-indexed)."""
        if self.is_full:
            from core.errors import QueueFull
            raise QueueFull(self._max_size)
        position = max(0, min(position, len(self._tracks)))
        self._tracks.insert(position, track)

    def next(self, current: Track | None = None) -> Track | None:
        """Get the next track based on the current loop mode.

        Args:
            current: The currently playing track (needed for loop modes).

        Returns:
            The next track, or None if the queue is empty and not looping.
        """
        if self._loop_mode == LoopMode.TRACK and current is not None:
            return current

        if self._loop_mode == LoopMode.QUEUE and current is not None:
            self._tracks.append(current)

        if current is not None:
            self._history.appendleft(current)

        if self.is_empty:
            return None

        return self._tracks.popleft()

    def previous(self) -> Track | None:
        """Get the previous track from history."""
        if not self._history:
            return None
        return self._history.popleft()

    def peek(self) -> Track | None:
        """Peek at the next track without removing it."""
        if self.is_empty:
            return None
        return self._tracks[0]

    def get(self, index: int) -> Track | None:
        """Get a track at a specific index (0-indexed) without removing it."""
        if 0 <= index < len(self._tracks):
            return self._tracks[index]
        return None

    def remove(self, index: int) -> Track | None:
        """Remove and return a track at the given index (0-indexed)."""
        if 0 <= index < len(self._tracks):
            track = self._tracks[index]
            del self._tracks[index]
            return track
        return None

    def move(self, from_index: int, to_index: int) -> bool:
        """Move a track from one position to another (0-indexed)."""
        if not (0 <= from_index < len(self._tracks)):
            return False
        to_index = max(0, min(to_index, len(self._tracks) - 1))
        track = self._tracks[from_index]
        del self._tracks[from_index]
        self._tracks.insert(to_index, track)
        return True

    def shuffle(self) -> None:
        """Shuffle the queue in-place using Fisher-Yates."""
        tracks = list(self._tracks)
        random.shuffle(tracks)
        self._tracks = deque(tracks)

    def clear(self) -> int:
        """Clear all tracks from the queue. Returns the number of tracks cleared."""
        count = len(self._tracks)
        self._tracks.clear()
        return count

    def get_page(self, page: int, per_page: int = 10) -> tuple[list[Track], int]:
        """Get a page of tracks for display.

        Returns:
            Tuple of (tracks on this page, total pages).
        """
        tracks = list(self._tracks)
        total_pages = max(1, (len(tracks) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        end = start + per_page
        return tracks[start:end], total_pages
