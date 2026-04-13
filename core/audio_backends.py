"""Audio backend implementations for native FFmpeg and Lavalink."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import discord
import wavelink
from loguru import logger

from core.errors import NothingPlaying, VoiceConnectionFailed
from core.extractor import extract_track_url
from core.ffmpeg_builder import build_ffmpeg_options
from core.filters import PresetDefinition, build_ffmpeg_filter_string, build_wavelink_filters
from core.track import Track

if TYPE_CHECKING:
    from config import BotConfig


class BackendUnavailable(VoiceConnectionFailed):
    """Raised when a backend cannot be used."""


class BaseAudioBackend(ABC):
    """Abstract audio backend contract."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._volume = 50
        self._preset_definition: PresetDefinition | None = None

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def voice_client(self): ...

    @property
    @abstractmethod
    def is_playing(self) -> bool: ...

    @property
    @abstractmethod
    def is_paused(self) -> bool: ...

    @property
    @abstractmethod
    def position_ms(self) -> int: ...

    @property
    def supports_filters(self) -> bool:
        return True

    async def set_filters(self, preset_definition: PresetDefinition | None) -> None:
        self._preset_definition = preset_definition

    @abstractmethod
    async def play(self, track: Track, seek: float | None = None) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def pause(self) -> None: ...

    @abstractmethod
    async def resume(self) -> None: ...

    @abstractmethod
    async def seek(self, position_ms: int) -> None: ...

    @abstractmethod
    async def set_volume(self, volume: int) -> None: ...

    @abstractmethod
    async def cleanup(self) -> None: ...

    @abstractmethod
    async def wait_for_track_end(self) -> Exception | None: ...


class FFmpegBackend(BaseAudioBackend):
    """Native FFmpeg audio backend using discord.py voice client."""

    def __init__(self, voice_client: discord.VoiceClient, config: BotConfig) -> None:
        super().__init__(config)
        self._vc = voice_client
        self._start_time: float = 0
        self._pause_start: float = 0
        self._total_paused: float = 0
        self._playing: bool = False
        self._paused: bool = False
        self._current_track: Track | None = None
        self._after_callback: asyncio.Future | None = None

    @property
    def name(self) -> str:
        return "ffmpeg"

    @property
    def voice_client(self) -> discord.VoiceClient:
        return self._vc

    @property
    def is_playing(self) -> bool:
        return self._playing and not self._paused

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def position_ms(self) -> int:
        if not self._playing:
            return 0
        elapsed = time.monotonic() - self._start_time - self._total_paused
        if self._paused:
            elapsed -= time.monotonic() - self._pause_start
        return int(elapsed * 1000)

    async def play(self, track: Track, seek: float | None = None) -> None:
        stream_url = track.stream_url or await extract_track_url(track)
        if not stream_url:
            raise VoiceConnectionFailed("Could not get audio stream URL")

        before_opts, options = build_ffmpeg_options(
            filter_string=build_ffmpeg_filter_string(self._preset_definition),
            seek_position=seek,
            volume=self._volume / 100.0,
        )

        source = discord.FFmpegPCMAudio(
            stream_url,
            executable=self.config.ffmpeg_path,
            before_options=before_opts,
            options=options,
        )

        loop = asyncio.get_running_loop()
        self._after_callback = loop.create_future()

        def after_playing(error):
            if error:
                logger.error("FFmpeg playback error: {}", error)
            self._playing = False
            self._paused = False
            if self._after_callback and not self._after_callback.done():
                loop.call_soon_threadsafe(self._after_callback.set_result, error)

        if self._vc.is_playing():
            self._vc.stop()

        self._vc.play(source, after=after_playing)
        self._playing = True
        self._paused = False
        self._start_time = time.monotonic()
        self._total_paused = 0
        self._current_track = track

        if seek:
            self._start_time -= seek

    async def stop(self) -> None:
        if self._vc.is_playing() or self._vc.is_paused():
            self._vc.stop()
        self._playing = False
        self._paused = False

    async def pause(self) -> None:
        if self._vc.is_playing():
            self._vc.pause()
            self._paused = True
            self._pause_start = time.monotonic()

    async def resume(self) -> None:
        if self._vc.is_paused():
            self._vc.resume()
            self._paused = False
            self._total_paused += time.monotonic() - self._pause_start

    async def seek(self, position_ms: int) -> None:
        if self._current_track is None:
            raise NothingPlaying()
        await self.play(self._current_track, seek=position_ms / 1000.0)

    async def set_volume(self, volume: int) -> None:
        self._volume = volume
        if self._playing and self._current_track:
            pos = self.position_ms
            await self.play(self._current_track, seek=pos / 1000.0)

    async def set_filters(self, preset_definition: PresetDefinition | None) -> None:
        await super().set_filters(preset_definition)
        if self._playing and self._current_track:
            pos = self.position_ms
            await self.play(self._current_track, seek=pos / 1000.0)

    async def cleanup(self) -> None:
        if self._vc.is_playing() or self._vc.is_paused():
            self._vc.stop()
        self._playing = False

    async def wait_for_track_end(self) -> Exception | None:
        if self._after_callback is None:
            return None
        return await self._after_callback


