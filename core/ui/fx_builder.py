"""Interactive FX preset builder using modals and dropdowns.

Full implementation in Phase 4. This is a stub for cog loading.
"""

from __future__ import annotations

import discord

from core.filters import BUILTIN_PRESETS, PRESET_DESCRIPTIONS


class FXBuilderView(discord.ui.View):
    """Step-by-step interactive FX preset builder.

    Walks the user through selecting effects via dropdowns and modals,
    then saves the resulting filter chain as a custom preset.

    Full implementation in Phase 4.
    """

    def __init__(self, guild_id: int, user_id: int, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.guild_id = guild_id
        self.user_id = user_id
        self.selected_presets: list[str] = []
        self.preset_name: str | None = None

    @discord.ui.select(
        placeholder="Select effects to combine...",
        min_values=1,
        max_values=5,
        options=[
            discord.SelectOption(
                label=name,
                description=PRESET_DESCRIPTIONS.get(name, ""),
                value=name,
            )
            for name in list(BUILTIN_PRESETS.keys())[:25]  # Discord max 25 options
        ],
    )
    async def effect_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        self.selected_presets = select.values
        await interaction.response.send_modal(FXNameModal(self))

    async def on_timeout(self) -> None:
        self.clear_items()


class FXNameModal(discord.ui.Modal, title="Name Your Preset"):
    """Modal for naming a custom FX preset."""

    name = discord.ui.TextInput(
        label="Preset Name",
        placeholder="e.g., chill-vibes",
        min_length=1,
        max_length=50,
    )

    def __init__(self, builder_view: FXBuilderView) -> None:
        super().__init__()
        self.builder_view = builder_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.builder_view.preset_name = self.name.value
        presets = ", ".join(self.builder_view.selected_presets)
        await interaction.response.send_message(
            f"Preset **{self.name.value}** created with effects: {presets}\n"
            f"Use `/setfx {self.name.value}` to apply it!",
            ephemeral=True,
        )
        self.builder_view.stop()
