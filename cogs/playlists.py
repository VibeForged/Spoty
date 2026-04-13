"""Playlists cog — persistent per-user playlist management.

Phase 1 stub. Full implementation in Phase 3.
"""

from __future__ import annotations

import random
import string
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger

from core.checks import cooldown
from core.errors import (
    NotPlaylistOwner,
    PlaylistAlreadyExists,
    PlaylistNotFound,
)

if TYPE_CHECKING:
    from bot import MusicBot


class Playlists(commands.Cog):
    """Playlist management commands."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot

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
        from core.repositories import PlaylistRepo

        existing = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, name)
        if existing:
            raise PlaylistAlreadyExists(name)

        await PlaylistRepo.create(ctx.guild.id, ctx.author.id, name)
        await ctx.send(
            embed=discord.Embed(
                title="Playlist Created",
                description=f"Created playlist **{name}**",
                color=discord.Color.green(),
            )
        )

    @playlist.command(name="delete", description="Delete a playlist")
    @app_commands.describe(name="Name of the playlist to delete")
    @cooldown(1, 5.0)
    async def playlist_delete(self, ctx: commands.Context, *, name: str) -> None:
        """Delete a playlist you own."""
        from core.repositories import PlaylistRepo

        playlist = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, name)
        if not playlist:
            raise PlaylistNotFound(name)

        if playlist.owner_id != ctx.author.id:
            # Check if admin
            if not ctx.author.guild_permissions.manage_guild:
                raise NotPlaylistOwner()

        await PlaylistRepo.delete_playlist(playlist.id)
        await ctx.send(f"Deleted playlist **{name}**")

    @playlist.command(name="add", description="Add a track to a playlist")
    @app_commands.describe(name="Playlist name", query="Song name or URL")
    @cooldown(1, 3.0)
    async def playlist_add(self, ctx: commands.Context, name: str, *, query: str) -> None:
        """Add a track to one of your playlists."""
        from core.extractor import search_track
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        playlist = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, name)
        if not playlist:
            raise PlaylistNotFound(name)

        await ctx.defer()
        track = await search_track(query)
        if not track:
            from core.errors import TrackNotFound
            raise TrackNotFound(query)

        await PlaylistTrackRepo.add_track(
            playlist.id, track.title, track.url, track.duration, ctx.author.id
        )
        count = await PlaylistTrackRepo.count(playlist.id)
        await ctx.send(f"Added **{track.short_title}** to **{name}** (#{count})")

    @playlist.command(name="remove", description="Remove a track from a playlist")
    @app_commands.describe(name="Playlist name", position="Track position (1-indexed)")
    @cooldown(1, 3.0)
    async def playlist_remove(self, ctx: commands.Context, name: str, position: int) -> None:
        """Remove a track from your playlist at a given position."""
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        playlist = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, name)
        if not playlist:
            raise PlaylistNotFound(name)

        if await PlaylistTrackRepo.remove_track(playlist.id, position):
            await ctx.send(f"Removed track #{position} from **{name}**")
        else:
            await ctx.send(f"No track at position {position}.", ephemeral=True)

    @playlist.command(name="list", description="List your playlists")
    @cooldown(1, 3.0)
    async def playlist_list(self, ctx: commands.Context) -> None:
        """List all your playlists in this server."""
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        playlists = await PlaylistRepo.list_for_user(ctx.guild.id, ctx.author.id)
        if not playlists:
            await ctx.send("You don't have any playlists. Create one with `/playlist create`!")
            return

        embed = discord.Embed(title="Your Playlists", color=discord.Color.blue())
        lines = []
        for pl in playlists:
            count = await PlaylistTrackRepo.count(pl.id)
            lines.append(f"**{pl.name}** — {count} tracks")
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @playlist.command(name="view", description="View tracks in a playlist")
    @app_commands.describe(name="Playlist name")
    @cooldown(1, 3.0)
    async def playlist_view(self, ctx: commands.Context, *, name: str) -> None:
        """View all tracks in a playlist."""
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        playlist = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, name)
        if not playlist:
            raise PlaylistNotFound(name)

        tracks = await PlaylistTrackRepo.get_tracks(playlist.id)
        if not tracks:
            await ctx.send(f"Playlist **{name}** is empty.")
            return

        embed = discord.Embed(title=f"Playlist: {name}", color=discord.Color.blue())
        lines = []
        for t in tracks[:25]:  # Show first 25
            dur = f" [{t.duration // 60}:{t.duration % 60:02d}]" if t.duration else ""
            lines.append(f"`{t.position}.` {t.title[:60]}{dur}")
        embed.description = "\n".join(lines)

        if len(tracks) > 25:
            embed.set_footer(text=f"Showing 25/{len(tracks)} tracks")

        await ctx.send(embed=embed)

    @playlist.command(name="play", description="Load a playlist into the queue")
    @app_commands.describe(name="Playlist name", shuffle="Shuffle before loading")
    @cooldown(1, 5.0)
    async def playlist_play(self, ctx: commands.Context, name: str, shuffle: bool = False) -> None:
        """Load all tracks from a playlist into the queue."""
        from core.repositories import PlaylistRepo, PlaylistTrackRepo
        from core.track import Track

        playlist = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, name)
        if not playlist:
            raise PlaylistNotFound(name)

        tracks = await PlaylistTrackRepo.get_tracks(playlist.id)
        if not tracks:
            await ctx.send(f"Playlist **{name}** is empty.", ephemeral=True)
            return

        # Get or create player
        music_cog = self.bot.get_cog("Music")
        if music_cog is None:
            await ctx.send("Music cog not loaded.", ephemeral=True)
            return

        player = await music_cog._get_or_create_player(ctx)

        # Convert to Track objects
        track_list = [
            Track(
                title=t.title,
                url=t.url,
                duration=t.duration,
                requester_id=ctx.author.id,
                requester_name=ctx.author.display_name,
            )
            for t in tracks
        ]

        if shuffle:
            random.shuffle(track_list)

        for track in track_list:
            player.queue.add(track)

        # Start playing if not already
        if not player.is_playing and not player.is_paused:
            await player.play_next()

        await ctx.send(
            embed=discord.Embed(
                title="Playlist Loaded",
                description=f"Added **{len(track_list)}** tracks from **{name}**",
                color=discord.Color.green(),
            )
        )

    @playlist.command(name="share", description="Generate a share code for a playlist")
    @app_commands.describe(name="Playlist name")
    @cooldown(1, 10.0)
    async def playlist_share(self, ctx: commands.Context, *, name: str) -> None:
        """Generate a shareable code for your playlist."""
        from core.repositories import PlaylistRepo

        playlist = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, name)
        if not playlist:
            raise PlaylistNotFound(name)

        if playlist.share_code:
            code = playlist.share_code
        else:
            code = "".join(random.choices(string.ascii_letters + string.digits, k=8))
            await PlaylistRepo.update_share_code(playlist.id, code)

        await ctx.send(
            embed=discord.Embed(
                title="Playlist Share Code",
                description=f"Share code for **{name}**: `{code}`\n"
                f"Others can import with `/playlist import {code}`",
                color=discord.Color.green(),
            )
        )

    @playlist.command(name="rename", description="Rename a playlist")
    @app_commands.describe(old_name="Current name", new_name="New name")
    @cooldown(1, 5.0)
    async def playlist_rename(self, ctx: commands.Context, old_name: str, new_name: str) -> None:
        """Rename one of your playlists."""
        from core.repositories import PlaylistRepo

        playlist = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, old_name)
        if not playlist:
            raise PlaylistNotFound(old_name)

        await PlaylistRepo.rename(playlist.id, new_name)
        await ctx.send(f"Renamed **{old_name}** to **{new_name}**")

    @playlist.command(name="info", description="Show playlist metadata")
    @app_commands.describe(name="Playlist name")
    @cooldown(1, 3.0)
    async def playlist_info(self, ctx: commands.Context, *, name: str) -> None:
        """Show metadata for a playlist."""
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        playlist = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, name)
        if not playlist:
            raise PlaylistNotFound(name)

        tracks = await PlaylistTrackRepo.get_tracks(playlist.id)
        total_duration = sum(t.duration or 0 for t in tracks)
        hours, remainder = divmod(total_duration, 3600)
        minutes, _ = divmod(remainder, 60)

        owner = ctx.guild.get_member(playlist.owner_id)
        owner_name = owner.display_name if owner else "Unknown"

        embed = discord.Embed(title=f"Playlist: {name}", color=discord.Color.blue())
        embed.add_field(name="Creator", value=owner_name, inline=True)
        embed.add_field(name="Tracks", value=str(len(tracks)), inline=True)
        embed.add_field(
            name="Total Duration",
            value=f"{hours}h {minutes}m" if hours else f"{minutes}m",
            inline=True,
        )
        embed.add_field(
            name="Created",
            value=discord.utils.format_dt(playlist.created_at, "R"),
            inline=True,
        )
        if playlist.share_code:
            embed.add_field(name="Share Code", value=f"`{playlist.share_code}`", inline=True)

        await ctx.send(embed=embed)

    @playlist.command(name="import", description="Import a playlist from YouTube/Spotify URL or share code")
    @app_commands.describe(source="YouTube/Spotify URL or share code")
    @cooldown(1, 15.0)
    async def playlist_import(self, ctx: commands.Context, *, source: str) -> None:
        """Import a playlist from a URL or share code. Full implementation in Phase 3."""
        await ctx.defer()

        # Check if it's a share code (8 chars alphanumeric)
        if len(source) == 8 and source.isalnum():
            from core.repositories import PlaylistRepo

            shared = await PlaylistRepo.get_by_share_code(source)
            if shared:
                await ctx.send(f"Found shared playlist **{shared.name}**. Import coming in Phase 3!")
                return

        # Check for Spotify URL
        if "spotify.com" in source:
            if not self.bot.config.spotify_configured:
                await ctx.send(
                    "Spotify support is not configured. "
                    "Set `SPOTIPY_CLIENT_ID` and `SPOTIPY_CLIENT_SECRET` in `.env`.",
                    ephemeral=True,
                )
                return
            await ctx.send("Spotify import coming in Phase 3!")
            return

        # YouTube playlist import
        from core.extractor import extract_playlist

        tracks = await extract_playlist(source)
        if not tracks:
            await ctx.send("No tracks found in that playlist.", ephemeral=True)
            return

        await ctx.send(
            embed=discord.Embed(
                title="Playlist Import",
                description=f"Found **{len(tracks)}** tracks. Full import coming in Phase 3!",
                color=discord.Color.blue(),
            )
        )

    @playlist.command(name="like", description="Upvote a track in a playlist")
    @app_commands.describe(name="Playlist name", position="Track position")
    @cooldown(1, 3.0)
    async def playlist_like(self, ctx: commands.Context, name: str, position: int) -> None:
        """Upvote a track. Full implementation in Phase 3."""
        await ctx.send("Voting coming in Phase 3!", ephemeral=True)

    @playlist.command(name="dislike", description="Downvote a track in a playlist")
    @app_commands.describe(name="Playlist name", position="Track position")
    @cooldown(1, 3.0)
    async def playlist_dislike(self, ctx: commands.Context, name: str, position: int) -> None:
        """Downvote a track. Full implementation in Phase 3."""
        await ctx.send("Voting coming in Phase 3!", ephemeral=True)

    @playlist.command(name="copy", description="Copy a playlist")
    @app_commands.describe(source="Source playlist name", new_name="New playlist name")
    @cooldown(1, 5.0)
    async def playlist_copy(self, ctx: commands.Context, source: str, new_name: str) -> None:
        """Copy a playlist. Full implementation in Phase 3."""
        await ctx.send("Playlist copy coming in Phase 3!", ephemeral=True)

    @playlist.command(name="shuffle", description="Permanently shuffle playlist track order")
    @app_commands.describe(name="Playlist name")
    @cooldown(1, 5.0)
    async def playlist_shuffle(self, ctx: commands.Context, *, name: str) -> None:
        """Permanently shuffle the stored order of a playlist."""
        await ctx.send("Playlist shuffle coming in Phase 3!", ephemeral=True)


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Playlists(bot))
