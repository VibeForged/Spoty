"""Paginated queue embed with navigation buttons."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from core.player import MusicPlayer


class QueuePaginator(discord.ui.View):
    """Paginated view for the music queue.

    Shows 8 tracks per page with Previous/Next navigation buttons.
    """

    def __init__(self, player: MusicPlayer, page: int = 1, timeout: float = 120.0) -> None:
        super().__init__(timeout=timeout)
        self.player = player
        self.page = page

    def build_embed(self) -> discord.Embed:
        """Build the queue embed for the current page."""
        tracks, total_pages = self.player.queue.get_page(self.page, per_page=8)

        embed = discord.Embed(title="Music Queue", color=discord.Color.blue())

        # Current track
        if self.player.current:
            current = self.player.current
            pos_str = _format_ms(self.player.position_ms)
            embed.description = (
                f"**Now Playing:** [{current.short_title}]({current.url}) "
                f"`{pos_str}/{current.duration_str}`"
            )

        # Queue tracks
        if not tracks:
            embed.add_field(name="Queue", value="Empty", inline=False)
        else:
            start_idx = (self.page - 1) * 8
            lines = []
            for i, track in enumerate(tracks, start=start_idx + 1):
                lines.append(f"`{i}.` [{track.short_title}]({track.url}) `{track.duration_str}`")
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)

        # Footer
        total = self.player.queue.size
        total_dur = self.player.queue.total_duration
        loop = self.player.queue.loop_mode.value
        embed.set_footer(
            text=f"Page {self.page}/{total_pages} | {total} tracks | "
            f"Duration: {_format_seconds(total_dur)} | Loop: {loop}"
        )

        # Disable buttons at boundaries
        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= total_pages

        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="\u25c0")
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self.player._destroyed:
            await interaction.response.send_message("Player is no longer active.", ephemeral=True)
            self.stop()
            return
        self.page = max(1, self.page - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="\u25b6")
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self.player._destroyed:
            await interaction.response.send_message("Player is no longer active.", ephemeral=True)
            self.stop()
            return
        _, total_pages = self.player.queue.get_page(self.page, per_page=8)
        self.page = min(total_pages, self.page + 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self) -> None:
        self.clear_items()


def _format_ms(ms: int) -> str:
    """Format milliseconds as MM:SS or HH:MM:SS."""
    seconds = ms // 1000
    return _format_seconds(seconds)


def _format_seconds(seconds: int) -> str:
    """Format seconds as MM:SS or HH:MM:SS."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
