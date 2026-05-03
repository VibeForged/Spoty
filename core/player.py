"""Per-guild MusicPlayer class managing voice, queue, playback, and FX state."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

import discord
from loguru import logger

from core.audio_backends import BackendUnavailable, BaseAudioBackend, LavalinkBackend
from core.filters import PresetDefinition, combine_preset_definitions, preset_requires_ffmpeg
from core.queue import LoopMode, MusicQueue
from core.track import Track

if TYPE_CHECKING:
    from bot import MusicBot


class MusicPlayer:
    """Per-guild music player managing queue, voice, and playback state."""

    def __init__(self, bot: MusicBot, guild_id: int, backend: BaseAudioBackend) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self._backend = backend
        self.queue = MusicQueue()
        self.current: Track | None = None
        self.volume: int = 50
        self.active_filters: list[str] = []
        self._active_preset_definition: PresetDefinition | None = None
        self.text_channel: discord.TextChannel | None = None
        self._play_lock = asyncio.Lock()
        self._inactive_task: asyncio.Task | None = None
        self._destroyed = False
        self._play_task: asyncio.Task | None = None
        self._fallback_announced = False
        self._backend_switch_in_progress = False
        self._consecutive_failures = 0
        self._backend._volume = self.volume
        logger.info("MusicPlayer created for guild {} using {}", guild_id, self.backend_name)

    @property
    def voice_client(self):
        return self._backend.voice_client

    @property
    def is_connected(self) -> bool:
        return self._backend.is_connected

    @property
    def backend_name(self) -> str:
        return self._backend.name

    @property
    def is_playing(self) -> bool:
        return self._backend.is_playing

    @property
    def is_paused(self) -> bool:
        return self._backend.is_paused

    @property
    def position_ms(self) -> int:
        return self._backend.position_ms

    @classmethod
    async def create(
        cls,
        bot: MusicBot,
        guild_id: int,
        channel: discord.VoiceChannel,
    ) -> MusicPlayer:
        backend = await bot.backend_manager.connect_preferred(channel)
        player = cls(bot, guild_id, backend)
        settings = await bot.get_guild_settings(guild_id)
        if settings:
            player.volume = settings.default_volume
            await player._backend.set_volume(settings.default_volume)
        return player

    async def play_next(self, error: Exception | None = None) -> None:
        """Play the next track in the queue."""
        if self._destroyed:
            return

        async with self._play_lock:
            if error:
                logger.error("Playback error in guild {}: {}", self.guild_id, error)

            self._cancel_inactive_timer()
            next_track = self.queue.next(self.current)

            if next_track is None:
                self.current = None
                self._start_inactive_timer()
                if await self._try_auto_dj():
                    return
                logger.debug("Queue empty for guild {}", self.guild_id)
                return

            self.current = next_track
            logger.info(
                "Playing: {} in guild {} via {}",
                next_track.title[:60],
                self.guild_id,
                self.backend_name,
            )

            try:
                await self._backend.play(next_track)
                self._consecutive_failures = 0
                await self._record_track_play(next_track)
            except BackendUnavailable as exc:
                if await self._try_fallback(exc, next_track):
                    return
                await self._handle_track_failure(next_track, exc)
                return
            except Exception as exc:
                await self._handle_track_failure(next_track, exc)
                return

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
        skipped = self.current
        if self._play_task:
            self._play_task.cancel()
        await self._backend.stop()

        was_track_loop = self.queue.loop_mode == LoopMode.TRACK
        if was_track_loop:
            self.queue.loop_mode = LoopMode.OFF

        await self.play_next()

        if was_track_loop:
            self.queue.loop_mode = LoopMode.TRACK

        return skipped

    async def stop(self) -> None:
        if self._play_task:
            self._play_task.cancel()
        await self._backend.stop()
        self.queue.clear()
        self.current = None
        self._start_inactive_timer()

    async def pause(self) -> None:
        await self._run_backend_action("pause")

    async def resume(self) -> None:
        await self._run_backend_action("resume")

    async def seek(self, position_ms: int) -> None:
        await self._run_backend_action("seek", position_ms)

    async def set_volume(self, volume: int) -> None:
        self.volume = max(0, min(volume, 200))
        await self._run_backend_action("set_volume", self.volume)

    async def apply_filters(self, preset_names: list[str]) -> None:
        self.active_filters = preset_names
        if preset_names:
            from core.repositories import FXPresetRepo

            custom_presets_db = await FXPresetRepo.list_for_guild(self.guild_id)
            custom = {}
            for preset in custom_presets_db:
                definition = FXPresetRepo.get_definition(preset)
                if definition is not None:
                    custom[preset.name] = definition
            preset_definition = combine_preset_definitions(preset_names, custom)
        else:
            preset_definition = None

        if preset_definition and preset_requires_ffmpeg(preset_definition) and self.backend_name == "lavalink":
            await self._switch_to_ffmpeg("Selected FX requires FFmpeg-compatible playback")

        self._active_preset_definition = preset_definition
        await self._run_backend_action("set_filters", preset_definition)

    async def handle_lavalink_event(self, error: Exception | None = None) -> None:
        """Resolve Lavalink playback waiters from bot event listeners."""
        if isinstance(self._backend, LavalinkBackend):
            self._backend.notify_track_end(error)

    async def _run_backend_action(self, method_name: str, *args) -> None:
        if self._backend_switch_in_progress:
            logger.warning("Backend switch in progress, skipping {}", method_name)
            return
        try:
            await getattr(self._backend, method_name)(*args)
        except BackendUnavailable as exc:
            await self._switch_to_ffmpeg(str(exc), resume_position_ms=self.position_ms)
            await getattr(self._backend, method_name)(*args)

    async def _switch_to_ffmpeg(
        self,
        reason: str,
        *,
        resume_position_ms: int | None = None,
        record_current: bool = False,
    ) -> None:
        """Switch this guild to the FFmpeg fallback backend."""
        if self.backend_name == "ffmpeg":
            return

        channel = self.voice_client.channel
        logger.warning("Falling back to FFmpeg in guild {}: {}", self.guild_id, reason)

        old_backend = self._backend
        self._backend_switch_in_progress = True
        try:
            # Cancel active play task FIRST
            if self._play_task:
                self._play_task.cancel()
                self._play_task = None

            # Resolve orphaned futures
            old_backend.cancel_waiters()

            try:
                await old_backend.cleanup()
            except Exception:
                logger.debug("Ignored cleanup failure during fallback", exc_info=True)

            new_backend = await self.bot.backend_manager.fallback_backend(channel)
            self._backend = new_backend
            self._backend._volume = self.volume
            if self._active_preset_definition:
                await self._backend.set_filters(self._active_preset_definition)
            await self._backend.set_volume(self.volume)
        finally:
            self._backend_switch_in_progress = False

        if self.current:
            await self._backend.play(self.current, seek=(resume_position_ms or 0) / 1000.0)
            if record_current:
                await self._record_track_play(self.current)
            self._play_task = asyncio.create_task(self._wait_and_play_next())

        if self.text_channel and not self._fallback_announced:
            await self.text_channel.send(
                embed=discord.Embed(
                    title="Audio Backend Fallback",
                    description="Lavalink became unavailable, so playback switched to FFmpeg automatically.",
                    color=discord.Color.orange(),
                )
            )
            self._fallback_announced = True

    async def _try_fallback(self, error: Exception, track: Track) -> bool:
        """Attempt automatic fallback from Lavalink to FFmpeg."""
        if self.backend_name != "lavalink":
            return False

        resume_position_ms = self.position_ms if self.current else 0
        await self._switch_to_ffmpeg(
            str(error),
            resume_position_ms=resume_position_ms,
            record_current=True,
        )
        return True

    async def _record_track_play(self, track: Track) -> None:
        from core.repositories import HistoryRepo, StatsRepo

        await HistoryRepo.add(
            guild_id=self.guild_id,
            track_title=track.title,
            track_url=track.url,
            duration=track.duration,
            requested_by=track.requester_id or 0,
        )
        await StatsRepo.increment(self.guild_id, track.duration or 0)

        if self.text_channel:
            settings = await self.bot.get_guild_settings(self.guild_id)
            if settings and settings.announce_songs:
                await self._send_now_playing()

    async def _handle_track_failure(self, track: Track, error: Exception) -> None:
        self._consecutive_failures += 1
        logger.error(
            "Failed to play track in guild {}: {} (consecutive: {})",
            self.guild_id, error, self._consecutive_failures,
        )
        if self._consecutive_failures >= 3:
            logger.error("Too many consecutive failures in guild {}, stopping", self.guild_id)
            self.current = None
            if self.text_channel:
                await self.text_channel.send(
                    embed=discord.Embed(
                        title="Playback Error",
                        description="Too many consecutive playback failures. Stopping.",
                        color=discord.Color.red(),
                    )
                )
            self._start_inactive_timer()
            return
        if self.text_channel:
            await self.text_channel.send(
                embed=discord.Embed(
                    title="Playback Error",
                    description=f"Failed to play **{track.short_title}**: {error}",
                    color=discord.Color.red(),
                )
            )
        self.current = track
        await self.play_next()

    async def _send_now_playing(self) -> None:
        if not self.text_channel or not self.current:
            return

        track = self.current
        embed = discord.Embed(
            title="Now Playing",
            description=f"**[{track.title}]({track.url})**",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Duration", value=track.duration_str, inline=True)
        embed.add_field(name="Backend", value=self.backend_name, inline=True)
        if track.requester_name != "Unknown":
            embed.add_field(name="Requested by", value=track.requester_name, inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)

        await self.text_channel.send(embed=embed)

    async def _try_auto_dj(self) -> bool:
        settings = await self.bot.get_guild_settings(self.guild_id)
        if not settings or not settings.autoplay:
            return False

        history = self.queue.history
        if not history:
            return False

        last_track = history[0]
        video_id = _extract_video_id(last_track.url)
        if not video_id:
            return False

        logger.info("Auto-DJ: fetching related tracks for {}", video_id)

        from core.extractor import get_related_tracks

        related = await get_related_tracks(video_id, limit=3)
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
        self._cancel_inactive_timer()
        timeout = 300
        self._inactive_task = asyncio.create_task(self._inactive_disconnect(timeout))

    def _cancel_inactive_timer(self) -> None:
        if self._inactive_task and not self._inactive_task.done():
            self._inactive_task.cancel()
            self._inactive_task = None

    async def _inactive_disconnect(self, timeout: int) -> None:
        try:
            await asyncio.sleep(timeout)
            if not self._destroyed and not self.is_playing:
                logger.info("Inactivity timeout for guild {}, disconnecting", self.guild_id)
                await self.destroy()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Error in inactive disconnect", exc_info=True)

    async def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self.bot.players.pop(self.guild_id, None)  # Free slot immediately to prevent duplicates

        self._cancel_inactive_timer()
        if self._play_task:
            self._play_task.cancel()

        try:
            await self._backend.cleanup()
        except Exception:
            logger.debug("Ignored cleanup error during destroy", exc_info=True)
        logger.info("MusicPlayer destroyed for guild {}", self.guild_id)


def _extract_video_id(url: str) -> str | None:
    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None
