"""Music cog core playback commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from cachetools import TTLCache
from discord import app_commands
from discord.ext import commands
from loguru import logger

from core.checks import cooldown, in_voice, is_dj
from core.errors import (
    BotNotConnectedError,
    NothingPlayingError,
    QueueEmptyError,
    TrackNotFoundError,
    VoiceConnectionFailedError,
)
from core.extractor import search_track
from core.player import MusicPlayer
from core.track import Track
from core.ui.now_playing import NowPlayingView
from core.ui.queue_paginator import QueuePaginator

if TYPE_CHECKING:
    from bot import MusicBot


# Short-TTL cache of recent (title, url) per guild — autocomplete fires per keystroke.
_history_ac_cache: TTLCache[int, list[tuple[str, str]]] = TTLCache(maxsize=500, ttl=30)


async def _recent_history_entries(guild_id: int) -> list[tuple[str, str]]:
    cached = _history_ac_cache.get(guild_id)
    if cached is not None:
        return cached
    from core.repositories import HistoryRepo

    try:
        rows = await HistoryRepo.get_recent(guild_id, limit=25)
    except Exception:
        return []
    entries = [(r.track_title, r.track_url) for r in rows]
    _history_ac_cache[guild_id] = entries
    return entries


async def _play_history_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Suggest recently played tracks for /play."""
    if not interaction.guild_id:
        return []

    cur = current.lower()
    seen: set[str] = set()
    choices: list[app_commands.Choice[str]] = []
    for title, url in await _recent_history_entries(interaction.guild_id):
        if title in seen:
            continue
        if cur and cur not in title.lower():
            continue
        seen.add(title)
        value = url if len(url) <= 100 else title
        choices.append(app_commands.Choice(name=title[:100], value=value[:100]))
        if len(choices) >= 25:
            break
    return choices


