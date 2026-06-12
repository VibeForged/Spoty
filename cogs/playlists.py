"""Playlists cog persistent per-user playlist management."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from core.checks import cooldown
from core.errors import InvalidPlaylistPositionError, PlaylistNotFoundError, TrackNotFoundError
from core.playlists.service import MAX_IMPORT_ITEMS, PlaylistService
from core.ui.playlist_paginator import PlaylistPaginator, build_playlist_embed

if TYPE_CHECKING:
    from bot import MusicBot


async def playlist_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not interaction.guild_id:
        return []
    playlists = await PlaylistService.list_user_playlists(interaction.guild_id, interaction.user.id)
    choices = []
    current_lower = current.lower()
    for playlist in playlists:
        if current_lower in playlist.name.lower():
            choices.append(app_commands.Choice(name=playlist.name, value=playlist.name))
        if len(choices) >= 25:
            break
    return choices


class Playlists(commands.Cog):
    """Playlist management commands."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        settings = await self.bot.get_guild_settings(ctx.guild.id)
        if settings and settings.music_channel_id and ctx.channel.id != settings.music_channel_id:
            from core.errors import WrongChannelError

            raise WrongChannelError(settings.music_channel_id)
        return True

    @commands.hybrid_group(name="playlist", aliases=["pl"], description="Manage playlists")
    async def playlist(self, ctx: commands.Context) -> None:
        """Playlist management. Use subcommands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @playlist.command(name="create", description="Create a new playlist")
    @app_commands.describe(name="Name for the new playlist")
    @cooldown(1, 5.0)
    async def playlist_create(self, ctx: commands.Context, *, name: str) -> None:
        """Create a new empty playlist."""
        playlist = await PlaylistService.create_playlist(ctx.guild.id, ctx.author.id, name)
        await ctx.send(
            embed=discord.Embed(
                title="Playlist Created",
                description=f"Created playlist **{playlist.name}**",
                color=discord.Color.green(),
            )
        )

    @playlist.command(name="delete", description="Delete a playlist")
    @app_commands.describe(name="Name of the playlist to delete")
    @app_commands.autocomplete(name=playlist_autocomplete)
    @cooldown(1, 5.0)
    async def playlist_delete(self, ctx: commands.Context, *, name: str) -> None:
        """Delete a playlist you own."""
        from core.ui.confirm import confirm_action

        if not await confirm_action(ctx, f"Delete playlist **{name}**? This cannot be undone."):
            await ctx.send("Cancelled.", ephemeral=True)
            return
        await PlaylistService.delete_playlist(ctx.guild.id, ctx.author.id, name)
        await ctx.send(f"Deleted playlist **{name}**")

    @playlist.command(name="add", description="Add a track to a playlist")
    @app_commands.describe(name="Playlist name", query="Song name or URL")
    @app_commands.autocomplete(name=playlist_autocomplete)
    @cooldown(1, 3.0)
    async def playlist_add(self, ctx: commands.Context, name: str, *, query: str) -> None:
        """Add a track to one of your playlists."""
        from core.extractor import search_track

        await ctx.defer()
        track = await search_track(query)
        if not track:
            raise TrackNotFoundError(query)

        position = await PlaylistService.add_item(
            ctx.guild.id,
            ctx.author.id,
            name,
            PlaylistService.item_from_track(track),
        )
        await ctx.send(f"Added **{track.short_title}** to **{name}** (#{position})")

    @playlist.command(name="remove", description="Remove a track from a playlist")
    @app_commands.describe(name="Playlist name", position="Track position (1-indexed)")
    @app_commands.autocomplete(name=playlist_autocomplete)
    @cooldown(1, 3.0)
    async def playlist_remove(self, ctx: commands.Context, name: str, position: int) -> None:
        """Remove a track from your playlist at a given position."""
        await PlaylistService.remove_item(ctx.guild.id, ctx.author.id, name, position)
        await ctx.send(f"Removed track #{position} from **{name}**")

    @playlist.command(name="list", description="List your playlists")
    @cooldown(1, 3.0)
    async def playlist_list(self, ctx: commands.Context) -> None:
        """List all your playlists in this server."""
        playlists = await PlaylistService.list_user_playlists(ctx.guild.id, ctx.author.id)
        if not playlists:
            await ctx.send("You don't have any playlists. Create one with `/playlist create`!")
            return

        embed = discord.Embed(title="Your Playlists", color=discord.Color.blue())
        embed.description = "\n".join(
            f"**{i+1}. {playlist.name}** - {playlist.track_count} tracks"
            for i, playlist in enumerate(playlists)
        )
        await ctx.send(embed=embed)

    @playlist.command(name="view", description="View contents of a playlist")
    @app_commands.describe(name="Playlist name")
    @app_commands.autocomplete(name=playlist_autocomplete)
    @cooldown(1, 3.0)
    async def playlist_view(
        self, ctx: commands.Context, name: str, page: int = 1
    ) -> None:
        """View tracks in a playlist."""
        view = PlaylistPaginator(ctx.guild.id, ctx.author.id, name, page=page)
        detail = await PlaylistService.get_playlist_detail(
            ctx.guild.id, ctx.author.id, name, page=page
        )
        if not detail.items:
            await ctx.send(f"Playlist **{detail.playlist.name}** is empty.")
            return

        view.page = detail.page
        view.total_pages = detail.total_pages
        view._sync_controls()
        await ctx.send(embed=build_playlist_embed(detail), view=view)

    @playlist.command(name="play", description="Queue a playlist")
    @app_commands.describe(name="Playlist name", shuffle="Shuffle the playlist before queueing")
    @app_commands.autocomplete(name=playlist_autocomplete)
    @cooldown(1, 5.0)
    async def playlist_play(self, ctx: commands.Context, name: str, shuffle: bool = False) -> None:
        """Load all tracks from a playlist into the queue."""
        await ctx.defer()
        tracks = await PlaylistService.tracks_for_play(ctx.guild.id, ctx.author.id, name)
        if not tracks:
            await ctx.send(f"Playlist **{name}** is empty.", ephemeral=True)
            return

        music_cog = self.bot.get_cog("Music")
        if music_cog is None:
            await ctx.send("Music cog not loaded.", ephemeral=True)
            return

        player = await music_cog._get_or_create_player(ctx)
        if len(tracks) > player.queue.remaining_capacity:
            await ctx.send(
                (
                    f"Playlist has **{len(tracks)}** tracks, but the queue only has "
                    f"**{player.queue.remaining_capacity}** open slots."
                ),
                ephemeral=True,
            )
            return

        for track in tracks:
            track.requester_id = ctx.author.id
            track.requester_name = ctx.author.display_name

        if shuffle:
            random.shuffle(tracks)

        for track in tracks:
            player.queue.add(track)

        if not player.is_playing and not player.is_paused:
            await player.play_next()

        await ctx.send(
            embed=discord.Embed(
                title="Playlist Loaded",
                description=f"Added **{len(tracks)}** tracks from **{name}**",
                color=discord.Color.green(),
            )
        )

    @playlist.command(name="share", description="Share a playlist")
    @app_commands.describe(name="Playlist name")
    @app_commands.autocomplete(name=playlist_autocomplete)
    @cooldown(1, 5.0)
    async def playlist_share(self, ctx: commands.Context, *, name: str) -> None:
        """Generate a shareable code for your playlist."""
        code = await PlaylistService.generate_share_code(ctx.guild.id, ctx.author.id, name)
        await ctx.send(
            embed=discord.Embed(
                title="Playlist Share Code",
                description=(
                    f"Share code for **{name}**: `{code}`\n"
                    f"Others can import with `/playlist import {code}`"
                ),
                color=discord.Color.green(),
            )
        )

    @playlist.command(name="rename", description="Rename a playlist")
    @app_commands.describe(old_name="Current name", new_name="New name")
    @app_commands.autocomplete(old_name=playlist_autocomplete)
    @cooldown(1, 5.0)
    async def playlist_rename(self, ctx: commands.Context, old_name: str, new_name: str) -> None:
        """Rename one of your playlists."""
        final_name = await PlaylistService.rename_playlist(
            ctx.guild.id, ctx.author.id, old_name, new_name
        )
        await ctx.send(f"Renamed **{old_name}** to **{final_name}**")

    @playlist.command(name="info", description="Get playlist details")
    @app_commands.describe(name="Playlist name")
    @app_commands.autocomplete(name=playlist_autocomplete)
    @cooldown(1, 3.0)
    async def playlist_info(self, ctx: commands.Context, *, name: str) -> None:
        """Show metadata for a playlist."""
        info = await PlaylistService.get_playlist_info(ctx.guild.id, ctx.author.id, name)
        playlist = info.playlist
        hours, remainder = divmod(info.total_duration, 3600)
        minutes, _ = divmod(remainder, 60)

        owner = ctx.guild.get_member(playlist.owner_id)
        owner_name = owner.display_name if owner else "Unknown"

        embed = discord.Embed(title=f"Playlist: {playlist.name}", color=discord.Color.blue())
        embed.add_field(name="Creator", value=owner_name, inline=True)
        embed.add_field(name="Tracks", value=str(playlist.track_count), inline=True)
        embed.add_field(
            name="Total Duration",
            value=f"{hours}h {minutes}m" if hours else f"{minutes}m",
            inline=True,
        )
        embed.add_field(name="Visibility", value=playlist.visibility, inline=True)
        embed.add_field(
            name="Created",
            value=discord.utils.format_dt(playlist.created_at, "R"),
            inline=True,
        )
        if playlist.share_code:
            embed.add_field(name="Share Code", value=f"`{playlist.share_code}`", inline=True)
        await ctx.send(embed=embed)

    @playlist.command(
        name="import", description="Import a playlist from YouTube/Spotify URL or share code"
    )
    @app_commands.describe(source="YouTube/Spotify URL or share code")
    @cooldown(1, 15.0)
    async def playlist_import(self, ctx: commands.Context, *, source: str) -> None:
        """Import a playlist from a URL or share code."""
        await ctx.defer()

        if len(source) == 8 and source.isalnum():
            try:
                playlist = await PlaylistService.import_share_code(
                    ctx.guild.id, ctx.author.id, source
                )
            except PlaylistNotFoundError:
                playlist = None
            if playlist is not None:
                await ctx.send(
                    embed=discord.Embed(
                        title="Playlist Imported",
                        description=(
                            f"Imported **{playlist.track_count}** tracks as "
                            f"**{playlist.name}**"
                        ),
                        color=discord.Color.green(),
                    )
                )
                return

        if "spotify.com" in source:
            from core.spotify import SpotifyScraper
            playlist_name, queries = await SpotifyScraper.extract_queries(source)
            if not queries:
                await ctx.send("Failed to search Spotify or no tracks found.", ephemeral=True)
                return

            name = playlist_name or "Imported Spotify Playlist"
            track_dicts = []
            for q in queries[:MAX_IMPORT_ITEMS]:
                track_dicts.append({
                    "title": q,
                    "url": source,
                    "duration": None,
                    "source": "spotify",
                    "external_id": q
                })

            playlist = await PlaylistService.import_items(
                ctx.guild.id, ctx.author.id, name, track_dicts
            )
            await ctx.send(
                embed=discord.Embed(
                    title="Spotify Playlist Imported",
                    description=(
                        f"Imported **{playlist.track_count}** tracks as **{playlist.name}**"
                    ),
                    color=discord.Color.green(),
                )
            )
            return

        from core.extractor import extract_playlist

        playlist_name, tracks = await extract_playlist(source)
        if not tracks:
            await ctx.send("No tracks found in that playlist.", ephemeral=True)
            return

        logger.info("Extracted {} tracks from playlist import", len(tracks))
        playlist = await PlaylistService.import_items(
            ctx.guild.id,
            ctx.author.id,
            playlist_name,
            [PlaylistService.item_from_track(track) for track in tracks[:MAX_IMPORT_ITEMS]],
        )
        await ctx.send(
            embed=discord.Embed(
                title="Playlist Imported",
                description=f"Imported **{playlist.track_count}** tracks as **{playlist.name}**",
                color=discord.Color.green(),
            )
        )

    @playlist.command(name="like", description="Like a track in a playlist")
    @app_commands.describe(name="Playlist name", position="Track position (1-indexed)")
    @app_commands.autocomplete(name=playlist_autocomplete)
    @cooldown(1, 3.0)
    async def playlist_like(self, ctx: commands.Context, name: str, position: int) -> None:
        """Upvote a track in a playlist."""
        await self._vote(ctx, name, position, 1)

    @playlist.command(name="dislike", description="Dislike a track in a playlist")
    @app_commands.describe(name="Playlist name", position="Track position (1-indexed)")
    @app_commands.autocomplete(name=playlist_autocomplete)
    @cooldown(1, 3.0)
    async def playlist_dislike(self, ctx: commands.Context, name: str, position: int) -> None:
        """Downvote a track in a playlist."""
        await self._vote(ctx, name, position, -1)

    async def _vote(
        self, ctx: commands.Context, name: str, position: int, vote: int
    ) -> None:
        try:
            item, (likes, dislikes) = await PlaylistService.vote_item(
                ctx.guild.id,
                ctx.author.id,
                name,
                position,
                ctx.author.id,
                vote,
            )
        except InvalidPlaylistPositionError:
            await ctx.send(f"No track at position {position}.", ephemeral=True)
            return

        await ctx.send(
            embed=discord.Embed(
                title="Track Liked" if vote == 1 else "Track Disliked",
                description=f"**{item.title}**\nLikes: {likes} | Dislikes: {dislikes}",
                color=discord.Color.green() if vote == 1 else discord.Color.red(),
            )
        )

    @playlist.command(name="copy", description="Copy a shared playlist")
    @app_commands.describe(source="Share code, URL, or your playlist name", new_name="New playlist name")
    @app_commands.autocomplete(source=playlist_autocomplete)
    @cooldown(1, 5.0)
    async def playlist_copy(self, ctx: commands.Context, source: str, new_name: str) -> None:
        """Copy a playlist (own or shared) to a new name."""
        playlist = await PlaylistService.copy_playlist(
            ctx.guild.id,
            ctx.author.id,
            source,
            new_name,
        )
        await ctx.send(
            embed=discord.Embed(
                title="Playlist Copied",
                description=f"Copied **{playlist.track_count}** tracks to **{playlist.name}**",
                color=discord.Color.green(),
            )
        )

    @playlist.command(name="shuffle", description="Shuffle your playlist")
    @app_commands.describe(name="Playlist name")
    @app_commands.autocomplete(name=playlist_autocomplete)
    @cooldown(1, 5.0)
    async def playlist_shuffle(self, ctx: commands.Context, *, name: str) -> None:
        """Permanently shuffle the stored order of a playlist."""
        count = await PlaylistService.shuffle_items(ctx.guild.id, ctx.author.id, name)
        if count == 0:
            await ctx.send(f"Playlist **{name}** is empty.", ephemeral=True)
            return
        await ctx.send(
            embed=discord.Embed(
                title="Playlist Shuffled",
                description=f"Shuffled **{count}** tracks in **{name}**",
                color=discord.Color.green(),
            )
        )


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Playlists(bot))
