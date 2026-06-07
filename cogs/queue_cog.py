"""Queue management cog loop, shuffle, move, remove, clear, grab."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from core.checks import cooldown, is_dj
from core.errors import BotNotConnectedError, NothingPlayingError, QueueEmptyError
from core.queue import LoopMode

if TYPE_CHECKING:
    from bot import MusicBot


class QueueCog(commands.Cog, name="Queue"):
    """Queue management commands."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        settings = await self.bot.get_guild_settings(ctx.guild.id)
        if settings and settings.music_channel_id and ctx.channel.id != settings.music_channel_id:
            from core.errors import WrongChannelError

            raise WrongChannelError(settings.music_channel_id)
        return True

    @commands.hybrid_command(name="loop", description="Set loop mode")
    @app_commands.describe(mode="Loop mode: off, track, or queue")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Off", value="off"),
        app_commands.Choice(name="Track", value="track"),
        app_commands.Choice(name="Queue", value="queue"),
    ])
    @is_dj()
    @cooldown(1, 2.0)
    async def loop(self, ctx: commands.Context, mode: str) -> None:
        """Set the loop mode."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()

        try:
            loop_mode = LoopMode(mode.lower())
        except ValueError:
            await ctx.send("Invalid mode. Use `off`, `track`, or `queue`.", ephemeral=True)
            return

        player.queue.loop_mode = loop_mode
        await ctx.send(f"Loop mode set to **{loop_mode.value}**")

    @commands.hybrid_command(name="shuffle", description="Shuffle the queue")
    @is_dj()
    @cooldown(1, 3.0)
    async def shuffle(self, ctx: commands.Context) -> None:
        """Shuffle the current queue."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()
        if player.queue.is_empty:
            raise QueueEmptyError()

        player.queue.shuffle()
        await ctx.send(f"Shuffled **{player.queue.size}** tracks")

    @commands.hybrid_command(name="move", description="Move a track in the queue")
    @app_commands.describe(from_pos="Current position (1-indexed)", to_pos="New position (1-indexed)")
    @is_dj()
    @cooldown(1, 2.0)
    async def move(self, ctx: commands.Context, from_pos: int, to_pos: int) -> None:
        """Move a track from one position to another."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()

        track = player.queue.get(from_pos - 1)
        if not track:
            await ctx.send(f"No track at position {from_pos}.", ephemeral=True)
            return

        if player.queue.move(from_pos - 1, to_pos - 1):
            await ctx.send(f"Moved **{track.short_title}** to position **{to_pos}**")
        else:
            await ctx.send("Failed to move track.", ephemeral=True)

    @commands.hybrid_command(name="remove", description="Remove a track from the queue")
    @app_commands.describe(position="Position to remove (1-indexed)")
    @is_dj()
    @cooldown(1, 2.0)
    async def remove(self, ctx: commands.Context, position: int) -> None:
        """Remove a track at a given position from the queue."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()

        track = player.queue.remove(position - 1)
        if track:
            await ctx.send(f"Removed **{track.short_title}** from the queue")
        else:
            await ctx.send(f"No track at position {position}.", ephemeral=True)

    @commands.hybrid_command(name="clear", description="Clear the queue")
    @is_dj()
    @cooldown(1, 3.0)
    async def clear(self, ctx: commands.Context) -> None:
        """Clear all tracks from the queue (keeps current track playing)."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()

        count = player.queue.clear()
        await ctx.send(f"Cleared **{count}** tracks from the queue")

    @commands.hybrid_command(name="grab", description="DM yourself the current track info")
    @cooldown(1, 5.0)
    async def grab(self, ctx: commands.Context) -> None:
        """DM the current track info to yourself."""
        player = self.bot.get_player(ctx.guild.id)
        if not player or not player.current:
            raise NothingPlayingError()

        track = player.current
        embed = discord.Embed(
            title="Saved Track",
            description=f"**[{track.title}]({track.url})**",
            color=discord.Color.green(),
        )
        embed.add_field(name="Duration", value=track.duration_str, inline=True)
        embed.add_field(name="Source", value=track.source, inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        embed.set_footer(text=f"From: {ctx.guild.name}")

        try:
            await ctx.author.send(embed=embed)
            await ctx.send("Track info sent to your DMs!", ephemeral=True)
        except discord.Forbidden:
            await ctx.send("Couldn't send DM. Please enable DMs from server members.", ephemeral=True)


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(QueueCog(bot))
