"""Per-guild MusicPlayer class managing voice, queue, playback, and FX state."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
from loguru import logger

from core.audio_backends import BackendUnavailableError, BaseAudioBackend, LavalinkBackend
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
        self._autodj_lock = asyncio.Lock()
        self._inactive_task: asyncio.Task | None = None
        self._destroyed = False
        self._play_task: asyncio.Task | None = None
        self._autodj_prefill_task: asyncio.Task | None = None
        self._fallback_announced = False
        self._backend_switch_in_progress = False
        self._consecutive_failures = 0
        self._skip_votes: set[int] = set()
        self._sleep_task: asyncio.Task | None = None
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
            default_fx = getattr(settings, "default_fx", None)
            if default_fx:
                try:
                    await player.apply_filters([default_fx])
                except Exception:
                    logger.debug("Failed to apply default FX '{}'", default_fx, exc_info=True)
        return player

    async def play_next(self, error: Exception | None = None) -> None:
        """Play the next track in the queue."""
        if self._destroyed:
            return

        async with self._play_lock:
            # If a concurrent play_next started playing before we got the lock, abort
            if self.is_playing or self.is_paused:
                return

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
            self._skip_votes.clear()

            if next_track.lazy_query:
                from core.extractor import search_track
                resolved = await search_track(next_track.lazy_query)
                if resolved:
                    next_track.url = resolved.url
                    next_track.title = resolved.title
                    next_track.duration = resolved.duration
                    next_track.thumbnail = resolved.thumbnail
                    next_track.stream_url = resolved.stream_url
                next_track.lazy_query = None

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
            except BackendUnavailableError as exc:
                if await self._try_fallback(exc, next_track):
                    return
                await self._handle_track_failure(next_track, exc)
                return
            except Exception as exc:
                await self._handle_track_failure(next_track, exc)
                return

            # Cancel any lingering wait task to prevent cascading skip loops
            if self._play_task and not self._play_task.done():
                self._play_task.cancel()
            self._play_task = asyncio.create_task(self._wait_and_play_next())

            # Pre-emptive Auto-DJ: start filling queue when it's getting low
            await self._maybe_prefill_auto_dj()

    async def _wait_and_play_next(self) -> None:
        """Wait for the current track to finish, then play next."""
        try:
            error = await self._backend.wait_for_track_end()
            if not self._destroyed:
                # Record completion signal for Auto-DJ learning
                if self.current and self.current.requester_name == "Auto-DJ":
                    await self.bot.autodj_engine.record_completion(self.guild_id, self.current)
                await self.play_next(error)
        except asyncio.CancelledError:
            pass

    def add_skip_vote(self, user_id: int) -> int:
        """Record a skip vote for the current track. Returns the current vote count."""
        self._skip_votes.add(user_id)
        return len(self._skip_votes)

    def set_sleep_timer(self, seconds: int) -> None:
        """Stop playback after ``seconds``. Replaces any existing sleep timer."""
        self.cancel_sleep_timer()
        self._sleep_task = asyncio.create_task(self._sleep_wrapper(seconds))

    def cancel_sleep_timer(self) -> None:
        """Cancel a pending sleep timer, if any."""
        if self._sleep_task and not self._sleep_task.done():
            self._sleep_task.cancel()
        self._sleep_task = None

    async def _sleep_wrapper(self, seconds: int) -> None:
        try:
            await asyncio.sleep(seconds)
            if self._destroyed:
                return
            if self.text_channel:
                await self.text_channel.send(
                    embed=discord.Embed(
                        title="Sleep Timer",
                        description="Sleep timer reached — stopping playback. Good night!",
                        color=discord.Color.blurple(),
                    )
                )
            await self.stop()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Error in sleep timer", exc_info=True)

    async def play_previous(self) -> Track | None:
        """Replay the most recent track from history. Returns it, or None if empty."""
        prev = self.queue.previous()
        if prev is None:
            return None

        # Re-queue the current track to play after the previous one, then jump back.
        if self.current:
            self.queue.add_top(self.current)
        self.queue.add_top(prev)
        await self.skip()
        return prev

    async def skip(self) -> Track | None:
        skipped = self.current
        if self._play_task:
            self._play_task.cancel()
        await self._backend.stop()

        # Record skip signal for Auto-DJ learning
        if skipped and skipped.requester_name == "Auto-DJ":
            await self.bot.autodj_engine.record_skip(self.guild_id, skipped)

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
        except BackendUnavailableError as exc:
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
        if not self.current:
            return

        settings = await self.bot.get_guild_settings(self.guild_id)
        if not settings:
            return

        from core.ui.player_control import PlayerControlPanel, build_panel_embed

        if settings.music_channel_id and settings.panel_message_id:
            channel = self.bot.get_channel(settings.music_channel_id)
            if channel:
                try:
                    msg = await channel.fetch_message(settings.panel_message_id)
                    embed = build_panel_embed(self)
                    view = PlayerControlPanel(self.bot, self.guild_id)
                    await msg.edit(embed=embed, view=view)
                    return
                except (discord.NotFound, discord.Forbidden):
                    # Message deleted or access denied; fallback
                    pass

        # Fallback
        if not self.text_channel:
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

        from core.ui.now_playing import NowPlayingView
        view = NowPlayingView(self) if settings.interactive_buttons else None
        await self.text_channel.send(embed=embed, view=view)

    async def _try_auto_dj(self) -> bool:
        """Attempt to fill the queue via the Auto-DJ recommendation engine.

        Uses the multi-source pipeline: YouTube Mix → History → Search fallback.
        Protected by a lock to prevent concurrent triggers.
        """
        settings = await self.bot.get_guild_settings(self.guild_id)
        if not settings or not settings.autoplay:
            return False

        history = self.queue.history
        if not history:
            return False

        if self._autodj_lock.locked():
            logger.debug("Auto-DJ: already running for guild {}, skipping", self.guild_id)
            return False

        async with self._autodj_lock:
            last_track = history[0]
            logger.info("Auto-DJ: fetching recommendations for guild {}", self.guild_id)

            try:
                from core.repositories import HistoryRepo

                db_recent_urls = await HistoryRepo.get_recent_urls(self.guild_id, limit=200)
            except Exception:
                db_recent_urls = None
                logger.debug("Auto-DJ: failed to fetch DB history URLs", exc_info=True)

            try:
                new_tracks = await self.bot.autodj_engine.get_recommendations(
                    guild_id=self.guild_id,
                    seed_track=last_track,
                    queue=self.queue,
                    db_recent_urls=db_recent_urls,
                )
            except Exception:
                logger.error("Auto-DJ: engine error for guild {}", self.guild_id, exc_info=True)
                return False

            if not new_tracks:
                logger.debug("Auto-DJ: no recommendations found for guild {}", self.guild_id)
                return False

            for track in new_tracks:
                track.requester_name = "Auto-DJ"
                self.queue.add(track)

            logger.info("Auto-DJ: added {} tracks to queue for guild {}", len(new_tracks), self.guild_id)
            await self.play_next()
            return True

    async def _maybe_prefill_auto_dj(self) -> None:
        """Pre-emptively fill the queue when it's getting low (≤1 track remaining).

        Runs as a background task so it doesn't block the current playback.
        """
        settings = await self.bot.get_guild_settings(self.guild_id)
        if not settings or not settings.autoplay:
            return
        if self.queue.size > 1:
            return

        # Don't stack multiple prefill tasks
        if self._autodj_prefill_task and not self._autodj_prefill_task.done():
            return

        self._autodj_prefill_task = asyncio.create_task(self._prefill_auto_dj())

    async def _prefill_auto_dj(self) -> None:
        """Background task to pre-fill the queue with Auto-DJ tracks."""
        try:
            if self._autodj_lock.locked():
                return

            async with self._autodj_lock:
                seed = self.current
                if not seed:
                    return

                try:
                    from core.repositories import HistoryRepo

                    db_recent_urls = await HistoryRepo.get_recent_urls(self.guild_id, limit=200)
                except Exception:
                    db_recent_urls = None

                try:
                    new_tracks = await self.bot.autodj_engine.get_recommendations(
                        guild_id=self.guild_id,
                        seed_track=seed,
                        queue=self.queue,
                        db_recent_urls=db_recent_urls,
                    )
                except Exception:
                    logger.debug("Auto-DJ prefill: engine error", exc_info=True)
                    return

                for track in new_tracks:
                    track.requester_name = "Auto-DJ"
                    self.queue.add(track)

                if new_tracks:
                    logger.info(
                        "Auto-DJ prefill: added {} tracks for guild {}",
                        len(new_tracks),
                        self.guild_id,
                    )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Auto-DJ prefill error", exc_info=True)

    def _start_inactive_timer(self) -> None:
        self._cancel_inactive_timer()
        self._inactive_task = asyncio.create_task(self._inactive_disconnect_wrapper())

    async def _inactive_disconnect_wrapper(self) -> None:
        try:
            settings = await self.bot.get_guild_settings(self.guild_id)
            timeout = settings.inactivity_timeout if settings else 300

            if timeout <= 0:
                # 24/7 mode enabled
                return

            await asyncio.sleep(timeout)
            if not self._destroyed and not self.is_playing:
                logger.info("Inactivity timeout for guild {}, disconnecting", self.guild_id)
                await self.destroy()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Error in inactive disconnect", exc_info=True)

    def _cancel_inactive_timer(self) -> None:
        if self._inactive_task and not self._inactive_task.done():
            self._inactive_task.cancel()
            self._inactive_task = None

    async def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self.bot.players.pop(self.guild_id, None)  # Free slot immediately to prevent duplicates

        self._cancel_inactive_timer()
        self.cancel_sleep_timer()
        if self._play_task:
            self._play_task.cancel()
        if self._autodj_prefill_task and not self._autodj_prefill_task.done():
            self._autodj_prefill_task.cancel()

        # Clean up the Auto-DJ session
        self.bot.autodj_engine.destroy_session(self.guild_id)

        try:
            await self._backend.cleanup()
        except Exception:
            logger.debug("Ignored cleanup error during destroy", exc_info=True)
        logger.info("MusicPlayer destroyed for guild {}", self.guild_id)
