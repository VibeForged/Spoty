"""Builds FFmpeg command arguments for audio playback with filters."""

from __future__ import annotations


# Default FFmpeg options for Discord voice streaming
FFMPEG_BEFORE_OPTIONS = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
)

FFMPEG_OPTIONS = "-vn"  # No video


def build_ffmpeg_options(
    filter_string: str | None = None,
    seek_position: float | None = None,
    volume: float = 1.0,
) -> tuple[str, str]:
    """Build FFmpeg before_options and options strings.

    Args:
        filter_string: FFmpeg -af filter string (from filters.py).
        seek_position: Seek position in seconds (for mid-song FX changes).
        volume: Volume multiplier (1.0 = 100%).

    Returns:
        Tuple of (before_options, options) strings for FFmpegPCMAudio.
    """
    before_opts = FFMPEG_BEFORE_OPTIONS

    if seek_position is not None and seek_position > 0:
        before_opts = f"-ss {seek_position:.2f} {before_opts}"

    options_parts = ["-vn"]

    # Build audio filter chain
    af_parts: list[str] = []

    if filter_string:
        af_parts.append(filter_string)

    if volume != 1.0:
        af_parts.append(f"volume={volume:.2f}")

    if af_parts:
        options_parts.append(f'-af "{",".join(af_parts)}"')

    return before_opts, " ".join(options_parts)
