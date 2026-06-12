"""Audio effects cog preset system and FX management."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from cachetools import TTLCache
from discord import app_commands
from discord.ext import commands

from core.checks import cooldown, is_dj
from core.errors import BotNotConnectedError, NothingPlayingError, PresetNotFoundError
from core.filters import (
    BUILTIN_PRESETS,
    PRESET_DESCRIPTIONS,
    WARNING_PRESETS,
    parse_preset_input,
    summarize_preset_definition,
)
from core.validation import validate_name

if TYPE_CHECKING:
    from bot import MusicBot

# Cap on custom FX presets per guild (prevents unbounded DB growth / slow listings).
MAX_CUSTOM_PRESETS = 50

# Short-TTL cache of per-guild custom preset names, so autocomplete (which fires
# per keystroke) doesn't hit the DB on every character.
_preset_name_cache: TTLCache[int, list[str]] = TTLCache(maxsize=500, ttl=30)


async def _guild_custom_preset_names(guild_id: int) -> list[str]:
    cached = _preset_name_cache.get(guild_id)
    if cached is not None:
        return cached
    try:
        from core.repositories import FXPresetRepo

        names = [p.name for p in await FXPresetRepo.list_for_guild(guild_id)]
    except Exception:
        return []
    _preset_name_cache[guild_id] = names
    return names


async def _fx_all_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete over built-in + this guild's custom preset names."""
    names = list(BUILTIN_PRESETS.keys())
    if interaction.guild_id:
        names.extend(await _guild_custom_preset_names(interaction.guild_id))
    cur = current.lower()
    matches = [n for n in sorted(set(names)) if cur in n.lower()][:25]
    return [app_commands.Choice(name=n, value=n) for n in matches]


async def _fx_custom_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete over only this guild's custom preset names (for delete/rename)."""
    names = await _guild_custom_preset_names(interaction.guild_id) if interaction.guild_id else []
    cur = current.lower()
    matches = [n for n in sorted(names) if cur in n.lower()][:25]
    return [app_commands.Choice(name=n, value=n) for n in matches]


class FX(commands.Cog):
    """Audio effects commands."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        settings = await self.bot.get_guild_settings(ctx.guild.id)
        if settings and settings.music_channel_id and ctx.channel.id != settings.music_channel_id:
            from core.errors import WrongChannelError

            raise WrongChannelError(settings.music_channel_id)
        return True

    @commands.hybrid_command(name="setfx", description="Apply an audio effect preset")
    @app_commands.describe(preset="Name of the preset to apply")
    @app_commands.autocomplete(preset=_fx_all_autocomplete)
    @is_dj()
    @cooldown(1, 3.0)
    async def setfx(self, ctx: commands.Context, preset: str) -> None:
        """Apply a built-in or custom FX preset."""
        player = self.bot.get_player(ctx.guild.id)
        if not player:
            raise BotNotConnectedError()
        if not player.current:
            raise NothingPlayingError()

        preset_lower = preset.lower()

        # Check if it's a valid preset
        if preset_lower not in BUILTIN_PRESETS:
            # Check custom presets
            from core.repositories import FXPresetRepo

            custom = await FXPresetRepo.get_by_name(ctx.guild.id, preset_lower)
            if custom is None:
                raise PresetNotFoundError(preset)

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
            raise BotNotConnectedError()

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
            raise BotNotConnectedError()

        if not player.active_filters:
            await ctx.send(
                embed=discord.Embed(
                    title="Active Effects",
                    description="No active effects.",
                    color=discord.Color.purple(),
                )
            )
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
            custom_lines = []
            for preset in custom_presets:
                definition = FXPresetRepo.get_definition(preset)
                summary = summarize_preset_definition(definition or {})
                custom_lines.append(f"`{preset.name}` — {summary}")
            embed.add_field(
                name="Custom",
                value="\n".join(custom_lines),
                inline=False,
            )

        await ctx.send(embed=embed)

    @fxpreset.command(name="create", description="Create a custom FX preset")
    @app_commands.describe(
        name="Preset name",
        filters="Structured preset JSON or a legacy raw FFmpeg filter string",
    )
    @is_dj()
    @cooldown(1, 5.0)
    async def fxpreset_create(self, ctx: commands.Context, name: str, *, filters: str) -> None:
        """Create a custom FX preset from structured JSON or a legacy filter string."""
        from core.repositories import FXPresetRepo

        try:
            name = validate_name(name, max_length=50, label="Preset name")
        except ValueError as exc:
            await ctx.send(str(exc), ephemeral=True)
            return

        existing = await FXPresetRepo.get_by_name(ctx.guild.id, name.lower())
        if existing:
            await ctx.send(f"A preset named `{name}` already exists.", ephemeral=True)
            return

        presets = await FXPresetRepo.list_for_guild(ctx.guild.id)
        if len(presets) >= MAX_CUSTOM_PRESETS:
            await ctx.send(
                f"This server has reached the limit of {MAX_CUSTOM_PRESETS} custom presets.",
                ephemeral=True,
            )
            return

        try:
            definition = parse_preset_input(filters)
        except ValueError as exc:
            await ctx.send(str(exc), ephemeral=True)
            return

        await FXPresetRepo.create(ctx.guild.id, name.lower(), definition, ctx.author.id)
        await ctx.send(
            f"Created preset **{name}** with effects: {summarize_preset_definition(definition)}"
        )

    @fxpreset.command(name="delete", description="Delete a custom FX preset")
    @app_commands.describe(name="Preset name to delete")
    @app_commands.autocomplete(name=_fx_custom_autocomplete)
    @is_dj()
    @cooldown(1, 5.0)
    async def fxpreset_delete(self, ctx: commands.Context, name: str) -> None:
        """Delete a custom FX preset."""
        from core.repositories import FXPresetRepo

        if await FXPresetRepo.delete_preset(ctx.guild.id, name.lower()):
            await ctx.send(f"Deleted preset **{name}**")
        else:
            raise PresetNotFoundError(name)

    @fxpreset.command(name="rename", description="Rename a custom FX preset")
    @app_commands.describe(old_name="Current preset name", new_name="New preset name")
    @app_commands.autocomplete(old_name=_fx_custom_autocomplete)
    @is_dj()
    @cooldown(1, 5.0)
    async def fxpreset_rename(self, ctx: commands.Context, old_name: str, new_name: str) -> None:
        """Rename a custom FX preset."""
        from core.repositories import FXPresetRepo

        if await FXPresetRepo.rename(ctx.guild.id, old_name.lower(), new_name.lower()):
            await ctx.send(f"Renamed preset **{old_name}** to **{new_name}**")
        else:
            raise PresetNotFoundError(old_name)

    @fxpreset.command(name="builder", description="Interactive FX preset builder")
    @is_dj()
    @cooldown(1, 10.0)
    async def fxpreset_builder(self, ctx: commands.Context) -> None:
        """Launch the interactive FX preset builder UI."""
        from core.ui.fx_builder import FXBuilderView

        view = FXBuilderView(ctx.guild.id, ctx.author.id, bot=self.bot)
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
