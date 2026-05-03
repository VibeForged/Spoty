"""Playlists cog persistent per-user playlist management."""

from __future__ import annotations

import asyncio
import random
import re
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
        await ctx.defer()
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

    async def _import_spotify(self, url: str) -> tuple[str, list[dict]]:
        """Import tracks from a Spotify playlist or album URL.

        Returns (name, tracks) where tracks is a list of dicts with
        title, url, and duration keys.
        """
        import spotipy

        sp = spotipy.Spotify(
            auth_manager=spotipy.SpotifyClientCredentials(
                client_id=self.bot.config.spotipy_client_id,
                client_secret=self.bot.config.spotipy_client_secret,
            )
        )

        loop = asyncio.get_running_loop()

        # Parse playlist or album ID from URL
        playlist_match = re.search(r"playlist/([a-zA-Z0-9]+)", url)
        album_match = re.search(r"album/([a-zA-Z0-9]+)", url)

        tracks: list[dict] = []

        if playlist_match:
            sp_id = playlist_match.group(1)
            sp_playlist = await loop.run_in_executor(None, sp.playlist, sp_id)
            name = sp_playlist["name"]

            results = sp_playlist["tracks"]
            while True:
                for item in results["items"]:
                    t = item.get("track")
                    if not t:
                        continue
                    artists = ", ".join(a["name"] for a in t["artists"])
                    title = f"{artists} - {t['name']}"
                    tracks.append(
                        {
                            "title": title,
                            "url": f"ytsearch:{artists} - {t['name']}",
                            "duration": t["duration_ms"] // 1000,
                        }
                    )
                if results["next"]:
                    results = await loop.run_in_executor(None, sp.next, results)
                else:
                    break

        elif album_match:
            sp_id = album_match.group(1)
            sp_album = await loop.run_in_executor(None, sp.album, sp_id)
            name = sp_album["name"]

            results = sp_album["tracks"]
            while True:
                for t in results["items"]:
                    artists = ", ".join(a["name"] for a in t["artists"])
                    title = f"{artists} - {t['name']}"
                    tracks.append(
                        {
                            "title": title,
                            "url": f"ytsearch:{artists} - {t['name']}",
                            "duration": t["duration_ms"] // 1000,
                        }
                    )
                if results["next"]:
                    results = await loop.run_in_executor(None, sp.next, results)
                else:
                    break
        else:
            raise ValueError("Could not parse Spotify playlist or album URL.")

        return name, tracks

    @playlist.command(
        name="import", description="Import a playlist from YouTube/Spotify URL or share code"
    )
    @app_commands.describe(source="YouTube/Spotify URL or share code")
    @cooldown(1, 15.0)
    async def playlist_import(self, ctx: commands.Context, *, source: str) -> None:
        """Import a playlist from a URL or share code."""
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        await ctx.defer()

        # Check if it's a share code (8 chars alphanumeric)
        if len(source) == 8 and source.isalnum():
            shared = await PlaylistRepo.get_by_share_code(source)
            if shared:
                new_name = f"{shared.name} (imported)"
                new_playlist = await PlaylistRepo.create(
                    ctx.guild.id, ctx.author.id, new_name
                )
                shared_tracks = await PlaylistTrackRepo.get_tracks(shared.id)
                track_dicts = [
                    {"title": t.title, "url": t.url, "duration": t.duration}
                    for t in shared_tracks
                ]
                await PlaylistTrackRepo.bulk_add_tracks(
                    new_playlist.id, track_dicts, ctx.author.id
                )
                await ctx.send(
                    embed=discord.Embed(
                        title="Playlist Imported",
                        description=(
                            f"Imported **{len(track_dicts)}** tracks from "
                            f"**{shared.name}** as **{new_name}**"
                        ),
                        color=discord.Color.green(),
                    )
                )
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

            name, track_dicts = await self._import_spotify(source)
            if not track_dicts:
                await ctx.send("No tracks found in that Spotify URL.", ephemeral=True)
                return

            new_playlist = await PlaylistRepo.create(
                ctx.guild.id, ctx.author.id, name
            )
            await PlaylistTrackRepo.bulk_add_tracks(
                new_playlist.id, track_dicts, ctx.author.id
            )
            await ctx.send(
                embed=discord.Embed(
                    title="Spotify Playlist Imported",
                    description=(
                        f"Imported **{len(track_dicts)}** tracks from **{name}**"
                    ),
                    color=discord.Color.green(),
                )
            )
            return

        # YouTube playlist import
        from core.extractor import extract_playlist

        playlist_name, tracks = await extract_playlist(source)
        if not tracks:
            await ctx.send("No tracks found in that playlist.", ephemeral=True)
            return

        logger.info("Extracted {} deduplicated tracks from YouTube playlist", len(tracks))

        new_playlist = await PlaylistRepo.create(
            ctx.guild.id, ctx.author.id, playlist_name
        )
        track_dicts = [
            {"title": t.title, "url": t.url, "duration": t.duration} for t in tracks
        ]
        
        logger.info("Adding {} track dicts to playlist {}", len(track_dicts), new_playlist.id)
        added_tracks = await PlaylistTrackRepo.bulk_add_tracks(
            new_playlist.id, track_dicts, ctx.author.id
        )
        logger.info("Successfully added {} tracks to playlist {}", len(added_tracks), new_playlist.id)
        
        await ctx.send(
            embed=discord.Embed(
                title="Playlist Imported",
                description=(
                    f"Imported **{len(added_tracks)}** tracks as **{playlist_name}**"
                ),
                color=discord.Color.green(),
            )
        )

    @playlist.command(name="like", description="Upvote a track in a playlist")
    @app_commands.describe(name="Playlist name", position="Track position")
    @cooldown(1, 3.0)
    async def playlist_like(self, ctx: commands.Context, name: str, position: int) -> None:
        """Upvote a track in a playlist."""
        from core.repositories import PlaylistRepo, PlaylistTrackRepo, PlaylistVoteRepo

        playlist = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, name)
        if not playlist:
            raise PlaylistNotFound(name)

        track = await PlaylistTrackRepo.get_track_at_position(playlist.id, position)
        if not track:
            await ctx.send(f"No track at position {position}.", ephemeral=True)
            return

        await PlaylistVoteRepo.upsert_vote(track.id, ctx.author.id, 1)
        likes, dislikes = await PlaylistVoteRepo.get_votes(track.id)

        await ctx.send(
            embed=discord.Embed(
                title="Track Liked",
                description=(
                    f"**{track.title}**\n"
                    f"Likes: {likes} | Dislikes: {dislikes}"
                ),
                color=discord.Color.green(),
            )
        )

    @playlist.command(name="dislike", description="Downvote a track in a playlist")
    @app_commands.describe(name="Playlist name", position="Track position")
    @cooldown(1, 3.0)
    async def playlist_dislike(self, ctx: commands.Context, name: str, position: int) -> None:
        """Downvote a track in a playlist."""
        from core.repositories import PlaylistRepo, PlaylistTrackRepo, PlaylistVoteRepo

        playlist = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, name)
        if not playlist:
            raise PlaylistNotFound(name)

        track = await PlaylistTrackRepo.get_track_at_position(playlist.id, position)
        if not track:
            await ctx.send(f"No track at position {position}.", ephemeral=True)
            return

        await PlaylistVoteRepo.upsert_vote(track.id, ctx.author.id, -1)
        likes, dislikes = await PlaylistVoteRepo.get_votes(track.id)

        await ctx.send(
            embed=discord.Embed(
                title="Track Disliked",
                description=(
                    f"**{track.title}**\n"
                    f"Likes: {likes} | Dislikes: {dislikes}"
                ),
                color=discord.Color.red(),
            )
        )

    @playlist.command(name="copy", description="Copy a playlist")
    @app_commands.describe(source="Source playlist name or share code", new_name="New playlist name")
    @cooldown(1, 5.0)
    async def playlist_copy(self, ctx: commands.Context, source: str, new_name: str) -> None:
        """Copy a playlist (own or shared) to a new name."""
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        # Try own playlist first
        src_playlist = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, source)
        if not src_playlist:
            # Try share code
            src_playlist = await PlaylistRepo.get_by_share_code(source)
        if not src_playlist:
            raise PlaylistNotFound(source)

        # Check new_name doesn't exist
        existing = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, new_name)
        if existing:
            raise PlaylistAlreadyExists(new_name)

        new_playlist = await PlaylistRepo.create(ctx.guild.id, ctx.author.id, new_name)
        src_tracks = await PlaylistTrackRepo.get_tracks(src_playlist.id)
        track_dicts = [
            {"title": t.title, "url": t.url, "duration": t.duration}
            for t in src_tracks
        ]
        await PlaylistTrackRepo.bulk_add_tracks(
            new_playlist.id, track_dicts, ctx.author.id
        )
        await ctx.send(
            embed=discord.Embed(
                title="Playlist Copied",
                description=(
                    f"Copied **{len(track_dicts)}** tracks to **{new_name}**"
                ),
                color=discord.Color.green(),
            )
        )

    @playlist.command(name="shuffle", description="Permanently shuffle playlist track order")
    @app_commands.describe(name="Playlist name")
    @cooldown(1, 5.0)
    async def playlist_shuffle(self, ctx: commands.Context, *, name: str) -> None:
        """Permanently shuffle the stored order of a playlist."""
        from core.repositories import PlaylistRepo, PlaylistTrackRepo

        playlist = await PlaylistRepo.get_by_name(ctx.guild.id, ctx.author.id, name)
        if not playlist:
            raise PlaylistNotFound(name)

        tracks = await PlaylistTrackRepo.get_tracks(playlist.id)
        if not tracks:
            await ctx.send(f"Playlist **{name}** is empty.", ephemeral=True)
            return

        track_ids = [t.id for t in tracks]
        random.shuffle(track_ids)
        await PlaylistTrackRepo.reorder_tracks(playlist.id, track_ids)

        await ctx.send(
            embed=discord.Embed(
                title="Playlist Shuffled",
                description=f"Shuffled **{len(tracks)}** tracks in **{name}**",
                color=discord.Color.green(),
            )
        )


async def setup(bot: MusicBot) -> None:
    await bot.add_cog(Playlists(bot))
