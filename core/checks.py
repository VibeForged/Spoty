"""Custom command check decorators for permission and voice state validation."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, Callable, TypeVar

import discord
from discord.ext import commands

from core.errors import (
    AdminRequired,
    BotNotConnected,
    DifferentVoiceChannel,
    DJRequired,
    NotInVoiceChannel,
)
from core.permissions import Tier, check_tier, get_user_tier

if TYPE_CHECKING:
    pass

T = TypeVar("T")


def in_voice() -> Callable:
    """Check that the user is in a voice channel."""

    async def predicate(ctx: commands.Context) -> bool:
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
            raise NotInVoiceChannel()
        return True

    return commands.check(predicate)


def bot_connected() -> Callable:
    """Check that the bot is connected to a voice channel."""

    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            raise BotNotConnected()
        return True

    return commands.check(predicate)


def same_channel() -> Callable:
    """Check that the user is in the same voice channel as the bot."""

    async def predicate(ctx: commands.Context) -> bool:
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
            raise NotInVoiceChannel()
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            raise BotNotConnected()
        if ctx.author.voice.channel != ctx.voice_client.channel:
            raise DifferentVoiceChannel()
        return True

    return commands.check(predicate)


def is_dj() -> Callable:
    """Check that the user has DJ-tier permissions."""

    async def predicate(ctx: commands.Context) -> bool:
        # Get DJ role from guild settings
        dj_role_id = None
        if hasattr(ctx.bot, "get_guild_settings"):
            settings = await ctx.bot.get_guild_settings(ctx.guild.id)
            if settings:
                dj_role_id = settings.dj_role_id

        tier = await get_user_tier(ctx, dj_role_id)
        if not check_tier(tier, Tier.DJ):
            raise DJRequired()
        return True

    return commands.check(predicate)


def is_admin() -> Callable:
    """Check that the user has Admin-tier permissions."""

    async def predicate(ctx: commands.Context) -> bool:
        tier = await get_user_tier(ctx)
        if not check_tier(tier, Tier.ADMIN):
            raise AdminRequired()
        return True

    return commands.check(predicate)


def cooldown(rate: int = 1, per: float = 5.0) -> Callable:
    """Apply a per-user command cooldown."""
    return commands.cooldown(rate, per, commands.BucketType.user)
