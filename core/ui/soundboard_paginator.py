"""Paginated soundboard listing embed with navigation buttons."""

from __future__ import annotations

import discord


class SoundboardPaginator(discord.ui.View):
    """Paginated view for soundboard sounds.

    Shows 10 sounds per page with Previous/Next navigation buttons.
    """

    def __init__(
        self,
        builtins: list[str],
        customs: list[str],
        page: int = 1,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.builtins = builtins
        self.customs = customs
        # Standardized prefix for visual clarity: 🔊 for built-in, 🎵 for custom
        self.all_sounds = [f"🔊 `{name}`" for name in builtins] + [
            f"🎵 `{name}` *(custom)*" for name in customs
        ]
        self.page = page
        self.per_page = 10
        self.total_pages = max(1, (len(self.all_sounds) + self.per_page - 1) // self.per_page)

    def build_embed(self) -> discord.Embed:
        """Build the soundboard listing embed for the current page."""
        self.page = max(1, min(self.page, self.total_pages))
        start = (self.page - 1) * self.per_page
        end = start + self.per_page
        page_sounds = self.all_sounds[start:end]

        embed = discord.Embed(
            title="🔊 Soundboard Sounds",
            description="\n".join(page_sounds) if page_sounds else "*No sounds available.*",
            color=discord.Color.blurple(),
        )
        embed.set_footer(
            text=f"Page {self.page}/{self.total_pages} | Use /soundboard play <name> to play!"
        )

        self.prev_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= self.total_pages

        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="\u25c0")
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.page = max(1, self.page - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="\u25b6")
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.page = min(self.total_pages, self.page + 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self) -> None:
        self.clear_items()
