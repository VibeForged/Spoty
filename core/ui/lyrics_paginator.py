"""Paginated lyrics embed with navigation buttons."""

from __future__ import annotations

import discord


class LyricsPaginator(discord.ui.View):
    """Paginated view for song lyrics."""

    def __init__(self, query: str, lyrics: str, timeout: float = 180.0) -> None:
        super().__init__(timeout=timeout)
        self.query = query

        # Split lyrics into pages of max 1500 characters
        self.pages = []
        lines = lyrics.split("\n")
        current_page = ""

        for line in lines:
            # If a single line is absurdly long, we'd need to chunk it, but for lyrics it's fine.
            if len(current_page) + len(line) > 1500:
                self.pages.append(current_page.strip())
                current_page = line + "\n"
            else:
                current_page += line + "\n"

        if current_page.strip():
            self.pages.append(current_page.strip())

        if not self.pages:
            self.pages = ["[No lyrics found]"]

        self.current_page = 0

    def build_embed(self) -> discord.Embed:
        """Build the lyrics embed for the current page."""
        embed = discord.Embed(
            title=f"Lyrics: {self.query[:100]}",
            description=self.pages[self.current_page],
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.pages)}")

        # Update button states
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.pages) - 1

        return embed

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, emoji="\u25c0")
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, emoji="\u25b6")
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.current_page = min(len(self.pages) - 1, self.current_page + 1)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        try:
            if hasattr(self, "message") and self.message:
                await self.message.edit(view=self)
        except Exception:
            pass