async def _queue_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Suggest songs from the current queue."""
    if not interaction.guild_id:
        return []

    player = interaction.client.get_player(interaction.guild_id)
    if not player or player.queue.is_empty:
        return []

    cur = current.lower()
    choices: list[app_commands.Choice[str]] = []

    for i, track in enumerate(player.queue.tracks):
        label = f"{i + 1}. {track.title}"
        if cur in label.lower():
            # Use string representation of index as value
            choices.append(app_commands.Choice(name=label[:100], value=str(i)))
        if len(choices) >= 25:
            break

    return choices


class Music(commands.Cog):
    """Core music playback commands."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        settings = await self.bot.get_guild_settings(ctx.guild.id)
        if settings and settings.music_channel_id and ctx.channel.id != settings.music_channel_id:
            from core.errors import WrongChannelError

            raise WrongChannelError(settings.music_channel_id)
        return True

    async def _get_or_create_player(self, ctx: commands.Context) -> MusicPlayer:
        """Get existing player or create a new one by joining the user's VC."""
        guild_id = ctx.guild.id
        player = self.bot.get_player(guild_id)

        if player and player.is_connected:
            return player

        # Stale player — destroy before creating new one
        if player:
            await player.destroy()

        # User must be in a voice channel
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
            from core.errors import NotInVoiceChannelError

            raise NotInVoiceChannelError()

        channel = ctx.author.voice.channel

        try:
            player = await self.bot.create_player(guild_id, channel, ctx.channel)
        except Exception as e:
            raise VoiceConnectionFailedError(str(e)) from e

        # Load guild default volume
        settings = await self.bot.get_guild_settings(guild_id)
        if settings:
            player.volume = settings.default_volume

        return player

    async def _within_queue_limit(self, ctx: commands.Context, player: MusicPlayer) -> bool:
        """Return False if the requester has hit the per-user queue cap (DJs bypass)."""
        settings = await self.bot.get_guild_settings(ctx.guild.id)
        cap = getattr(settings, "max_tracks_per_user", 0) if settings else 0
        if cap <= 0:
            return True

        from core.permissions import Tier, check_tier, get_user_tier

        dj_role_id = settings.dj_role_id if settings else None
        lone = getattr(settings, "lone_user_dj", True) if settings else True
        tier = await get_user_tier(ctx, dj_role_id, lone)
        if check_tier(tier, Tier.DJ):
            return True

        return player.queue.count_for_requester(ctx.author.id) < cap

    @commands.hybrid_command(
        name="play", aliases=["p"], description="Play a song from YouTube or other sources"
    )
    @app_commands.describe(query="Song name or URL to play")
    @app_commands.autocomplete(query=_play_history_autocomplete)
    @cooldown(1, 3.0)
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Search and play a track, or add it to the queue."""
        await ctx.defer()

        player = await self._get_or_create_player(ctx)
        player.text_channel = ctx.channel

        if not await self._within_queue_limit(ctx, player):
            await ctx.send("You've reached this server's per-user queue limit.", ephemeral=True)
            return

        # Search for the track
        tracks = []
        if "spotify.com" in query:
            from core.spotify import SpotifyScraper

            _playlist_name, queries = await SpotifyScraper.extract_queries(query)
            if not queries:
                raise TrackNotFoundError(query)
            for q in queries:
                track = Track(title=q, url=query, source="spotify", lazy_query=q)
                track.requester_id = ctx.author.id
                track.requester_name = ctx.author.display_name
                tracks.append(track)
        else:
            track = await search_track(query)
            if track is None:
                raise TrackNotFoundError(query)
            track.requester_id = ctx.author.id
            track.requester_name = ctx.author.display_name
            tracks.append(track)

        # Process tracks
        for i, track in enumerate(tracks):
            position = player.queue.add(track)

            # If nothing is playing and this is the first track, play immediately
            if i == 0 and not player.is_playing and not player.is_paused:
                await player.play_next()

                embed = discord.Embed(
                    title="Now Playing",
                    description=f"**[{track.title}]({track.url})**",
                    color=discord.Color.green(),
                )
                if track.duration_str != "0:00":
                    embed.add_field(name="Duration", value=track.duration_str, inline=True)
                embed.add_field(name="Requested by", value=ctx.author.display_name, inline=True)
                if track.thumbnail:
                    embed.set_thumbnail(url=track.thumbnail)

                settings = await self.bot.get_guild_settings(ctx.guild.id)
                view = NowPlayingView(player) if settings and settings.interactive_buttons else None
                await ctx.send(embed=embed, view=view)
            elif i == 0:
                # Add to queue notification for the first track or single track
                embed = discord.Embed(
                    title="Added to Queue",
                    description=f"**[{track.title}]({track.url})**"
                    + (f" and {len(tracks) - 1} more tracks" if len(tracks) > 1 else ""),
                    color=discord.Color.blue(),
                )
                embed.add_field(name="Position", value=str(position), inline=True)
                embed.add_field(name="Requested by", value=ctx.author.display_name, inline=True)
                await ctx.send(embed=embed)

    @commands.hybrid_command(name="search", description="Search and pick from the top results")
    @app_commands.describe(query="Song name to search for")
    @cooldown(1, 5.0)
    async def search(self, ctx: commands.Context, *, query: str) -> None:
        """Show the top search results and let the requester pick one to play."""
        from core.extractor import search_tracks

        await ctx.defer()
        tracks = await search_tracks(query, limit=5)
        if not tracks:
            raise TrackNotFoundError(query)

        lines = [
            f"`{i + 1}.` {track.short_title} `{track.duration_str}`"
            for i, track in enumerate(tracks)
        ]
        embed = discord.Embed(
            title=f"Search results for '{query[:80]}'",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        await ctx.send(embed=embed, view=_SearchResultView(self, ctx, tracks))

    @commands.hybrid_command(
        name="playnext", aliases=["pn"], description="Add a song to the front of the queue"
    )
    @app_commands.describe(query="Song name or URL to play next")
    @is_dj()
    @cooldown(1, 3.0)
    async def playnext(self, ctx: commands.Context, *, query: str) -> None:
        """Search a track and put it at the front of the queue (plays after the current song)."""
        await ctx.defer()

        player = await self._get_or_create_player(ctx)
        player.text_channel = ctx.channel

        track = await search_track(query)
        if track is None:
            raise TrackNotFoundError(query)
        track.requester_id = ctx.author.id
        track.requester_name = ctx.author.display_name

        if not player.is_playing and not player.is_paused:
            player.queue.add(track)
            await player.play_next()
            await ctx.send(
                embed=discord.Embed(
                    title="Now Playing",
                    description=f"**[{track.title}]({track.url})**",
                    color=discord.Color.green(),
                )
            )
        else:
            player.queue.add_top(track)
            await ctx.send(
                embed=discord.Embed(
                    title="Playing Next",
                    description=f"**[{track.title}]({track.url})** will play next",
                    color=discord.Color.blue(),
                )
            )

    @commands.hybrid_command(
        name="previous", aliases=["back", "prev"], description="Play the previous track"
    )
    @is_dj()
    @cooldown(1, 2.0)
    async def previous(self, ctx: commands.Context) -> None:
        """Replay the track that played before the current one."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()

        prev = await player.play_previous()
        if prev is None:
            await ctx.send("No previous track in history.", ephemeral=True)
            return
        await ctx.send(
            embed=discord.Embed(
                title="Playing Previous",
                description=f"**[{prev.title}]({prev.url})**",
                color=discord.Color.green(),
            )
        )

    @commands.hybrid_command(name="skip", aliases=["s"], description="Skip the current track")
    @cooldown(1, 2.0)
    async def skip(self, ctx: commands.Context) -> None:
        """Skip the current track.

        DJs/admins skip instantly. If the server configured a skip-vote threshold,
        other members vote and the track is skipped once enough listeners agree.
        """
        from math import ceil

        from core.permissions import Tier, check_tier, get_user_tier

        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.is_playing:
            raise NothingPlayingError()

        settings = await self.bot.get_guild_settings(ctx.guild.id)
        threshold = getattr(settings, "skip_vote_threshold", 0) if settings else 0

        dj_role_id = settings.dj_role_id if settings else None
        lone = getattr(settings, "lone_user_dj", True) if settings else True
        tier = await get_user_tier(ctx, dj_role_id, lone)
        privileged = check_tier(tier, Tier.DJ)

        # Instant skip for DJs/admins, or when vote-skip is disabled.
        if threshold <= 0 or privileged:
            skipped = await player.skip()
            title = skipped.short_title if skipped else "Unknown"
            await ctx.send(
                embed=discord.Embed(
                    title="Skipped",
                    description=f"Skipped **{title}**",
                    color=discord.Color.orange(),
                )
            )
            return

        # Vote-skip path: the voter must be listening in the bot's channel.
        vc = player.voice_client
        author_voice = getattr(ctx.author, "voice", None)
        if not vc or not author_voice or author_voice.channel != vc.channel:
            await ctx.send("Join the voice channel to vote-skip.", ephemeral=True)
            return

        listeners = [m for m in vc.channel.members if not m.bot]
        needed = max(1, ceil(len(listeners) * threshold / 100))
        votes = player.add_skip_vote(ctx.author.id)

        if votes >= needed:
            skipped = await player.skip()
            title = skipped.short_title if skipped else "Unknown"
            await ctx.send(
                embed=discord.Embed(
                    title="Vote Skip Passed",
                    description=f"Skipped **{title}** ({votes}/{needed} votes)",
                    color=discord.Color.orange(),
                )
            )
        else:
            await ctx.send(
                embed=discord.Embed(
                    title="Vote to Skip",
                    description=f"Skip vote registered: **{votes}/{needed}**",
                    color=discord.Color.blue(),
                )
            )

    @commands.hybrid_command(name="stop", description="Stop playback and clear the queue")
    @is_dj()
    @cooldown(1, 3.0)
    async def stop(self, ctx: commands.Context) -> None:
        """Stop playback and clear the queue."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()

        await player.stop()
        await ctx.send(
            embed=discord.Embed(
                title="Stopped",
                description="Playback stopped and queue cleared.",
                color=discord.Color.red(),
            )
        )

    @commands.hybrid_command(name="pause", description="Pause playback")
    @is_dj()
    @cooldown(1, 2.0)
    async def pause(self, ctx: commands.Context) -> None:
        """Pause the current track."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.is_playing:
            raise NothingPlayingError()

        await player.pause()
        await ctx.send(
            embed=discord.Embed(
                title="Paused",
                description="Playback paused. Use `/resume` to continue.",
                color=discord.Color.orange(),
            )
        )

    @commands.hybrid_command(name="resume", description="Resume playback")
    @is_dj()
    @cooldown(1, 2.0)
    async def resume(self, ctx: commands.Context) -> None:
        """Resume paused playback."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()
        if not player.is_paused:
            await ctx.send("Playback is not paused.", ephemeral=True)
            return

        await player.resume()
        await ctx.send(
            embed=discord.Embed(
                title="Resumed",
                description="Playback resumed.",
                color=discord.Color.green(),
            )
        )

    @commands.hybrid_command(name="queue", aliases=["q"], description="Show the current queue")
    @app_commands.describe(page="Page number (1-indexed)")
    @cooldown(1, 3.0)
    async def queue(self, ctx: commands.Context, page: int = 1) -> None:
        """Show the current music queue."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()

        if player.queue.is_empty and not player.current:
            raise QueueEmptyError()

        paginator = QueuePaginator(player, page=page)
        embed = paginator.build_embed()
        await ctx.send(embed=embed, view=paginator)

    @commands.hybrid_command(
        name="nowplaying", aliases=["np"], description="Show the currently playing track"
    )
    @cooldown(1, 3.0)
    async def nowplaying(self, ctx: commands.Context) -> None:
        """Show the currently playing track with interactive buttons."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.current:
            raise NothingPlayingError()

        track = player.current
        position = player.position_ms // 1000
        duration = track.duration or 0

        # Build progress bar
        bar_length = 20
        if duration > 0:
            filled = int(bar_length * position / duration)
            bar = "\u2588" * filled + "\u2591" * (bar_length - filled)
            progress = f"`{_format_time(position)}` {bar} `{_format_time(duration)}`"
        else:
            progress = f"`{_format_time(position)}` (LIVE)"

        embed = discord.Embed(
            title="Now Playing",
            description=f"**[{track.title}]({track.url})**\n\n{progress}",
            color=discord.Color.blue(),
        )
        if track.requester_name != "Unknown":
            if track.requester_name == "Auto-DJ":
                source_str = f" ({track.source})" if track.source else ""
                embed.add_field(name="Requested by", value=f"🤖 Auto-DJ{source_str}", inline=True)
            else:
                embed.add_field(name="Requested by", value=track.requester_name, inline=True)
        embed.add_field(name="Volume", value=f"{player.volume}%", inline=True)
        embed.add_field(name="Loop", value=player.queue.loop_mode.value, inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)

        settings = await self.bot.get_guild_settings(ctx.guild.id)
        view = NowPlayingView(player) if settings and settings.interactive_buttons else None
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(
        name="panel", description="Re-summon the persistent player control panel"
    )
    @is_dj()
    @cooldown(1, 10.0)
    async def panel(self, ctx: commands.Context) -> None:
        """Summon the Player Control Panel to the bottom of the chat."""
        from core.repositories import GuildSettingsRepo
        from core.ui.player_control import PlayerControlPanel, build_panel_embed

        settings = await self.bot.get_guild_settings(ctx.guild.id)
        player = self.bot.get_player(ctx.guild.id)

        # Try to delete the old panel message
        if settings and settings.music_channel_id and settings.panel_message_id:
            try:
                channel = self.bot.get_channel(settings.music_channel_id)
                if channel:
                    old_msg = await channel.fetch_message(settings.panel_message_id)
                    await old_msg.delete()
            except discord.NotFound:
                pass
            except Exception as e:
                logger.warning(f"Could not delete old panel message: {e}")

        # If no player exists, we'll still show the empty state panel
        embed = build_panel_embed(player)
        view = PlayerControlPanel(self.bot, ctx.guild.id)

        msg = await ctx.send(embed=embed, view=view)

        # Track this new panel message in the settings
        await GuildSettingsRepo.update(ctx.guild.id, panel_message_id=msg.id)
        self.bot.invalidate_settings_cache(ctx.guild.id)

    @commands.hybrid_command(name="join", description="Join a voice channel")
    @in_voice()
    @cooldown(1, 3.0)
    async def join(
        self, ctx: commands.Context, *, channel: discord.VoiceChannel | None = None
    ) -> None:
        """Join a voice channel."""
        target = channel or ctx.author.voice.channel

        player = self.bot.get_player(ctx.guild.id)
        if player and player.is_connected:
            if player.voice_client.channel == target:
                await ctx.send("Already connected to this channel.", ephemeral=True)
                return
            await player.voice_client.move_to(target)
            await ctx.send(f"Moved to **{target.name}**")
            return

        try:
            player = await self.bot.create_player(ctx.guild.id, target, ctx.channel)
            await ctx.send(f"Joined **{target.name}** using **{player.backend_name}**")
        except Exception as e:
            raise VoiceConnectionFailedError(str(e)) from e

    @commands.hybrid_command(
        name="leave", aliases=["dc", "disconnect"], description="Leave the voice channel"
    )
    @is_dj()
    @cooldown(1, 3.0)
    async def leave(self, ctx: commands.Context) -> None:
        """Disconnect from the voice channel."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()

        await player.destroy()
        await ctx.send(
            embed=discord.Embed(
                title="Disconnected",
                description="Left the voice channel.",
                color=discord.Color.greyple(),
            )
        )

    @commands.hybrid_command(name="seek", description="Seek to a position in the current track")
    @app_commands.describe(position="Time to seek to (e.g., 1:30 or 90)")
    @is_dj()
    @cooldown(1, 3.0)
    async def seek(self, ctx: commands.Context, *, position: str) -> None:
        """Seek to a position in the current track."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.current:
            raise NothingPlayingError()

        seconds = _parse_time(position)
        if seconds is None or seconds < 0:
            from core.errors import InvalidSeekPositionError

            raise InvalidSeekPositionError()

        # Clamp to the track length so we never seek past the end.
        duration = player.current.duration
        if duration is not None and seconds > duration:
            seconds = duration

        await player.seek(seconds * 1000)
        await ctx.send(f"Seeked to `{_format_time(seconds)}`")

    @commands.hybrid_command(
        name="forward", aliases=["fwd"], description="Play a specific song from the queue"
    )
    @app_commands.describe(song="The song to play from the queue")
    @app_commands.autocomplete(song=_queue_autocomplete)
    @is_dj()
    @cooldown(1, 2.0)
    async def forward(self, ctx: commands.Context, song: str) -> None:
        """Play a specific song from the queue and remove it."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.current:
            raise NothingPlayingError()

        if not song.isdigit():
            await ctx.send("Invalid song selection.", ephemeral=True)
            return

        index = int(song)
        track = player.queue.remove(index)
        if not track:
            await ctx.send("Song not found in the queue.", ephemeral=True)
            return

        player.queue.add_top(track)
        await player.skip()

        await ctx.send(
            embed=discord.Embed(
                title="Forwarded to Song",
                description=f"Skipped to and playing **[{track.title}]({track.url})** from the queue.",
                color=discord.Color.green(),
            )
        )

    @commands.hybrid_command(name="rewind", aliases=["rwd"], description="Rewind the track")
    @app_commands.describe(seconds="Seconds to rewind (default 15)")
    @is_dj()
    @cooldown(1, 2.0)
    async def rewind(self, ctx: commands.Context, seconds: int = 15) -> None:
        """Seek backward by a number of seconds."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.current:
            raise NothingPlayingError()
        if seconds <= 0:
            await ctx.send("Seconds must be positive.", ephemeral=True)
            return

        target = max(0, player.position_ms // 1000 - seconds)
        await player.seek(target * 1000)
        await ctx.send(f"Rewound to `{_format_time(target)}`")

    @commands.hybrid_command(
        name="sleeptimer", aliases=["sleep"], description="Stop playback after N minutes"
    )
    @app_commands.describe(minutes="Minutes until playback stops (0 to cancel)")
    @is_dj()
    @cooldown(1, 3.0)
    async def sleeptimer(self, ctx: commands.Context, minutes: int) -> None:
        """Set or cancel a sleep timer that stops playback after a delay."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()
        if minutes < 0 or minutes > 1440:
            await ctx.send("Minutes must be between 0 and 1440.", ephemeral=True)
            return

        if minutes == 0:
            player.cancel_sleep_timer()
            await ctx.send("Sleep timer cancelled.")
            return

        player.text_channel = ctx.channel
        player.set_sleep_timer(minutes * 60)
        await ctx.send(f"Sleep timer set — playback will stop in **{minutes}** minute(s).")

    @commands.hybrid_command(name="volume", aliases=["vol"], description="Set the playback volume")
    @app_commands.describe(level="Volume level (0-200)")
    @is_dj()
    @cooldown(1, 2.0)
    async def volume(self, ctx: commands.Context, level: int) -> None:
        """Set the playback volume (0-200)."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()

        level = max(0, min(level, 200))
        await player.set_volume(level)
        await ctx.send(f"Volume set to **{level}%**")

    @commands.hybrid_command(name="replay", description="Restart the current track")
    @is_dj()
    @cooldown(1, 3.0)
    async def replay(self, ctx: commands.Context) -> None:
        """Restart the current track from the beginning."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.current:
            raise NothingPlayingError()

        await player.seek(0)
        await ctx.send(f"Replaying **{player.current.short_title}**")

    @commands.hybrid_command(name="jump", description="Jump to a specific position in the queue")
    @app_commands.describe(position="Queue position to jump to (1-indexed)")
    @is_dj()
    @cooldown(1, 3.0)
    async def jump(self, ctx: commands.Context, position: int) -> None:
        """Jump to a specific track in the queue."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()

        if position < 1 or position > player.queue.size:
            await ctx.send(
                f"Invalid position. Queue has {player.queue.size} tracks.", ephemeral=True
            )
            return

        # Remove tracks before the target position
        for _ in range(position - 1):
            player.queue.remove(0)

        await player.skip()
        await ctx.send(f"Jumped to position **{position}**")


class _SearchResultView(discord.ui.View):
    """A dropdown that lets the requester pick one of the search results to play."""

    def __init__(self, cog: Music, ctx: commands.Context, tracks: list[Track]) -> None:
        super().__init__(timeout=60.0)
        self.cog = cog
        self.ctx = ctx
        self.tracks = tracks

        options = [
            discord.SelectOption(
                label=track.short_title,
                value=str(i),
                description=(track.duration_str if track.duration else None),
            )
            for i, track in enumerate(tracks)
        ]
        self._select: discord.ui.Select = discord.ui.Select(
            placeholder="Pick a track to play…", min_values=1, max_values=1, options=options
        )
        self._select.callback = self._on_select
        self.add_item(self._select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This search isn't yours.", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction) -> None:
        track = self.tracks[int(self._select.values[0])]
        for child in self.children:
            child.disabled = True
        self.stop()
        await interaction.response.edit_message(
            content=f"Selected: **{track.short_title}**", view=self
        )

        from core.errors import MusicBotError

        try:
            player = await self.cog._get_or_create_player(self.ctx)
        except MusicBotError as exc:
            await interaction.followup.send(exc.message, ephemeral=True)
            return
        except Exception as exc:
            await interaction.followup.send(f"Couldn't join voice: {exc}", ephemeral=True)
            return

        if not await self.cog._within_queue_limit(self.ctx, player):
            await interaction.followup.send(
                "You've reached this server's per-user queue limit.", ephemeral=True
            )
            return

        player.text_channel = self.ctx.channel
        track.requester_id = interaction.user.id
        track.requester_name = interaction.user.display_name
        player.queue.add(track)

        if not player.is_playing and not player.is_paused:
            await player.play_next()
            await interaction.followup.send(f"Now playing **{track.short_title}**")
        else:
            await interaction.followup.send(f"Added **{track.short_title}** to the queue")

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


def _format_time(seconds: int) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _parse_time(time_str: str) -> int | None:
    """Parse a time string like '1:30' or '90' into seconds."""
    time_str = time_str.strip()

    # Try MM:SS or HH:MM:SS
    parts = time_str.split(":")
    try:
        if len(parts) == 1:
            return int(parts[0])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        pass
    return None


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Music(bot))
