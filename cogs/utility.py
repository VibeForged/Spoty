"""Utility cog help, ping, lyrics, history, stats, feedback, quiz, ambience."""

from __future__ import annotations

import platform
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from core.checks import cooldown

if TYPE_CHECKING:
    from bot import MusicBot
    from core.quiz import MusicQuiz

AMBIENCE_QUERIES: dict[str, str] = {
    "rain": "rain sounds relaxing 10 hours",
    "ocean": "ocean waves sounds relaxing",
    "forest": "forest nature sounds ambient",
    "cafe": "coffee shop ambience background noise",
    "fireplace": "fireplace crackling sounds",
    "thunder": "thunderstorm sounds relaxing",
    "wind": "wind sounds ambient relaxing",
    "birds": "bird sounds nature morning",
    "river": "river stream water sounds relaxing",
    "night": "night sounds crickets ambient",
}


class Utility(commands.Cog):
    """Utility and social commands."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot
        self._start_time = time.monotonic()

    @commands.hybrid_command(name="help", description="Show bot commands")
    @app_commands.describe(command="Specific command to get help for")
    @cooldown(1, 3.0)
    async def help(self, ctx: commands.Context, command: str | None = None) -> None:
        """Show help for all commands or a specific command."""
        if command:
            cmd = self.bot.get_command(command)
            if cmd is None:
                await ctx.send(f"Command `{command}` not found.", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"Help: {cmd.qualified_name}",
                description=cmd.help or cmd.description or "No description.",
                color=discord.Color.blue(),
            )
            if cmd.aliases:
                embed.add_field(name="Aliases", value=", ".join(f"`{a}`" for a in cmd.aliases))
            
            # Show subcommands if this is a group
            if isinstance(cmd, commands.Group):
                subcommands = [c for c in cmd.commands if not c.hidden]
                if subcommands:
                    subcommand_names = ", ".join(f"`{c.name}`" for c in sorted(subcommands, key=lambda c: c.name))
                    embed.add_field(name="Subcommands", value=subcommand_names, inline=False)
            
            usage = cmd.usage or cmd.signature
            if usage:
                embed.add_field(name="Usage", value=f"`{ctx.prefix}{cmd.qualified_name} {usage}`")
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title="Music Bot Commands",
            description=f"Use `{ctx.prefix}help <command>` for detailed info",
            color=discord.Color.blue(),
        )

        for cog_name, cog in sorted(self.bot.cogs.items()):
            cmds = [c for c in cog.get_commands() if not c.hidden]
            if not cmds:
                continue
            cmd_list = ", ".join(f"`{c.name}`" for c in sorted(cmds, key=lambda command: command.name))
            embed.add_field(name=cog_name, value=cmd_list, inline=False)

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="ping", description="Show bot latency")
    @cooldown(1, 3.0)
    async def ping(self, ctx: commands.Context) -> None:
        """Show the bot's WebSocket and API latency."""
        ws_latency = round(self.bot.latency * 1000)

        start = time.monotonic()
        msg = await ctx.send("Pinging...")
        api_latency = round((time.monotonic() - start) * 1000)

        await msg.edit(
            content=None,
            embed=discord.Embed(
                title="Pong!",
                description=f"WebSocket: **{ws_latency}ms**\nAPI: **{api_latency}ms**",
                color=discord.Color.green(),
            ),
        )

    @commands.hybrid_command(name="botinfo", description="Show bot information")
    @cooldown(1, 5.0)
    async def botinfo(self, ctx: commands.Context) -> None:
        """Show bot version and statistics."""
        embed = discord.Embed(title="Bot Info", color=discord.Color.blue())
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(
            name="Active Players",
            value=str(len(self.bot.players)),
            inline=True,
        )
        embed.add_field(
            name="Python",
            value=platform.python_version(),
            inline=True,
        )
        embed.add_field(name="discord.py", value=discord.__version__, inline=True)
        embed.add_field(name="Audio", value=self.bot.backend_manager.backend_status(), inline=False)
        embed.set_footer(text="Open source music bot")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="uptime", description="Show bot uptime")
    @cooldown(1, 3.0)
    async def uptime(self, ctx: commands.Context) -> None:
        """Show how long the bot has been running."""
        elapsed = int(time.monotonic() - self._start_time)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)

        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m {seconds}s")

        await ctx.send(f"Uptime: **{' '.join(parts)}**")

    @commands.hybrid_command(name="lyrics", description="Get lyrics for the current or specified song")
    @app_commands.describe(query="Song to search lyrics for (defaults to current track)")
    @cooldown(1, 5.0)
    async def lyrics(self, ctx: commands.Context, *, query: str | None = None) -> None:
        """Fetch lyrics for the current track or a search query."""
        if query is None:
            player = self.bot.get_player(ctx.guild.id)
            if player and player.current:
                query = player.current.title
            else:
                await ctx.send("Nothing playing and no query specified.", ephemeral=True)
                return

        await ctx.defer()

        try:
            from core.lyrics import fetch_lyrics

            lrc = await fetch_lyrics(query)
            if lrc:
                # Truncate to embed limit
                if len(lrc) > 4000:
                    lrc = lrc[:4000] + "\n..."

                embed = discord.Embed(
                    title=f"Lyrics: {query[:100]}",
                    description=lrc,
                    color=discord.Color.blue(),
                )
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"No lyrics found for: {query}")
        except ImportError:
            await ctx.send("Lyrics module not available.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Error fetching lyrics: {e}", ephemeral=True)

    @commands.hybrid_command(name="history", description="Show recently played tracks")
    @cooldown(1, 5.0)
    async def history(self, ctx: commands.Context) -> None:
        """Show the last 25 tracks played in this server."""
        from core.repositories import HistoryRepo

        entries = await HistoryRepo.get_recent(ctx.guild.id, limit=25)
        if not entries:
            await ctx.send("No play history yet.")
            return

        embed = discord.Embed(title="Play History", color=discord.Color.blue())
        lines = []
        for i, entry in enumerate(entries, 1):
            title = entry.track_title[:50]
            played = discord.utils.format_dt(entry.played_at, "R")
            lines.append(f"`{i}.` {title} — {played}")

        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="stats", description="Show server music statistics")
    @cooldown(1, 10.0)
    async def stats(self, ctx: commands.Context) -> None:
        """Show music usage statistics for this server."""
        from core.repositories import StatsRepo

        stats = await StatsRepo.get(ctx.guild.id)
        if not stats:
            await ctx.send("No stats available yet. Play some music first!")
            return

        hours = stats.total_seconds_played // 3600
        minutes = (stats.total_seconds_played % 3600) // 60

        embed = discord.Embed(title="Music Stats", color=discord.Color.gold())
        embed.add_field(name="Total Plays", value=str(stats.total_plays), inline=True)
        embed.add_field(
            name="Total Duration",
            value=f"{hours}h {minutes}m",
            inline=True,
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="feedback", description="Send feedback to the bot owner")
    @app_commands.describe(message="Your feedback message")
    @cooldown(1, 30.0)
    async def feedback(self, ctx: commands.Context, *, message: str) -> None:
        """Send feedback. Supports webhook, channel, and DM. Full in Phase 6."""
        embed = discord.Embed(
            title="Feedback",
            description=message,
            color=discord.Color.green(),
        )
        embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        embed.set_footer(text=f"Guild: {ctx.guild.name} ({ctx.guild.id})")

        sent = False

        # Try webhook
        if self.bot.config.feedback_webhook_url:
            try:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    webhook = discord.Webhook.from_url(
                        self.bot.config.feedback_webhook_url, session=session
                    )
                    await webhook.send(embed=embed)
                    sent = True
            except Exception:
                pass

        # Try channel
        if not sent and self.bot.config.feedback_channel_id:
            channel = self.bot.get_channel(self.bot.config.feedback_channel_id)
            if channel:
                await channel.send(embed=embed)
                sent = True

        # Try DM owner
        if not sent:
            app_info = await self.bot.application_info()
            if app_info.owner:
                try:
                    await app_info.owner.send(embed=embed)
                    sent = True
                except discord.Forbidden:
                    pass

        if sent:
            await ctx.send("Feedback sent! Thank you.", ephemeral=True)
        else:
            await ctx.send("Could not deliver feedback. Please try again later.", ephemeral=True)

    @commands.hybrid_command(name="musicquiz", description="Start a guess-the-song minigame")
    @cooldown(1, 30.0)
    async def musicquiz(self, ctx: commands.Context) -> None:
        """Start a music quiz based on this server's play history."""
        # Track active quizzes per guild
        if not hasattr(self, "_active_quizzes"):
            self._active_quizzes: dict[int, MusicQuiz] = {}

        if ctx.guild.id in self._active_quizzes and self._active_quizzes[ctx.guild.id].running:
            await ctx.send("A quiz is already running in this server!", ephemeral=True)
            return

        from core.quiz import MusicQuiz

        quiz = MusicQuiz(ctx, self.bot)
        self._active_quizzes[ctx.guild.id] = quiz

        try:
            await quiz.start()
        finally:
            self._active_quizzes.pop(ctx.guild.id, None)

    @commands.hybrid_command(name="ambience", description="Play ambient background sounds")
    @app_commands.describe(action="list, play, or stop", sound="Sound name (rain, cafe, etc.)")
    @cooldown(1, 5.0)
    async def ambience(self, ctx: commands.Context, action: str, sound: str | None = None) -> None:
        """Play ambient background sounds."""
        action = action.lower()

        if action == "list":
            embed = discord.Embed(
                title="Available Ambient Sounds",
                description="\n".join(f"• `{name}`" for name in sorted(AMBIENCE_QUERIES.keys())),
                color=discord.Color.green(),
            )
            embed.set_footer(text="Use !ambience play <sound> to start")
            await ctx.send(embed=embed)
            return

        if action == "stop":
            player = self.bot.get_player(ctx.guild.id)
            if player:
                await player.stop()
                await ctx.send("Ambience stopped.")
            else:
                await ctx.send("Nothing is playing.", ephemeral=True)
            return

        if action == "play":
            if not sound:
                await ctx.send(
                    "Specify a sound name. Use `!ambience list` to see options.", ephemeral=True
                )
                return

            sound_lower = sound.lower()
            if sound_lower not in AMBIENCE_QUERIES:
                available = ", ".join(f"`{n}`" for n in sorted(AMBIENCE_QUERIES.keys()))
                await ctx.send(f"Unknown sound. Available: {available}", ephemeral=True)
                return

            await ctx.defer()

            from core.extractor import search_track

            query = AMBIENCE_QUERIES[sound_lower]
            track = await search_track(query)
            if not track:
                await ctx.send("Could not find ambient sound.", ephemeral=True)
                return

            # Get or create player via Music cog
            music_cog = self.bot.get_cog("Music")
            if music_cog is None:
                await ctx.send("Music cog not loaded.", ephemeral=True)
                return

            player = await music_cog._get_or_create_player(ctx)
            player.queue.add(track)

            if not player.is_playing and not player.is_paused:
                await player.play_next()

            await ctx.send(
                embed=discord.Embed(
                    title=f"Ambience: {sound.title()}",
                    description=f"Now playing: **{track.short_title}**",
                    color=discord.Color.green(),
                )
            )
            return

        await ctx.send("Invalid action. Use `list`, `play`, or `stop`.", ephemeral=True)

    @commands.hybrid_command(name="voiceregion", description="Show voice server region")
    @cooldown(1, 5.0)
    async def voiceregion(self, ctx: commands.Context) -> None:
        """Show the current voice server region and latency."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.voice_client:
            await ctx.send("Not connected to a voice channel.", ephemeral=True)
            return

        channel = player.voice_client.channel
        region = getattr(channel, "rtc_region", None) or "Automatic"
        latency = round(self.bot.latency * 1000)

        await ctx.send(
            embed=discord.Embed(
                title="Voice Region",
                description=f"Region: **{region}**\nLatency: **{latency}ms**",
                color=discord.Color.blue(),
            )
        )

    @commands.hybrid_command(name="backend", description="Show the active audio backend")
    @cooldown(1, 5.0)
    async def backend(self, ctx: commands.Context) -> None:
        """Show guild backend and global backend health."""
        player = self.bot.get_player(ctx.guild.id)
        guild_backend = player.backend_name if player else "not connected"
        await ctx.send(
            embed=discord.Embed(
                title="Audio Backend",
                description=(
                    f"Guild backend: **{guild_backend}**\n"
                    f"Global status: **{self.bot.backend_manager.backend_status()}**"
                ),
                color=discord.Color.blue(),
            )
        )


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Utility(bot))
