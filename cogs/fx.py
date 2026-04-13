"""Audio effects cog — preset system and FX management.

Phase 1 stub. Full implementation in Phase 4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from core.checks import cooldown, is_dj
from core.errors import BotNotConnected, NothingPlaying, PresetNotFound
from core.filters import BUILTIN_PRESETS, PRESET_DESCRIPTIONS, WARNING_PRESETS

if TYPE_CHECKING:
    from bot import MusicBot


class FX(commands.Cog):
    """Audio effects commands."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="setfx", description="Apply an audio effect preset")
    @app_commands.describe(preset="Name of the preset to apply")
    @is_dj()
    @cooldown(1, 3.0)
    async def setfx(self, ctx: commands.Context, preset: str) -> None:
        """Apply a built-in or custom FX preset."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnected()
        if not player.current:
            raise NothingPlaying()

        preset_lower = preset.lower()

        # Check if it's a valid preset
        if preset_lower not in BUILTIN_PRESETS:
            # Check custom presets
            from core.repositories import FXPresetRepo

            custom = await FXPresetRepo.get_by_name(ctx.guild.id, preset_lower)
            if custom is None:
                raise PresetNotFound(preset)

        # Warning for earrape etc
        if preset_lower in WARNING_PRESETS:
            await ctx.send(
                embed=discord.Embed(
                    title="Warning",
                    description=f"**{preset}** is extremely loud! Applying anyway...",
                    color=discord.Color.orange(),
                ),
            )

        await player.apply_filters([preset_lower])
        await ctx.send(
            embed=discord.Embed(
                title="FX Applied",
                description=f"Applied **{preset}** preset",
                color=discord.Color.purple(),
            )
        )

    @commands.hybrid_command(name="clearfx", description="Remove all audio effects")
    @is_dj()
    @cooldown(1, 3.0)
    async def clearfx(self, ctx: commands.Context) -> None:
        """Remove all active audio effects."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnected()

        await player.apply_filters([])
        await ctx.send(
            embed=discord.Embed(
                title="FX Cleared",
                description="All audio effects removed",
                color=discord.Color.green(),
            )
        )

    @commands.hybrid_command(name="currenteffects", description="Show active audio effects")
    @cooldown(1, 3.0)
    async def currenteffects(self, ctx: commands.Context) -> None:
        """Show the currently active FX preset."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnected()

        if not player.active_filters:
            await ctx.send("No active effects.")
            return

        filters = ", ".join(player.active_filters)
        await ctx.send(
            embed=discord.Embed(
                title="Active Effects",
                description=f"**{filters}**",
                color=discord.Color.purple(),
            )
        )

    @commands.hybrid_group(name="fxpreset", description="Manage FX presets")
    async def fxpreset(self, ctx: commands.Context) -> None:
        """FX preset management group. Use subcommands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @fxpreset.command(name="list", description="List all available FX presets")
    @cooldown(1, 3.0)
    async def fxpreset_list(self, ctx: commands.Context) -> None:
        """List all available FX presets (built-in + custom)."""
        embed = discord.Embed(title="FX Presets", color=discord.Color.purple())

        # Built-in presets
        builtin_lines = []
        for name in sorted(BUILTIN_PRESETS.keys()):
            desc = PRESET_DESCRIPTIONS.get(name, "")
            builtin_lines.append(f"`{name}` — {desc}")
        embed.add_field(
            name="Built-in",
            value="\n".join(builtin_lines),
            inline=False,
        )

        # Custom presets
        from core.repositories import FXPresetRepo

        custom_presets = await FXPresetRepo.list_for_guild(ctx.guild.id)
        if custom_presets:
            custom_lines = [f"`{p.name}` — {p.filter_string[:50]}" for p in custom_presets]
            embed.add_field(
                name="Custom",
                value="\n".join(custom_lines),
                inline=False,
            )

        await ctx.send(embed=embed)

    @fxpreset.command(name="create", description="Create a custom FX preset")
    @app_commands.describe(name="Preset name", filters="FFmpeg audio filter string")
    @is_dj()
    @cooldown(1, 5.0)
    async def fxpreset_create(self, ctx: commands.Context, name: str, *, filters: str) -> None:
        """Create a custom FX preset with an FFmpeg filter string."""
        from core.repositories import FXPresetRepo

        existing = await FXPresetRepo.get_by_name(ctx.guild.id, name.lower())
        if existing:
            await ctx.send(f"A preset named `{name}` already exists.", ephemeral=True)
            return

        await FXPresetRepo.create(ctx.guild.id, name.lower(), filters, ctx.author.id)
        await ctx.send(f"Created preset **{name}** with filter: `{filters}`")

    @fxpreset.command(name="delete", description="Delete a custom FX preset")
    @app_commands.describe(name="Preset name to delete")
    @is_dj()
    @cooldown(1, 5.0)
    async def fxpreset_delete(self, ctx: commands.Context, name: str) -> None:
        """Delete a custom FX preset."""
        from core.repositories import FXPresetRepo

        if await FXPresetRepo.delete_preset(ctx.guild.id, name.lower()):
            await ctx.send(f"Deleted preset **{name}**")
        else:
            raise PresetNotFound(name)

    @fxpreset.command(name="rename", description="Rename a custom FX preset")
    @app_commands.describe(old_name="Current preset name", new_name="New preset name")
    @is_dj()
    @cooldown(1, 5.0)
    async def fxpreset_rename(self, ctx: commands.Context, old_name: str, new_name: str) -> None:
        """Rename a custom FX preset."""
        from core.repositories import FXPresetRepo

        if await FXPresetRepo.rename(ctx.guild.id, old_name.lower(), new_name.lower()):
            await ctx.send(f"Renamed preset **{old_name}** to **{new_name}**")
        else:
            raise PresetNotFound(old_name)

    @fxpreset.command(name="builder", description="Interactive FX preset builder")
    @is_dj()
    @cooldown(1, 10.0)
    async def fxpreset_builder(self, ctx: commands.Context) -> None:
        """Launch the interactive FX preset builder UI."""
        from core.ui.fx_builder import FXBuilderView

        view = FXBuilderView(ctx.guild.id, ctx.author.id)
        await ctx.send(
            embed=discord.Embed(
                title="FX Preset Builder",
                description="Select effects to combine into a custom preset:",
                color=discord.Color.purple(),
            ),
            view=view,
        )


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(FX(bot))
