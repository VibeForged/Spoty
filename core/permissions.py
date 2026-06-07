"""Three-tier permission system: Everyone, DJ, Admin."""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from discord.ext.commands import Context


class Tier(IntEnum):
    """Permission tiers, ordered by privilege level."""

    EVERYONE = 0
    DJ = 1
    ADMIN = 2
    OWNER = 3


async def get_user_tier(
    ctx: Context,
    dj_role_id: int | None = None,
) -> Tier:
    """Determine a user's permission tier in the current guild.

    Priority:
    1. Bot owner -> OWNER (bypasses all)
    2. Guild admin (manage_guild) -> ADMIN
    3. Has DJ role -> DJ
    4. Alone in VC with bot -> DJ (lone-user bypass)
    5. Default -> EVERYONE

    Args:
        ctx: The command context.
        dj_role_id: The guild's configured DJ role ID (from guild_settings).

    Returns:
        The user's effective permission tier.
    """
    # Bot owner bypasses everything
    if await ctx.bot.is_owner(ctx.author):
        return Tier.OWNER

    member = ctx.author
    if not isinstance(member, discord.Member):
        return Tier.EVERYONE

    # Guild admin
    if member.guild_permissions.manage_guild:
        return Tier.ADMIN

    # DJ role check
    if dj_role_id is not None and any(role.id == dj_role_id for role in member.roles):
        return Tier.DJ

    # Lone-user bypass: if user is alone in VC with the bot, treat as DJ
    if member.voice and member.voice.channel:
        voice_channel = member.voice.channel
        non_bot_members = [m for m in voice_channel.members if not m.bot]
        if len(non_bot_members) == 1:
            return Tier.DJ

    # Fallback: if no DJ role is configured, manage_channels acts as DJ
    if dj_role_id is None and member.guild_permissions.manage_channels:
        return Tier.DJ

    return Tier.EVERYONE


def check_tier(user_tier: Tier, required_tier: Tier) -> bool:
    """Check if a user's tier meets or exceeds the required tier."""
    return user_tier >= required_tier


async def check_command_permission(ctx: Context, command_name: str) -> bool | None:
    """Check per-role command permission overrides.

    Returns:
        True if explicitly allowed, False if explicitly denied, None if no overrides match.
    """
    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        return None

    from core.repositories import PermissionRepo

    overrides = await PermissionRepo.get_for_command(ctx.guild.id, command_name)
    if not overrides:
        return None

    member_role_ids = {role.id for role in ctx.author.roles}
    has_allow = False
    has_deny = False

    for override in overrides:
        if override.role_id in member_role_ids:
            if override.allowed:
                has_allow = True
            else:
                has_deny = True

    if has_allow:
        return True
    if has_deny:
        return False
    return None
