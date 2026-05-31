"""Auto-DJ commands cog — user-facing entry points for the recommendation engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from core.checks import cooldown, in_voice, is_dj
from core.errors import BotNotConnected, NothingPlaying
from core.extractor import search_track

if TYPE_CHECKING:
    from bot import MusicBot


class AutoDJ(commands.Cog):
    """Auto-DJ commands for intelligent music discovery."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="autodj", description="Auto-DJ controls")
    async def autodj(self, ctx: commands.Context) -> None:
        """Auto-DJ — intelligent music recommendations."""
        if ctx.invoked_subcommand is None:
            await self.autodj_start(ctx)

    @autodj.command(name="start", description="Start Auto-DJ with optional genre/artist seed")
    @app_commands.describe(query="Optional genre, artist, or song to seed Auto-DJ (e.g. 'rock', 'Eminem')")
    @in_voice()
    @cooldown(1, 5.0)
    async def autodj_start(self, ctx: commands.Context, *, query: str | None = None) -> None:
        """Start Auto-DJ. Optionally provide a genre, artist, or song to seed it.

        Examples:
            !autodj start          — Seeds from your last played or guild history
            !autodj start rock     — Seeds with a rock song
            !autodj start Eminem   — Seeds with an Eminem track
        """
        await ctx.defer()

        from core.player import MusicPlayer
        from core.repositories import GuildSettingsRepo, HistoryRepo

        guild_id = ctx.guild.id

        # Ensure autoplay is enabled
        settings = await self.bot.get_guild_settings(guild_id)
        if not settings or not settings.autoplay:
            await GuildSettingsRepo.update(guild_id, autoplay=True)
            self.bot.invalidate_settings_cache(guild_id)

        # Get or create player
        player = self.bot.get_player(guild_id)
        if not player or not player.is_connected:
            if player:
                await player.destroy()

            if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
                from core.errors import NotInVoiceChannel

                raise NotInVoiceChannel()

            channel = ctx.author.voice.channel
            from core.errors import VoiceConnectionFailed

            try:
                player = await self.bot.create_player(guild_id, channel, ctx.channel)
            except Exception as e:
                raise VoiceConnectionFailed(str(e))

        player.text_channel = ctx.channel

        # Find a seed track
        seed_track = None

        if query:
            # User provided a seed — search for it
            seed_track = await search_track(query)
            if not seed_track:
                await ctx.send(
                    embed=discord.Embed(
                        title="Auto-DJ",
                        description=f"Couldn't find anything for **{query}**. Try a different search.",
                        color=discord.Color.red(),
                    ),
                    ephemeral=True,
                )
                return
        else:
            # No query — try to use current track, queue history, or DB history
            if player.current:
                seed_track = player.current
            elif player.queue.history:
                seed_track = player.queue.history[0]
            else:
                # Check guild history in DB
                history = await HistoryRepo.get_recent(guild_id, limit=1)
                if history:
                    from core.track import Track

                    h = history[0]
                    seed_track = Track(title=h.track_title, url=h.track_url, duration=h.duration)

            if not seed_track:
                await ctx.send(
                    embed=discord.Embed(
                        title="Auto-DJ",
                        description="No listening history found! Start by playing a song:\n"
                        "`!autodj start <genre or artist>`",
                        color=discord.Color.orange(),
                    ),
                    ephemeral=True,
                )
                return

        # If nothing is currently playing, play the seed track first
        if not player.is_playing and not player.is_paused:
            if query and seed_track:
                seed_track.requester_name = "Auto-DJ"
                seed_track.requester_id = ctx.author.id
                player.queue.add(seed_track)
                await player.play_next()

        # Build session info
        session = await self.bot.autodj_engine.get_or_create_session(guild_id, seed_track)

        embed = discord.Embed(
            title="🤖 Auto-DJ Started",
            description=f"Seeded with **{seed_track.short_title}**\n\n"
            "I'll automatically queue related tracks as the queue empties.\n"
            "Use `!autodj stop` to turn it off.",
            color=discord.Color.purple(),
        )
        embed.add_field(name="Sources", value="YouTube Mix • Last.fm • History • Search", inline=False)
        if seed_track.thumbnail:
            embed.set_thumbnail(url=seed_track.thumbnail)

        await ctx.send(embed=embed)

    @autodj.command(name="stop", description="Stop Auto-DJ and disable autoplay")
    @is_dj()
    @cooldown(1, 5.0)
    async def autodj_stop(self, ctx: commands.Context) -> None:
        """Stop Auto-DJ and disable autoplay for this server."""
        guild_id = ctx.guild.id

        from core.repositories import GuildSettingsRepo

        await GuildSettingsRepo.update(guild_id, autoplay=False)
        self.bot.invalidate_settings_cache(guild_id)
        self.bot.autodj_engine.destroy_session(guild_id)

        await ctx.send(
            embed=discord.Embed(
                title="🤖 Auto-DJ Stopped",
                description="Auto-DJ has been disabled. The current queue will continue playing.",
                color=discord.Color.greyple(),
            )
        )

    @autodj.command(name="status", description="Show current Auto-DJ session status")
    @cooldown(1, 5.0)
    async def autodj_status(self, ctx: commands.Context) -> None:
        """Show the current Auto-DJ session info."""
        guild_id = ctx.guild.id
        settings = await self.bot.get_guild_settings(guild_id)
        session = self.bot.autodj_engine.get_session(guild_id)

        enabled = settings.autoplay if settings else False

        embed = discord.Embed(
            title="🤖 Auto-DJ Status",
            color=discord.Color.purple() if enabled else discord.Color.greyple(),
        )
        embed.add_field(name="Enabled", value="✅ Yes" if enabled else "❌ No", inline=True)

        if session:
            embed.add_field(name="Tracks Served", value=str(session.tracks_served), inline=True)
            embed.add_field(
                name="Seed Track",
                value=session.seed_track.short_title if session.seed_track else "None",
                inline=False,
            )

            # Show recent artists
            if session.recent_artists:
                unique_artists = list(dict.fromkeys(session.recent_artists))[:8]
                artists_str = ", ".join(a.title() for a in unique_artists)
                embed.add_field(name="Recent Artists", value=artists_str, inline=False)

            # Show skip/completion stats
            skips = sum(session.skip_signals.values())
            completions = sum(session.completion_signals.values())
            embed.add_field(name="Skips", value=str(skips), inline=True)
            embed.add_field(name="Completions", value=str(completions), inline=True)

            # Session age (use timezone-aware UTC)
            from datetime import datetime, UTC

            age_seconds = (datetime.now(UTC) - session.created_at).total_seconds()
            if age_seconds < 3600:
                age_str = f"{int(age_seconds / 60)}m"
            else:
                age_str = f"{age_seconds / 3600:.1f}h"
            embed.add_field(name="Session Age", value=age_str, inline=True)
        else:
            embed.add_field(
                name="Session",
                value="No active session. Use `!autodj start` to begin.",
                inline=False,
            )

        embed.add_field(
            name="Sources",
            value="YouTube Mix • Last.fm • History • Search",
            inline=False,
        )

        await ctx.send(embed=embed)

    @autodj.command(name="skip", description="Skip current Auto-DJ track and get a fresh recommendation")
    @cooldown(1, 3.0)
    async def autodj_skip(self, ctx: commands.Context) -> None:
        """Skip the current track and tell Auto-DJ you didn't like it."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.current:
            raise NothingPlaying()

        track = player.current
        # Record as skip signal (stronger than regular skip)
        await self.bot.autodj_engine.record_skip(ctx.guild.id, track)
        if track.requester_name == "Auto-DJ":
            await self.bot.autodj_engine.record_skip(ctx.guild.id, track)  # Double penalty

        skipped = await player.skip()
        title = skipped.short_title if skipped else "Unknown"
        await ctx.send(
            embed=discord.Embed(
                title="🤖 Auto-DJ Skip",
                description=f"Skipped **{title}** — I'll avoid similar tracks.",
                color=discord.Color.orange(),
            )
        )


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(AutoDJ(bot))
