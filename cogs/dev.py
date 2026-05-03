"""Dev/Admin cog owner-only commands for bot management."""

from __future__ import annotations

import os
import platform
import sys
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from loguru import logger

if TYPE_CHECKING:
    from bot import MusicBot


class Dev(commands.Cog):
    """Owner-only development and admin commands."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        """All commands in this cog require bot owner."""
        return await self.bot.is_owner(ctx.author)

    @commands.command(name="reload")
    async def reload(self, ctx: commands.Context, cog_name: str) -> None:
        """Hot-reload a cog by name.

        Usage: !reload music
        """
        # Normalize cog name
        if not cog_name.startswith("cogs."):
            cog_name = f"cogs.{cog_name}"

        try:
            await self.bot.reload_extension(cog_name)
            logger.info("Reloaded cog: {}", cog_name)
            await ctx.send(f"Reloaded `{cog_name}`")
        except commands.ExtensionNotLoaded:
            try:
                await self.bot.load_extension(cog_name)
                logger.info("Loaded cog: {}", cog_name)
                await ctx.send(f"Loaded `{cog_name}`")
            except Exception as e:
                await ctx.send(f"Failed to load `{cog_name}`: {e}")
        except Exception as e:
            logger.error("Failed to reload {}: {}", cog_name, e)
            await ctx.send(f"Failed to reload `{cog_name}`: {e}")

    @commands.command(name="debuginfo")
    async def debuginfo(self, ctx: commands.Context) -> None:
        """Show debug information about the bot."""
        import yt_dlp

        # Memory usage
        try:
            import psutil

            process = psutil.Process(os.getpid())
            mem = process.memory_info()
            ram_mb = mem.rss / 1024 / 1024
            cpu_pct = process.cpu_percent(interval=0.1)
        except ImportError:
            ram_mb = 0
            cpu_pct = 0

        # DB size
        db_size = "N/A"
        db_path = "data/bot.db"
        if os.path.exists(db_path):
            size_bytes = os.path.getsize(db_path)
            db_size = f"{size_bytes / 1024:.1f} KB"

        embed = discord.Embed(title="Debug Info", color=discord.Color.dark_grey())
        embed.add_field(name="Python", value=platform.python_version(), inline=True)
        embed.add_field(name="discord.py", value=discord.__version__, inline=True)
        embed.add_field(name="yt-dlp", value=yt_dlp.version.__version__, inline=True)
        embed.add_field(name="Platform", value=platform.platform()[:40], inline=True)
        embed.add_field(name="RAM Usage", value=f"{ram_mb:.1f} MB", inline=True)
        embed.add_field(name="CPU Usage", value=f"{cpu_pct:.1f}%", inline=True)
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Active Players", value=str(len(self.bot.players)), inline=True)
        embed.add_field(name="DB Size", value=db_size, inline=True)
        embed.add_field(
            name="Audio Backend",
            value=self.bot.backend_manager.backend_status(),
            inline=False,
        )
        embed.add_field(
            name="Loaded Cogs",
            value=", ".join(self.bot.cogs.keys()),
            inline=False,
        )

        await ctx.send(embed=embed)

    @commands.command(name="sync")
    async def sync(self, ctx: commands.Context) -> None:
        """Force-sync slash commands with Discord."""
        msg = await ctx.send("Syncing slash commands...")
        try:
            synced = await self.bot.tree.sync()
            await msg.edit(content=f"Synced **{len(synced)}** slash commands globally.")
            logger.info("Synced {} slash commands", len(synced))
        except Exception as e:
            await msg.edit(content=f"Sync failed: {e}")
            logger.error("Slash command sync failed: {}", e)


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Dev(bot))
