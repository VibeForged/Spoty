"""Custom exception hierarchy for the music bot."""

from __future__ import annotations

from discord.app_commands import AppCommandError


class MusicBotError(AppCommandError):
    """Base exception for all music bot errors."""

    def __init__(self, message: str = "An error occurred.") -> None:
        self.message = message
        super().__init__(message)


# --- Voice Errors ---


class VoiceError(MusicBotError):
    """Base exception for voice-related errors."""


class NotInVoiceChannelError(VoiceError):
    """User is not in a voice channel."""

    def __init__(self) -> None:
        super().__init__("You must be in a voice channel to use this command.")


class BotNotConnectedError(VoiceError):
    """Bot is not connected to a voice channel."""

    def __init__(self) -> None:
        super().__init__("I'm not connected to a voice channel.")


class DifferentVoiceChannelError(VoiceError):
    """User is in a different voice channel than the bot."""

    def __init__(self) -> None:
        super().__init__("You must be in the same voice channel as me.")


class VoiceConnectionFailedError(VoiceError):
    """Failed to connect to a voice channel."""

    def __init__(self, reason: str = "Unknown error") -> None:
        super().__init__(f"Failed to connect to voice channel: {reason}")


# --- Playback Errors ---


class PlaybackError(MusicBotError):
    """Base exception for playback-related errors."""


class TrackNotFoundError(PlaybackError):
    """No results found for a search query."""

    def __init__(self, query: str) -> None:
        super().__init__(f"No results found for: {query}")


class ExtractionFailedError(PlaybackError):
    """yt-dlp extraction failed."""

    def __init__(self, reason: str = "Unknown error") -> None:
        super().__init__(f"Failed to extract audio: {reason}")


class QueueEmptyError(PlaybackError):
    """Queue is empty."""

    def __init__(self) -> None:
        super().__init__("The queue is empty.")


class QueueFullError(PlaybackError):
    """Queue has reached its maximum size."""

    def __init__(self, max_size: int) -> None:
        super().__init__(f"The queue is full (max {max_size} tracks).")


class InvalidSeekPositionError(PlaybackError):
    """Invalid seek position."""

    def __init__(self) -> None:
        super().__init__("Invalid seek position. Use format like `1:30` or `90`.")


class NothingPlayingError(PlaybackError):
    """Nothing is currently playing."""

    def __init__(self) -> None:
        super().__init__("Nothing is currently playing.")


# --- Permission Errors ---


class PermissionError(MusicBotError):
    """Base exception for permission-related errors."""


class WrongChannelError(PermissionError):
    """Command used in the wrong channel."""

    def __init__(self, channel_id: int) -> None:
        super().__init__(f"This command can only be used in <#{channel_id}>.")


class DJRequiredError(PermissionError):
    """User needs DJ permissions."""

    def __init__(self) -> None:
        super().__init__("You need the DJ role to use this command.")


class AdminRequiredError(PermissionError):
    """User needs admin permissions."""

    def __init__(self) -> None:
        super().__init__("You need administrator permissions to use this command.")


# --- Playlist Errors ---


class PlaylistError(MusicBotError):
    """Base exception for playlist-related errors."""


class PlaylistNotFoundError(PlaylistError):
    """Playlist does not exist."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Playlist not found: {name}")


class PlaylistAlreadyExistsError(PlaylistError):
    """Playlist with this name already exists."""

    def __init__(self, name: str) -> None:
        super().__init__(f"A playlist named '{name}' already exists.")


class NotPlaylistOwnerError(PlaylistError):
    """User is not the owner of the playlist."""

    def __init__(self) -> None:
        super().__init__("You don't own this playlist.")


class PlaylistAccessDeniedError(PlaylistError):
    """User cannot access the requested playlist."""

    def __init__(self) -> None:
        super().__init__("You don't have access to that playlist.")


class InvalidPlaylistNameError(PlaylistError):
    """Playlist name is invalid."""

    def __init__(self, reason: str = "Playlist name must be 1-100 characters.") -> None:
        super().__init__(reason)


class InvalidPlaylistPositionError(PlaylistError):
    """Playlist track position is invalid."""

    def __init__(self, position: int) -> None:
        super().__init__(f"No track at position {position}.")


class PlaylistLimitExceededError(PlaylistError):
    """Playlist operation would exceed a configured limit."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"Playlist limit exceeded (max {limit} tracks).")


# --- FX Errors ---


class FXError(MusicBotError):
    """Base exception for audio effects errors."""


class PresetNotFoundError(FXError):
    """FX preset does not exist."""

    def __init__(self, name: str) -> None:
        super().__init__(f"FX preset not found: {name}")


class InvalidFilterStringError(FXError):
    """Invalid FFmpeg filter string."""

    def __init__(self) -> None:
        super().__init__("Invalid FFmpeg filter string.")


# --- Queue Lock ---


class QueueLockedError(MusicBotError):
    """Queue is locked to DJ-only additions."""

    def __init__(self) -> None:
        super().__init__("The queue is currently locked. Only DJs can add tracks.")
