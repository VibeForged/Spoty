"""Per-guild MusicPlayer class managing voice, queue, playback, and FX state."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Protocol

import discord
from loguru import logger

from core.errors import NothingPlaying, VoiceConnectionFailed
from core.extractor import extract_track_url
from core.ffmpeg_builder import build_ffmpeg_options
from core.filters import build_filter_chain
from core.queue import LoopMode, MusicQueue
from core.track import Track

if TYPE_CHECKING:
    from bot import MusicBot


class AudioBackend(Protocol):
    """Protocol for audio backends (FFmpeg native or Lavalink)."""

    async def play(self, track: Track, seek: float | None = None) -> None: ...
    async def stop(self) -> None: ...
    async def pause(self) -> None: ...
    async def resume(self) -> None: ...
    async def seek(self, position_ms: int) -> None: ...
    async def set_volume(self, volume: int) -> None: ...
    async def cleanup(self) -> None: ...
    @property
    def is_playing(self) -> bool: ...
    @property
    def is_paused(self) -> bool: ...
    @property
    def position_ms(self) -> int: ...


class FFmpegBackend:
    """Native FFmpeg audio backend using discord.py voice client."""

    def __init__(self, voice_client: discord.VoiceClient, config) -> None:
        self._vc = voice_client
        self._config = config
        self._start_time: float = 0
        self._pause_start: float = 0
        self._total_paused: float = 0
        self._playing: bool = False
        self._paused: bool = False
        self._current_track: Track | None = None
        self._after_callback: asyncio.Future | None = None
        self._filter_string: str | None = None

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
        """Play a track via FFmpeg."""
        # Get stream URL
        stream_url = track.stream_url or await extract_track_url(track)
        if not stream_url:
            raise VoiceConnectionFailed("Could not get audio stream URL")

        volume = getattr(self, "_volume", 50) / 100.0
        before_opts, options = build_ffmpeg_options(
            filter_string=self._filter_string,
            seek_position=seek,
            volume=volume,
        )

        source = discord.FFmpegPCMAudio(
            stream_url,
            executable=self._config.ffmpeg_path,
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
            # Resolve the future from the event loop thread
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
        # Volume changes require restarting the stream with new filter
        if self._playing and self._current_track:
            pos = self.position_ms
            await self.play(self._current_track, seek=pos / 1000.0)

    async def set_filters(self, filter_string: str | None) -> None:
        """Apply new FFmpeg filters. Restarts the stream at the current position."""
        self._filter_string = filter_string
        if self._playing and self._current_track:
            pos = self.position_ms
            await self.play(self._current_track, seek=pos / 1000.0)

    async def cleanup(self) -> None:
        if self._vc.is_playing() or self._vc.is_paused():
            self._vc.stop()
        self._playing = False

    async def wait_for_track_end(self) -> Exception | None:
        """Wait for the current track to finish playing."""
        if self._after_callback is None:
            return None
        return await self._after_callback


class MusicPlayer:
    """Per-guild music player managing queue, voice, and playback state.

    One instance per guild, stored in bot.players[guild_id].
    """

    def __init__(self, bot: MusicBot, guild_id: int, voice_client: discord.VoiceClient) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.voice_client = voice_client
        self.queue = MusicQueue()
        self.current: Track | None = None
        self.volume: int = 50
        self.active_filters: list[str] = []
        self.text_channel: discord.TextChannel | None = None

        # Internal state
        self._play_lock = asyncio.Lock()
        self._inactive_task: asyncio.Task | None = None
        self._destroyed = False
        self._play_task: asyncio.Task | None = None

        # Audio backend
        self._backend: FFmpegBackend = FFmpegBackend(voice_client, bot.config)
        self._backend._volume = self.volume

        logger.info("MusicPlayer created for guild {}", guild_id)

    @property
    def is_playing(self) -> bool:
        return self._backend.is_playing

    @property
    def is_paused(self) -> bool:
        return self._backend.is_paused

    @property
    def position_ms(self) -> int:
        return self._backend.position_ms

    async def play_next(self, error: Exception | None = None) -> None:
        """Play the next track in the queue.

        Called after a track finishes, on skip, or on initial play.
        """
        if self._destroyed:
            return

        async with self._play_lock:
            if error:
                logger.error("Playback error in guild {}: {}", self.guild_id, error)

            # Cancel inactivity timer
            self._cancel_inactive_timer()

            # Get next track from queue
            next_track = self.queue.next(self.current)

            if next_track is None:
                self.current = None
                # Start inactivity timer
                self._start_inactive_timer()

                # Try Auto-DJ if enabled
                if await self._try_auto_dj():
                    return

                logger.debug("Queue empty for guild {}", self.guild_id)
                return

            self.current = next_track
            logger.info("Playing: {} in guild {}", next_track.title[:60], self.guild_id)

            try:
                await self._backend.play(next_track)

                # Record in history
                from core.repositories import HistoryRepo, StatsRepo

                await HistoryRepo.add(
                    guild_id=self.guild_id,
                    track_title=next_track.title,
                    track_url=next_track.url,
                    duration=next_track.duration,
                    requested_by=next_track.requester_id or 0,
                )
                await StatsRepo.increment(self.guild_id, next_track.duration or 0)

                # Announce if enabled
                if self.text_channel:
                    settings = await self.bot.get_guild_settings(self.guild_id)
                    if settings and settings.announce_songs:
                        await self._send_now_playing()

            except Exception as e:
                logger.error("Failed to play track in guild {}: {}", self.guild_id, e)
                if self.text_channel:
                    await self.text_channel.send(
                        embed=discord.Embed(
                            title="Playback Error",
                            description=f"Failed to play **{next_track.short_title}**: {e}",
                            color=discord.Color.red(),
                        )
                    )
                # Try next track
                self.current = next_track  # Set so queue.next() can handle loop
                await self.play_next()
                return

            # Wait for track to finish and then play next
            self._play_task = asyncio.create_task(self._wait_and_play_next())

    async def _wait_and_play_next(self) -> None:
        """Wait for the current track to finish, then play next."""
        try:
            error = await self._backend.wait_for_track_end()
            if not self._destroyed:
                await self.play_next(error)
        except asyncio.CancelledError:
            pass

    async def skip(self) -> Track | None:
        """Skip the current track. Returns the skipped track."""
        skipped = self.current
        if self._play_task:
            self._play_task.cancel()
        await self._backend.stop()

        # If loop mode is TRACK, temporarily disable to actually skip
        was_track_loop = self.queue.loop_mode == LoopMode.TRACK
        if was_track_loop:
            self.queue.loop_mode = LoopMode.OFF

        await self.play_next()

        if was_track_loop:
            self.queue.loop_mode = LoopMode.TRACK

        return skipped

    async def stop(self) -> None:
        """Stop playback and clear the queue."""
        if self._play_task:
            self._play_task.cancel()
        await self._backend.stop()
        self.queue.clear()
        self.current = None
        self._start_inactive_timer()

    async def pause(self) -> None:
        await self._backend.pause()

    async def resume(self) -> None:
        await self._backend.resume()

    async def seek(self, position_ms: int) -> None:
        await self._backend.seek(position_ms)

    async def set_volume(self, volume: int) -> None:
        self.volume = max(0, min(volume, 200))
        self._backend._volume = self.volume
        await self._backend.set_volume(self.volume)

    async def apply_filters(self, preset_names: list[str]) -> None:
        """Apply FX presets to current playback.

        Rebuilds the audio source at the current position with the new filter chain.
        """
        self.active_filters = preset_names

        if preset_names:
            # Get custom presets from DB
            from core.repositories import FXPresetRepo

            custom_presets_db = await FXPresetRepo.list_for_guild(self.guild_id)
            custom = {p.name: p.filter_string for p in custom_presets_db}
            filter_string = build_filter_chain(preset_names, custom)
        else:
            filter_string = None

        await self._backend.set_filters(filter_string)

    async def _send_now_playing(self) -> None:
        """Send a now playing embed to the text channel."""
        if not self.text_channel or not self.current:
            return

        track = self.current
        embed = discord.Embed(
            title="Now Playing",
            description=f"**[{track.title}]({track.url})**",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Duration", value=track.duration_str, inline=True)
        if track.requester_name != "Unknown":
            embed.add_field(name="Requested by", value=track.requester_name, inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)

        await self.text_channel.send(embed=embed)

    async def _try_auto_dj(self) -> bool:
        """Try to fetch related tracks for Auto-DJ. Returns True if tracks were added."""
        settings = await self.bot.get_guild_settings(self.guild_id)
        if not settings or not settings.autoplay:
            return False

        # Get the last played track from history
        history = self.queue.history
        if not history:
            return False

        last_track = history[0]
        # Extract video ID from YouTube URL
        video_id = _extract_video_id(last_track.url)
        if not video_id:
            return False

        logger.info("Auto-DJ: fetching related tracks for {}", video_id)

        from core.extractor import get_related_tracks

        related = await get_related_tracks(video_id, limit=3)

        # Filter out recently played
        recent_urls = {t.url for t in history[:50]}
        new_tracks = [t for t in related if t.url not in recent_urls]

        if not new_tracks:
            logger.debug("Auto-DJ: no new related tracks found")
            return False

        for track in new_tracks:
            track.requester_name = "Auto-DJ"
            self.queue.add(track)

        logger.info("Auto-DJ: added {} tracks to queue", len(new_tracks))
        await self.play_next()
        return True

    def _start_inactive_timer(self) -> None:
        """Start the inactivity disconnect timer."""
        self._cancel_inactive_timer()
        timeout = 300  # Default 5 minutes
        self._inactive_task = asyncio.create_task(self._inactive_disconnect(timeout))

    def _cancel_inactive_timer(self) -> None:
        """Cancel the inactivity disconnect timer."""
        if self._inactive_task and not self._inactive_task.done():
            self._inactive_task.cancel()
            self._inactive_task = None

    async def _inactive_disconnect(self, timeout: int) -> None:
        """Disconnect after timeout seconds of inactivity."""
        try:
            await asyncio.sleep(timeout)
            if not self._destroyed and not self.is_playing:
                logger.info("Inactivity timeout for guild {}, disconnecting", self.guild_id)
                await self.destroy()
        except asyncio.CancelledError:
            pass

    async def destroy(self) -> None:
        """Destroy the player and disconnect from voice."""
        if self._destroyed:
            return
        self._destroyed = True

        self._cancel_inactive_timer()
        if self._play_task:
            self._play_task.cancel()

        await self._backend.cleanup()

        if self.voice_client and self.voice_client.is_connected():
            await self.voice_client.disconnect()

        # Remove from bot's player dict
        self.bot.players.pop(self.guild_id, None)
        logger.info("MusicPlayer destroyed for guild {}", self.guild_id)


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from a URL."""
    import re

    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None