class LavalinkBackend(BaseAudioBackend):
    """Lavalink backend powered by Wavelink."""

    def __init__(self, voice_client: wavelink.Player, config: BotConfig) -> None:
        super().__init__(config)
        self._vc = voice_client
        self._current_track: Track | None = None
        self._after_callback: asyncio.Future | None = None

    @property
    def name(self) -> str:
        return "lavalink"

    @property
    def voice_client(self) -> wavelink.Player:
        return self._vc

    @property
    def is_playing(self) -> bool:
        return bool(self._vc.playing and not self._vc.paused)

    @property
    def is_paused(self) -> bool:
        return bool(self._vc.paused)

    @property
    def position_ms(self) -> int:
        return int(self._vc.position or 0)

    async def play(self, track: Track, seek: float | None = None) -> None:
        try:
            result = await wavelink.Playable.search(track.url, node=self._vc.node)
        except Exception as exc:
            raise BackendUnavailable(f"Lavalink search failed: {exc}") from exc

        playable = None
        if hasattr(result, "tracks"):
            playable = result.tracks[0] if result.tracks else None
        elif isinstance(result, list):
            playable = result[0] if result else None

        if playable is None:
            raise BackendUnavailable("Lavalink could not load the requested track")

        self._after_callback = asyncio.get_running_loop().create_future()
        self._current_track = track

        filters = build_wavelink_filters(self._preset_definition)
        try:
            await self._vc.play(
                playable,
                start=int((seek or 0) * 1000),
                volume=self._volume,
                filters=filters,
            )
        except Exception as exc:
            raise BackendUnavailable(f"Lavalink playback failed: {exc}") from exc

    async def stop(self) -> None:
        await self._vc.skip(force=True)

    async def pause(self) -> None:
        await self._vc.pause(True)

    async def resume(self) -> None:
        await self._vc.pause(False)

    async def seek(self, position_ms: int) -> None:
        if self._current_track is None:
            raise NothingPlaying()
        await self._vc.seek(position_ms)

    async def set_volume(self, volume: int) -> None:
        self._volume = volume
        await self._vc.set_volume(volume)

    async def set_filters(self, preset_definition: PresetDefinition | None) -> None:
        await super().set_filters(preset_definition)
        filters = build_wavelink_filters(self._preset_definition)
        await self._vc.set_filters(filters, seek=True)

    async def cleanup(self) -> None:
        await self._vc.disconnect()

    async def wait_for_track_end(self) -> Exception | None:
        if self._after_callback is None:
            return None
        return await self._after_callback

    def notify_track_end(self, error: Exception | None = None) -> None:
        """Resolve the current wait future from Wavelink event listeners."""
        if self._after_callback and not self._after_callback.done():
            self._after_callback.set_result(error)
