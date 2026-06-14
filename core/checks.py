"""Custom command check decorators for permission and voice state validation."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

import discord
from discord.ext import commands

from core.errors import (
    AdminRequiredError,
    BotNotConnectedError,
    DifferentVoiceChannelError,
    DJRequiredError,
    NotInVoiceChannelError,
    WrongChannelError,
)
from core.permissions import Tier, check_command_permission, check_tier, get_user_tier

if TYPE_CHECKING:
    pass

T = TypeVar("T")


def in_music_channel() -> Callable:
    """Check that the command is used in the configured music channel, if any."""

    async def predicate(ctx: commands.Context) -> bool:
        if hasattr(ctx.bot, "get_guild_settings"):
            settings = await ctx.bot.get_guild_settings(ctx.guild.id)
            if (
                settings
                and settings.music_channel_id
                and ctx.channel.id != settings.music_channel_id
            ):
                raise WrongChannelError(settings.music_channel_id)
        return True

    return commands.check(predicate)


def in_voice() -> Callable:
    """Check that the user is in a voice channel."""

    async def predicate(ctx: commands.Context) -> bool:
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
            raise NotInVoiceChannelError()
        return True

    return commands.check(predicate)


def bot_connected() -> Callable:
    """Check that the bot is connected to a voice channel."""

    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            raise BotNotConnectedError()
        return True

    return commands.check(predicate)


def same_channel() -> Callable:
    """Check that the user is in the same voice channel as the bot."""

    async def predicate(ctx: commands.Context) -> bool:
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
            raise NotInVoiceChannelError()
        if not ctx.voice_client or not ctx.voice_client.is_connected():
            raise BotNotConnectedError()
        if ctx.author.voice.channel != ctx.voice_client.channel:
            raise DifferentVoiceChannelError()
        return True

    return commands.check(predicate)


def is_dj() -> Callable:
    """Check that the user has DJ-tier permissions."""

    async def predicate(ctx: commands.Context) -> bool:
        # Check per-role permission overrides first
        override = await check_command_permission(ctx, ctx.command.qualified_name)
        if override is True:
            return True
        if override is False:
            raise DJRequiredError()

        # Get DJ role + lone-user-bypass setting from guild settings
        dj_role_id = None
        lone_user_dj = True
        if hasattr(ctx.bot, "get_guild_settings"):
            settings = await ctx.bot.get_guild_settings(ctx.guild.id)
            if settings:
                dj_role_id = settings.dj_role_id
                lone_user_dj = getattr(settings, "lone_user_dj", True)

        tier = await get_user_tier(ctx, dj_role_id, lone_user_dj)
        if not check_tier(tier, Tier.DJ):
            raise DJRequiredError()
        return True

    return commands.check(predicate)


def is_admin() -> Callable:
    """Check that the user has Admin-tier permissions."""

    async def predicate(ctx: commands.Context) -> bool:
        # Check per-role permission overrides first
        override = await check_command_permission(ctx, ctx.command.qualified_name)
        if override is True:
            return True
        if override is False:
            raise AdminRequiredError()

        tier = await get_user_tier(ctx)
        if not check_tier(tier, Tier.ADMIN):
            raise AdminRequiredError()
        return True

    return commands.check(predicate)


def cooldown(rate: int = 1, per: float = 5.0) -> Callable:
    """Apply a per-user command cooldown."""
    return commands.cooldown(rate, per, commands.BucketType.user)
