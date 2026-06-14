"""Soundboard cog for playing short audio clips in voice channels."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from core.checks import cooldown, is_dj
from core.errors import VoiceConnectionFailedError

if TYPE_CHECKING:
    from bot import MusicBot
    from core.player import MusicPlayer

BUILTIN_SOUNDS = {
    "airhorn": "https://www.myinstants.com/media/sounds/mlg-airhorn.mp3",
    "bruh": "https://www.myinstants.com/media/sounds/bruh.mp3",
    "sad_violin": "https://www.myinstants.com/media/sounds/sad-violin.mp3",
    "applause": "https://www.myinstants.com/media/sounds/applause_4.mp3",
    "fart": "https://www.myinstants.com/media/sounds/fart-sound-effect.mp3",
    "tada": "https://www.myinstants.com/media/sounds/tada.mp3",
    "victory": "https://www.myinstants.com/media/sounds/victory.mp3",
    "directed_by": "https://www.myinstants.com/media/sounds/directed-by-robert-b-weide.mp3",
}


async def soundboard_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Suggest built-in and guild-custom soundboard sounds."""
    builtins = list(BUILTIN_SOUNDS.keys())
    customs = []

    if interaction.guild_id:
        try:
            from core.repositories import SoundboardRepo

            db_sounds = await SoundboardRepo.get_all(interaction.guild_id)
            customs = [s.name for s in db_sounds]
        except Exception:
            pass

    all_sounds = sorted(list(set(builtins + customs)))

    current_lower = current.lower()
    choices = []
    for name in all_sounds:
        if current_lower in name.lower():
            choices.append(app_commands.Choice(name=name, value=name))
        if len(choices) >= 25:
            break
    return choices


