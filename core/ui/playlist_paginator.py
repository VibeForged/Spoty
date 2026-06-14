"""Paginated playlist embed with navigation controls."""

from __future__ import annotations

import discord

from core.playlists.service import PlaylistDetail, PlaylistService


class PlaylistPageSelect(discord.ui.Select):
    """Dropdown for jumping to playlist pages."""

    def __init__(self, view: PlaylistPaginator) -> None:
        self.paginator = view
        super().__init__(
            placeholder="Go to page...",
            min_values=1,
            max_values=1,
            options=_page_options(view.page, view.total_pages),
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.paginator.page = int(self.values[0])
        embed = await self.paginator.build_embed()
        await interaction.response.edit_message(embed=embed, view=self.paginator)


class PlaylistPaginator(discord.ui.View):
    """Interactive playlist viewer with previous, next, and page-jump controls."""

    def __init__(
        self,
        guild_id: int,
        owner_id: int,
        name: str,
        page: int = 1,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.name = name
        self.page = page
        self.total_pages = 1
        self.page_select = PlaylistPageSelect(self)
        self.add_item(self.page_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            "Only the playlist owner can use these controls.",
            ephemeral=True,
        )
        return False

    async def build_embed(self) -> discord.Embed:
        """Fetch the current playlist page and build its embed."""
        detail = await PlaylistService.get_playlist_detail(
            self.guild_id,
            self.owner_id,
            self.name,
            page=self.page,
        )
        self.page = detail.page
        self.total_pages = detail.total_pages
        self._sync_controls()
        return build_playlist_embed(detail)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="\u25c0", row=0)
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.page = max(1, self.page - 1)
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="\u25b6", row=0)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.page = min(self.total_pages, self.page + 1)
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        self.clear_items()

    def _sync_controls(self) -> None:
        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= self.total_pages
        self.page_select.options = _page_options(self.page, self.total_pages)
        self.page_select.disabled = self.total_pages <= 1


def build_playlist_embed(detail: PlaylistDetail) -> discord.Embed:
    """Build a playlist page embed from service details."""
    embed = discord.Embed(
        title=f"Playlist: {detail.playlist.name}",
        color=discord.Color.blue(),
    )
    lines = []
    for item in detail.items:
        dur = f" [{item.duration // 60}:{item.duration % 60:02d}]" if item.duration else ""
        likes, dislikes = detail.vote_counts.get(item.id, (0, 0))
        votes = f" (+{likes}/-{dislikes})" if likes or dislikes else ""
        lines.append(f"`{item.position}.` {item.title[:60]}{dur}{votes}")
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"Page {detail.page}/{detail.total_pages}")
    return embed


def _page_options(current_page: int, total_pages: int) -> list[discord.SelectOption]:
    total_pages = max(1, total_pages)
    current_page = max(1, min(current_page, total_pages))
    max_options = 25

    if total_pages <= max_options:
        start = 1
        end = total_pages
    else:
        half_window = max_options // 2
        start = max(1, current_page - half_window)
        end = start + max_options - 1
        if end > total_pages:
            end = total_pages
            start = end - max_options + 1

    return [
        discord.SelectOption(
            label=f"Page {page}",
            value=str(page),
            default=page == current_page,
        )
        for page in range(start, end + 1)
    ]
