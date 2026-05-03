"""Settings cog per-guild configuration management."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from core.checks import cooldown, is_admin, is_dj

if TYPE_CHECKING:
    from bot import MusicBot


class Settings(commands.Cog):
    """Server configuration commands."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="settings", description="View or modify server settings")
    async def settings(self, ctx: commands.Context) -> None:
        """Server settings. Use subcommands."""
        if ctx.invoked_subcommand is None:
            await self.settings_view(ctx)

    @settings.command(name="view", description="View current server settings")
    @cooldown(1, 5.0)
    async def settings_view(self, ctx: commands.Context) -> None:
        """Show all current server configuration."""
        gs = await self.bot.get_guild_settings(ctx.guild.id)
        if not gs:
            await ctx.send("No settings found.", ephemeral=True)
            return

        embed = discord.Embed(title="Server Settings", color=discord.Color.blue())
        embed.add_field(name="Prefix", value=f"`{gs.prefix}`", inline=True)
        embed.add_field(name="Default Volume", value=f"{gs.default_volume}%", inline=True)
        embed.add_field(
            name="DJ Role",
            value=f"<@&{gs.dj_role_id}>" if gs.dj_role_id else "Not set",
            inline=True,
        )
        embed.add_field(
            name="Music Channel",
            value=f"<#{gs.music_channel_id}>" if gs.music_channel_id else "Any",
            inline=True,
        )
        embed.add_field(name="Announce Songs", value=str(gs.announce_songs), inline=True)
        embed.add_field(name="Interactive Buttons", value=str(gs.interactive_buttons), inline=True)
        embed.add_field(name="Auto-DJ", value=str(gs.autoplay), inline=True)
        embed.add_field(name="Queue Locked", value=str(gs.queue_locked), inline=True)
        embed.add_field(
            name="Inactivity Timeout",
            value=f"{gs.inactivity_timeout}s",
            inline=True,
        )
        await ctx.send(embed=embed)

    @settings.command(name="default_volume", description="Set default playback volume")
    @app_commands.describe(volume="Default volume (0-100)")
    @is_admin()
    @cooldown(1, 5.0)
    async def settings_default_volume(self, ctx: commands.Context, volume: int) -> None:
        """Set the default volume for new playback sessions."""
        volume = max(0, min(volume, 100))
        from core.repositories import GuildSettingsRepo

        await GuildSettingsRepo.update(ctx.guild.id, default_volume=volume)
        self.bot.invalidate_settings_cache(ctx.guild.id)
        await ctx.send(f"Default volume set to **{volume}%**")

    @settings.command(name="announce_songs", description="Toggle now-playing announcements")
    @app_commands.describe(enabled="on or off")
    @is_admin()
    @cooldown(1, 5.0)
    async def settings_announce(self, ctx: commands.Context, enabled: str) -> None:
        """Toggle automatic now-playing announcements."""
        value = enabled.lower() in ("on", "true", "yes", "1")
        from core.repositories import GuildSettingsRepo

        await GuildSettingsRepo.update(ctx.guild.id, announce_songs=value)
        self.bot.invalidate_settings_cache(ctx.guild.id)
        await ctx.send(f"Song announcements **{'enabled' if value else 'disabled'}**")

    @settings.command(name="interactive_buttons", description="Toggle now-playing buttons")
    @app_commands.describe(enabled="on or off")
    @is_admin()
    @cooldown(1, 5.0)
    async def settings_buttons(self, ctx: commands.Context, enabled: str) -> None:
        """Toggle interactive buttons on now-playing embeds."""
        value = enabled.lower() in ("on", "true", "yes", "1")
        from core.repositories import GuildSettingsRepo

        await GuildSettingsRepo.update(ctx.guild.id, interactive_buttons=value)
        self.bot.invalidate_settings_cache(ctx.guild.id)
        await ctx.send(f"Interactive buttons **{'enabled' if value else 'disabled'}**")

    @settings.command(name="set_music_channel", description="Restrict music commands to a channel")
    @app_commands.describe(channel="Channel to restrict to (leave empty to allow all)")
    @is_admin()
    @cooldown(1, 5.0)
    async def settings_music_channel(
        self, ctx: commands.Context, channel: discord.TextChannel | None = None
    ) -> None:
        """Restrict music commands to a specific channel."""
        from core.repositories import GuildSettingsRepo

        channel_id = channel.id if channel else None
        await GuildSettingsRepo.update(ctx.guild.id, music_channel_id=channel_id)
        self.bot.invalidate_settings_cache(ctx.guild.id)

        if channel:
            await ctx.send(f"Music commands restricted to {channel.mention}")
        else:
            await ctx.send("Music commands allowed in any channel")

    @commands.hybrid_command(name="prefix", description="Set the bot's command prefix")
    @app_commands.describe(new_prefix="New prefix symbol")
    @is_admin()
    @cooldown(1, 10.0)
    async def prefix(self, ctx: commands.Context, new_prefix: str) -> None:
        """Change the bot's command prefix for this server."""
        if len(new_prefix) > 10:
            await ctx.send("Prefix must be 10 characters or fewer.", ephemeral=True)
            return

        from core.repositories import GuildSettingsRepo

        await GuildSettingsRepo.update(ctx.guild.id, prefix=new_prefix)
        self.bot.invalidate_settings_cache(ctx.guild.id)
        await ctx.send(f"Prefix changed to `{new_prefix}`")

    @commands.hybrid_command(name="set_dj_role", aliases=["setdj"], description="Set the DJ role")
    @app_commands.describe(role="Role to designate as DJ")
    @is_admin()
    @cooldown(1, 10.0)
    async def set_dj_role(self, ctx: commands.Context, role: discord.Role) -> None:
        """Set the DJ role for this server."""
        from core.repositories import GuildSettingsRepo

        await GuildSettingsRepo.update(ctx.guild.id, dj_role_id=role.id)
        self.bot.invalidate_settings_cache(ctx.guild.id)
        await ctx.send(f"DJ role set to {role.mention}")

    @commands.hybrid_command(name="autoplay", description="Toggle Auto-DJ")
    @is_dj()
    @cooldown(1, 5.0)
    async def autoplay(self, ctx: commands.Context) -> None:
        """Toggle Auto-DJ (automatically plays related tracks when queue empties)."""
        gs = await self.bot.get_guild_settings(ctx.guild.id)
        new_value = not gs.autoplay

        from core.repositories import GuildSettingsRepo

        await GuildSettingsRepo.update(ctx.guild.id, autoplay=new_value)
        self.bot.invalidate_settings_cache(ctx.guild.id)
        await ctx.send(f"Auto-DJ **{'enabled' if new_value else 'disabled'}**")

    @commands.hybrid_command(name="lockqueue", description="Toggle queue lock")
    @is_dj()
    @cooldown(1, 5.0)
    async def lockqueue(self, ctx: commands.Context) -> None:
        """Lock/unlock the queue (when locked, only DJs can add tracks)."""
        gs = await self.bot.get_guild_settings(ctx.guild.id)
        new_value = not gs.queue_locked

        from core.repositories import GuildSettingsRepo

        await GuildSettingsRepo.update(ctx.guild.id, queue_locked=new_value)
        self.bot.invalidate_settings_cache(ctx.guild.id)
        await ctx.send(f"Queue **{'locked' if new_value else 'unlocked'}**")

    @commands.hybrid_group(
        name="permissions", aliases=["perms"], description="Manage command permissions"
    )
    @is_admin()
    async def permissions(self, ctx: commands.Context) -> None:
        """Manage per-role command permissions."""
        if ctx.invoked_subcommand is None:
            await self.permissions_view(ctx)

    @permissions.command(name="view", description="View all permission overrides")
    @cooldown(1, 5.0)
    async def permissions_view(self, ctx: commands.Context) -> None:
        """List all permission overrides for this server."""
        from core.repositories import PermissionRepo

        overrides = await PermissionRepo.get_overrides(ctx.guild.id)
        if not overrides:
            await ctx.send("No permission overrides configured.", ephemeral=True)
            return

        # Group by command name
        grouped: dict[str, list] = {}
        for override in overrides:
            grouped.setdefault(override.command_name, []).append(override)

        embed = discord.Embed(title="Permission Overrides", color=discord.Color.blue())
        for cmd_name, cmd_overrides in sorted(grouped.items()):
            lines = []
            for o in cmd_overrides:
                action = "Allow" if o.allowed else "Deny"
                lines.append(f"<@&{o.role_id}> — {action}")
            embed.add_field(name=f"/{cmd_name}", value="\n".join(lines), inline=False)

        await ctx.send(embed=embed)

    @permissions.command(name="set", description="Set a permission override for a command")
    @app_commands.describe(
        command="Command name", role="Role to set permission for", action="allow or deny"
    )
    @cooldown(1, 5.0)
    async def permissions_set(
        self, ctx: commands.Context, command: str, role: discord.Role, action: str
    ) -> None:
        """Set a permission override for a command and role."""
        # Validate command exists
        bot_command = self.bot.get_command(command)
        if bot_command is None:
            await ctx.send(f"Unknown command: `{command}`", ephemeral=True)
            return

        action_lower = action.lower()
        if action_lower not in ("allow", "deny"):
            await ctx.send("Action must be `allow` or `deny`.", ephemeral=True)
            return

        allowed = action_lower == "allow"
        from core.repositories import PermissionRepo

        await PermissionRepo.set_override(
            ctx.guild.id, bot_command.qualified_name, role.id, allowed
        )
        action_word = "allowed" if allowed else "denied"
        await ctx.send(
            f"**{bot_command.qualified_name}** is now **{action_word}** for {role.mention}."
        )

    @permissions.command(name="remove", description="Remove a permission override")
    @app_commands.describe(command="Command name", role="Role to remove override for")
    @cooldown(1, 5.0)
    async def permissions_remove(
        self, ctx: commands.Context, command: str, role: discord.Role
    ) -> None:
        """Remove a specific permission override."""
        from core.repositories import PermissionRepo

        removed = await PermissionRepo.remove_override(ctx.guild.id, command, role.id)
        if removed:
            await ctx.send(
                f"Removed permission override for **{command}** on {role.mention}."
            )
        else:
            await ctx.send(
                f"No override found for **{command}** on {role.mention}.", ephemeral=True
            )

    @permissions.command(name="reset", description="Reset permission overrides")
    @app_commands.describe(command="Command to reset (leave empty to reset all)")
    @cooldown(1, 5.0)
    async def permissions_reset(
        self, ctx: commands.Context, command: str | None = None
    ) -> None:
        """Reset permission overrides for a command or all commands."""
        from core.repositories import PermissionRepo

        if command:
            count = await PermissionRepo.reset_command(ctx.guild.id, command)
            await ctx.send(f"Removed **{count}** override(s) for **{command}**.")
        else:
            count = await PermissionRepo.reset_all(ctx.guild.id)
            await ctx.send(f"Removed **{count}** permission override(s) for this server.")


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Settings(bot))