class Soundboard(commands.Cog):
    """Soundboard commands to play short audio clips."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        settings = await self.bot.get_guild_settings(ctx.guild.id)
        if settings and settings.music_channel_id and ctx.channel.id != settings.music_channel_id:
            from core.errors import WrongChannelError

            raise WrongChannelError(settings.music_channel_id)
        return True

    async def _get_or_create_player(self, ctx: commands.Context) -> MusicPlayer:
        """Get existing player or create a new one by joining the user's VC."""
        guild_id = ctx.guild.id
        player = self.bot.get_player(guild_id)

        if player and player.is_connected:
            return player

        if player:
            await player.destroy()

        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
            from core.errors import NotInVoiceChannelError

            raise NotInVoiceChannelError()

        channel = ctx.author.voice.channel

        try:
            player = await self.bot.create_player(guild_id, channel, ctx.channel)
        except Exception as e:
            raise VoiceConnectionFailedError(str(e)) from e

        settings = await self.bot.get_guild_settings(guild_id)
        if settings:
            player.volume = settings.default_volume

        return player

    async def play_sound(self, ctx: commands.Context, sound_url: str, sound_name: str) -> None:
        """Play the soundboard sound, temporarily pausing the queue if active."""
        player = await self._get_or_create_player(ctx)
        player.text_channel = ctx.channel

        from core.track import Track

        sound_track = Track(title=f"Soundboard: {sound_name}", url=sound_url, source="soundboard")
        sound_track.requester_name = ctx.author.display_name
        sound_track.requester_id = ctx.author.id

        # Resolve extraction (important for both FFmpeg / Lavalink wrapper)
        from core.extractor import search_track

        resolved = await search_track(sound_url)
        if resolved:
            sound_track.url = resolved.url
            sound_track.stream_url = resolved.stream_url
            sound_track.duration = resolved.duration
        else:
            sound_track.stream_url = sound_url

        currently_playing = player.current
        position = 0
        was_playing = player.is_playing or player.is_paused

        # Cancel the player wait task to prevent sound completion from triggering next song
        if player._play_task and not player._play_task.done():
            player._play_task.cancel()
            player._play_task = None

        if was_playing and currently_playing:
            position = player.position_ms
            await player.pause()

        await ctx.send(f"🔊 Playing soundboard sound: `{sound_name}`")

        settings = await self.bot.get_guild_settings(ctx.guild.id)
        sb_volume = getattr(settings, "soundboard_volume", 60) if settings else 60

        try:
            player.current = sound_track
            await player._backend.set_volume(sb_volume)
            await player._backend.play(sound_track)
            await player._backend.wait_for_track_end()
        except Exception as e:
            logger.error("Error playing soundboard sound: {}", e)
            await ctx.send(f"❌ Failed to play soundboard sound: `{sound_name}`", ephemeral=True)
        finally:
            await player._backend.set_volume(player.volume)
            if was_playing and currently_playing:
                player.current = currently_playing
                await player._backend.play(currently_playing, seek=position / 1000.0)
                if player._active_preset_definition:
                    await player._backend.set_filters(player._active_preset_definition)
                if player.is_paused:
                    await player.pause()

                # Re-register wait task
                player._play_task = asyncio.create_task(player._wait_and_play_next())
            else:
                player.current = None
                await player._backend.stop()
                player._start_inactive_timer()

    @commands.hybrid_group(
        name="soundboard", aliases=["sb"], description="Play short sound effects"
    )
    async def soundboard(self, ctx: commands.Context) -> None:
        """Soundboard commands. Use subcommands: play, list, add, remove."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @soundboard.command(name="play", description="Play a soundboard sound in the voice channel")
    @app_commands.describe(name="Name of the sound to play")
    @app_commands.autocomplete(name=soundboard_autocomplete)
    @cooldown(1, 2.0)
    async def soundboard_play(self, ctx: commands.Context, *, name: str) -> None:
        """Play a built-in or custom soundboard sound."""
        name_cleaned = name.lower().strip()
        sound_url = BUILTIN_SOUNDS.get(name_cleaned)

        if not sound_url:
            from core.repositories import SoundboardRepo

            custom_sound = await SoundboardRepo.get(ctx.guild.id, name_cleaned)
            if custom_sound:
                sound_url = custom_sound.url

        if not sound_url:
            await ctx.send(
                f"❌ Sound `{name}` not found. Use `/soundboard list` to see available sounds.",
                ephemeral=True,
            )
            return

        await self.play_sound(ctx, sound_url, name_cleaned)

    @soundboard.command(name="add", description="Add a custom soundboard sound")
    @app_commands.describe(name="Name of the sound", url="Direct URL to the audio file (mp3/wav)")
    @is_dj()
    @cooldown(1, 3.0)
    async def soundboard_add(self, ctx: commands.Context, name: str, url: str) -> None:
        """Add a custom soundboard sound to this guild (DJ/Admin only)."""
        name_cleaned = name.lower().strip()
        if not name_cleaned.isalnum() or len(name_cleaned) > 30:
            await ctx.send(
                "❌ Sound name must be alphanumeric and under 30 characters.", ephemeral=True
            )
            return

        if name_cleaned in BUILTIN_SOUNDS:
            await ctx.send("❌ Sound name conflicts with a built-in sound.", ephemeral=True)
            return

        if not url.startswith(("http://", "https://")):
            await ctx.send("❌ Invalid URL. Must start with http:// or https://", ephemeral=True)
            return

        from core.extractor import _has_disallowed_scheme, _is_ssrf_risk

        if _has_disallowed_scheme(url) or _is_ssrf_risk(url):
            await ctx.send(
                "❌ Security Check: Loopback or private network URLs are blocked.", ephemeral=True
            )
            return

        from core.repositories import SoundboardRepo

        await SoundboardRepo.add(ctx.guild.id, name_cleaned, url, ctx.author.id)
        await ctx.send(f"✅ Added custom soundboard sound: `{name_cleaned}`")

    @soundboard.command(name="remove", description="Remove a custom soundboard sound")
    @app_commands.describe(name="Name of the custom sound to remove")
    @app_commands.autocomplete(name=soundboard_autocomplete)
    @is_dj()
    @cooldown(1, 3.0)
    async def soundboard_remove(self, ctx: commands.Context, name: str) -> None:
        """Remove a custom soundboard sound from this guild (DJ/Admin only)."""
        name_cleaned = name.lower().strip()

        from core.repositories import SoundboardRepo

        deleted = await SoundboardRepo.delete(ctx.guild.id, name_cleaned)
        if deleted:
            await ctx.send(f"✅ Removed custom soundboard sound: `{name_cleaned}`")
        else:
            await ctx.send(f"❌ Custom sound `{name_cleaned}` not found.", ephemeral=True)

    @soundboard.command(name="list", description="List all available soundboard sounds")
    @cooldown(1, 3.0)
    async def soundboard_list(self, ctx: commands.Context, page: int = 1) -> None:
        """List all built-in and guild-custom soundboard sounds with pagination."""
        from core.repositories import SoundboardRepo
        from core.ui.soundboard_paginator import SoundboardPaginator

        custom_sounds = await SoundboardRepo.get_all(ctx.guild.id)
        builtins = list(BUILTIN_SOUNDS.keys())
        customs = [s.name for s in custom_sounds]

        paginator = SoundboardPaginator(builtins, customs, page=page)
        embed = paginator.build_embed()
        await ctx.send(embed=embed, view=paginator)


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Soundboard(bot))
