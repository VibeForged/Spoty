"""Music cog — core playback commands.

Phase 1: play, skip, stop, queue, join, leave, nowplaying, pause, resume.
Phase 2 will add: seek, volume, replay, jump, playtop, playnow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from core.checks import cooldown, in_voice
from core.errors import (
    BotNotConnected,
    NothingPlaying,
    QueueEmpty,
    TrackNotFound,
    VoiceConnectionFailed,
)
from core.extractor import search_track
from core.player import MusicPlayer
from core.track import Track
from core.ui.now_playing import NowPlayingView
from core.ui.queue_paginator import QueuePaginator

if TYPE_CHECKING:
    from bot import MusicBot


class Music(commands.Cog):
    """Core music playback commands."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    async def _get_or_create_player(
        self, ctx: commands.Context
    ) -> MusicPlayer:
        """Get existing player or create a new one by joining the user's VC."""
        guild_id = ctx.guild.id
        player = self.bot.get_player(guild_id)

        if player and player.voice_client and player.voice_client.is_connected():
            return player

        # Stale player — destroy before creating new one
        if player:
            await player.destroy()

        # User must be in a voice channel
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
            from core.errors import NotInVoiceChannel
            raise NotInVoiceChannel()

        channel = ctx.author.voice.channel

        try:
            player = await self.bot.create_player(guild_id, channel, ctx.channel)
        except Exception as e:
            raise VoiceConnectionFailed(str(e))

        # Load guild default volume
        settings = await self.bot.get_guild_settings(guild_id)
        if settings:
            player.volume = settings.default_volume

        return player

    @commands.hybrid_command(name="play", aliases=["p"], description="Play a song from YouTube or other sources")
    @app_commands.describe(query="Song name or URL to play")
    @cooldown(1, 3.0)
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Search and play a track, or add it to the queue."""
        await ctx.defer()

        player = await self._get_or_create_player(ctx)
        player.text_channel = ctx.channel

        # Search for the track
        track = await search_track(query)
        if track is None:
            raise TrackNotFound(query)

        track.requester_id = ctx.author.id
        track.requester_name = ctx.author.display_name

        # If nothing is playing, play immediately
        if not player.is_playing and not player.is_paused:
            player.queue.add(track)
            await player.play_next()

            embed = discord.Embed(
                title="Now Playing",
                description=f"**[{track.title}]({track.url})**",
                color=discord.Color.green(),
            )
            embed.add_field(name="Duration", value=track.duration_str, inline=True)
            embed.add_field(name="Requested by", value=ctx.author.display_name, inline=True)
            if track.thumbnail:
                embed.set_thumbnail(url=track.thumbnail)

            settings = await self.bot.get_guild_settings(ctx.guild.id)
            view = NowPlayingView(player) if settings and settings.interactive_buttons else None
            await ctx.send(embed=embed, view=view)
        else:
            # Add to queue
            position = player.queue.add(track)

            embed = discord.Embed(
                title="Added to Queue",
                description=f"**[{track.title}]({track.url})**",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Position", value=str(position), inline=True)
            embed.add_field(name="Duration", value=track.duration_str, inline=True)
            embed.add_field(name="Requested by", value=ctx.author.display_name, inline=True)
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="skip", aliases=["s"], description="Skip the current track")
    @cooldown(1, 2.0)
    async def skip(self, ctx: commands.Context) -> None:
        """Skip the current track."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.is_playing:
            raise NothingPlaying()

        skipped = await player.skip()
        title = skipped.short_title if skipped else "Unknown"
        await ctx.send(
            embed=discord.Embed(
                title="Skipped",
                description=f"Skipped **{title}**",
                color=discord.Color.orange(),
            )
        )

    @commands.hybrid_command(name="stop", description="Stop playback and clear the queue")
    @cooldown(1, 3.0)
    async def stop(self, ctx: commands.Context) -> None:
        """Stop playback and clear the queue."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnected()

        await player.stop()
        await ctx.send(
            embed=discord.Embed(
                title="Stopped",
                description="Playback stopped and queue cleared.",
                color=discord.Color.red(),
            )
        )

    @commands.hybrid_command(name="pause", description="Pause playback")
    @cooldown(1, 2.0)
    async def pause(self, ctx: commands.Context) -> None:
        """Pause the current track."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.is_playing:
            raise NothingPlaying()

        await player.pause()
        await ctx.send(
            embed=discord.Embed(
                title="Paused",
                description="Playback paused. Use `/resume` to continue.",
                color=discord.Color.orange(),
            )
        )

    @commands.hybrid_command(name="resume", description="Resume playback")
    @cooldown(1, 2.0)
    async def resume(self, ctx: commands.Context) -> None:
        """Resume paused playback."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnected()
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
    @cooldown(1, 3.0)
    async def queue(self, ctx: commands.Context, page: int = 1) -> None:
        """Show the current music queue."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnected()

        if player.queue.is_empty and not player.current:
            raise QueueEmpty()

        paginator = QueuePaginator(player, page=page)
        embed = paginator.build_embed()
        await ctx.send(embed=embed, view=paginator)

    @commands.hybrid_command(name="nowplaying", aliases=["np"], description="Show the currently playing track")
    @cooldown(1, 3.0)
    async def nowplaying(self, ctx: commands.Context) -> None:
        """Show the currently playing track with interactive buttons."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.current:
            raise NothingPlaying()

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
            embed.add_field(name="Requested by", value=track.requester_name, inline=True)
        embed.add_field(name="Volume", value=f"{player.volume}%", inline=True)
        embed.add_field(name="Loop", value=player.queue.loop_mode.value, inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)

        settings = await self.bot.get_guild_settings(ctx.guild.id)
        view = NowPlayingView(player) if settings and settings.interactive_buttons else None
        await ctx.send(embed=embed, view=view)

    @commands.hybrid_command(name="join", description="Join a voice channel")
    @in_voice()
    @cooldown(1, 3.0)
    async def join(self, ctx: commands.Context, *, channel: discord.VoiceChannel | None = None) -> None:
        """Join a voice channel."""
        target = channel or ctx.author.voice.channel

        player = self.bot.get_player(ctx.guild.id)
        if player and player.voice_client and player.voice_client.is_connected():
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
            raise VoiceConnectionFailed(str(e))

    @commands.hybrid_command(name="leave", aliases=["dc", "disconnect"], description="Leave the voice channel")
    @cooldown(1, 3.0)
    async def leave(self, ctx: commands.Context) -> None:
        """Disconnect from the voice channel."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnected()

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
    @cooldown(1, 3.0)
    async def seek(self, ctx: commands.Context, *, position: str) -> None:
        """Seek to a position in the current track."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.current:
            raise NothingPlaying()

        seconds = _parse_time(position)
        if seconds is None:
            from core.errors import InvalidSeekPosition
            raise InvalidSeekPosition()

        await player.seek(seconds * 1000)
        await ctx.send(f"Seeked to `{_format_time(seconds)}`")

    @commands.hybrid_command(name="volume", aliases=["vol"], description="Set the playback volume")
    @app_commands.describe(level="Volume level (0-200)")
    @cooldown(1, 2.0)
    async def volume(self, ctx: commands.Context, level: int) -> None:
        """Set the playback volume (0-200)."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnected()

        level = max(0, min(level, 200))
        await player.set_volume(level)
        await ctx.send(f"Volume set to **{level}%**")

    @commands.hybrid_command(name="replay", description="Restart the current track")
    @cooldown(1, 3.0)
    async def replay(self, ctx: commands.Context) -> None:
        """Restart the current track from the beginning."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.current:
            raise NothingPlaying()

        await player.seek(0)
        await ctx.send(f"Replaying **{player.current.short_title}**")

    @commands.hybrid_command(name="jump", description="Jump to a specific position in the queue")
    @app_commands.describe(position="Queue position to jump to (1-indexed)")
    @cooldown(1, 3.0)
    async def jump(self, ctx: commands.Context, position: int) -> None:
        """Jump to a specific track in the queue."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnected()

        if position < 1 or position > player.queue.size:
            await ctx.send(f"Invalid position. Queue has {player.queue.size} tracks.", ephemeral=True)
            return

        # Remove tracks before the target position
        for _ in range(position - 1):
            player.queue.remove(0)

        await player.skip()
        await ctx.send(f"Jumped to position **{position}**")


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
