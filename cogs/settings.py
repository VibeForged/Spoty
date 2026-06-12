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
            name="Lone-user DJ",
            value=str(getattr(gs, "lone_user_dj", True)),
            inline=True,
        )
        skip_pct = getattr(gs, "skip_vote_threshold", 0)
        embed.add_field(
            name="Vote-skip",
            value=f"{skip_pct}%" if skip_pct > 0 else "Off (DJ-only)",
            inline=True,
        )
        embed.add_field(
            name="Inactivity Timeout",
            value=f"{gs.inactivity_timeout}s" if gs.inactivity_timeout > 0 else "24/7 Mode (Never)",
            inline=True,
        )
        await ctx.send(embed=embed)

    @settings.command(
        name="lone_user_dj",
        description="Toggle whether a user alone in the voice channel gets DJ permissions",
    )
    @is_admin()
    @cooldown(1, 5.0)
    async def settings_lone_user_dj(self, ctx: commands.Context) -> None:
        """Toggle the lone-user-in-VC DJ bypass."""
        from core.repositories import GuildSettingsRepo

        gs = await self.bot.get_guild_settings(ctx.guild.id)
        new_val = not getattr(gs, "lone_user_dj", True)

        await GuildSettingsRepo.update(ctx.guild.id, lone_user_dj=new_val)
        self.bot.invalidate_settings_cache(ctx.guild.id)

        if new_val:
            msg = "Lone-user DJ **enabled**. A user alone in the voice channel gets DJ permissions."
        else:
            msg = "Lone-user DJ **disabled**. DJ permissions now require the DJ role or admin."
        await ctx.send(msg)

    @settings.command(
        name="skip_vote",
        description="Set the % of listeners needed to vote-skip (0 = DJ-only)",
    )
    @app_commands.describe(percent="Percentage 0-100 (0 disables vote-skip; DJs always skip)")
    @is_admin()
    @cooldown(1, 5.0)
    async def settings_skip_vote(self, ctx: commands.Context, percent: int) -> None:
        """Configure the vote-skip threshold."""
        from core.repositories import GuildSettingsRepo

        if percent < 0 or percent > 100:
            await ctx.send("Percentage must be between 0 and 100.", ephemeral=True)
            return

        await GuildSettingsRepo.update(ctx.guild.id, skip_vote_threshold=percent)
        self.bot.invalidate_settings_cache(ctx.guild.id)

        if percent == 0:
            await ctx.send("Vote-skip **disabled**. Only DJs/admins can skip.")
        else:
            await ctx.send(f"Vote-skip set to **{percent}%** of listeners in the channel.")

    @settings.command(name="247", description="Toggle 24/7 mode (stay in voice channel forever)")
    @is_admin()
    @cooldown(1, 5.0)
    async def settings_247(self, ctx: commands.Context) -> None:
        """Toggle 24/7 mode. When enabled, the bot will never leave the voice channel due to inactivity."""
        from core.repositories import GuildSettingsRepo

        gs = await self.bot.get_guild_settings(ctx.guild.id)
        current = getattr(gs, "inactivity_timeout", 300)

        if current <= 0:
            # 24/7 is currently on, turn it off (default to 300s)
            new_val = 300
            msg = "24/7 mode **disabled**. The bot will now leave after 5 minutes of inactivity."
        else:
            # Turn 24/7 on (set timeout to 0)
            new_val = 0
            msg = "24/7 mode **enabled**. The bot will stay in the voice channel indefinitely."

        await GuildSettingsRepo.update(ctx.guild.id, inactivity_timeout=new_val)
        self.bot.invalidate_settings_cache(ctx.guild.id)

        # Apply instantly to the active player if it exists
        player = self.bot.get_player(ctx.guild.id)
        if player:
            if new_val == 0:
                player._cancel_inactive_timer()
            elif not player.is_playing:
                player._start_inactive_timer()

        await ctx.send(msg)

    @settings.command(name="default_volume", description="Set default playback volume")
    @app_commands.describe(volume="Default volume (0-100)")
    @is_admin()
    @cooldown(1, 5.0)
    async def settings_default_volume(self, ctx: commands.Context, volume: int) -> None:
        """Set the default volume for new playback sessions."""
        if volume < 0 or volume > 100:
            await ctx.send("Volume must be between 0 and 100.", ephemeral=True)
            return
        from core.repositories import GuildSettingsRepo

        await GuildSettingsRepo.update(ctx.guild.id, default_volume=volume)
        self.bot.invalidate_settings_cache(ctx.guild.id)
        await ctx.send(f"Default volume set to **{volume}%**")

    @settings.command(name="announce_songs", description="Toggle now-playing announcements")
    @app_commands.describe(enabled="on or off")
    @app_commands.choices(
        enabled=[
            app_commands.Choice(name="on", value="on"),
            app_commands.Choice(name="off", value="off"),
        ]
    )
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
    @app_commands.choices(
        enabled=[
            app_commands.Choice(name="on", value="on"),
            app_commands.Choice(name="off", value="off"),
        ]
    )
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
    @app_commands.choices(
        action=[
            app_commands.Choice(name="allow", value="allow"),
            app_commands.Choice(name="deny", value="deny"),
        ]
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
            from core.ui.confirm import confirm_action

            if not await confirm_action(
                ctx, "Reset **all** permission overrides for this server? This cannot be undone."
            ):
                await ctx.send("Cancelled.", ephemeral=True)
                return
            count = await PermissionRepo.reset_all(ctx.guild.id)
            await ctx.send(f"Removed **{count}** permission override(s) for this server.")


    @commands.hybrid_command(name="setup", description="Setup the dedicated music channel and control panel")
    @is_admin()
    @cooldown(1, 10.0)
    async def setup_music(self, ctx: commands.Context) -> None:
        """Create a dedicated #music-requests channel with a persistent control panel."""
        await ctx.defer()

        # Check if we already have one
        from core.repositories import GuildSettingsRepo
        gs = await self.bot.get_guild_settings(ctx.guild.id)

        channel = None
        if gs and gs.music_channel_id:
            channel = ctx.guild.get_channel(gs.music_channel_id)

        if not channel:
            # Create a new channel
            overwrites = {
                ctx.guild.default_role: discord.PermissionOverwrite(send_messages=True),
                ctx.guild.me: discord.PermissionOverwrite(send_messages=True, embed_links=True, read_message_history=True)
            }
            try:
                channel = await ctx.guild.create_text_channel(
                    name="music-requests",
                    topic="Request songs here and use the control panel below!",
                    overwrites=overwrites,
                    reason="Spoty Music Bot Setup"
                )
            except discord.Forbidden:
                await ctx.send("I don't have permission to create channels!", ephemeral=True)
                return

        from core.ui.player_control import PlayerControlPanel, build_panel_embed
        player = self.bot.get_player(ctx.guild.id)

        embed = build_panel_embed(player)
        view = PlayerControlPanel(self.bot, ctx.guild.id)

        # Clear the channel if it's new or just to clean it up (optional, let's just send)
        msg = await channel.send(embed=embed, view=view)

        await GuildSettingsRepo.update(
            ctx.guild.id,
            music_channel_id=channel.id,
            panel_message_id=msg.id
        )
        self.bot.invalidate_settings_cache(ctx.guild.id)

        await ctx.send(f"Setup complete! Head over to {channel.mention} to control the music.", ephemeral=True)


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Settings(bot))

