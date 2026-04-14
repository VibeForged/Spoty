"""Interactive FX preset builder using modals and dropdowns."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from core.filters import (
    BUILTIN_PRESETS,
    PRESET_DESCRIPTIONS,
    combine_preset_definitions,
    summarize_preset_definition,
)

if TYPE_CHECKING:
    from bot import MusicBot


class FXBuilderView(discord.ui.View):
    """Step-by-step interactive FX preset builder.

    Walks the user through selecting effects via dropdowns and modals,
    then saves the resulting filter chain as a custom preset.
    """

    def __init__(
        self, guild_id: int, user_id: int, *, bot: MusicBot | None = None, timeout: float = 300.0
    ) -> None:
        super().__init__(timeout=timeout)
        self.guild_id = guild_id
        self.user_id = user_id
        self.bot = bot
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
        await interaction.response.send_message(
            f"Selected: **{', '.join(self.selected_presets)}**. "
            "Use **Preview** to see the combined effect or **Save** (via the dropdown again) to name it.",
            ephemeral=True,
        )

    @discord.ui.button(label="Preview", style=discord.ButtonStyle.secondary, row=1)
    async def preview_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Combine selected presets and show a summary embed."""
        if not self.selected_presets:
            await interaction.response.send_message(
                "Please select at least one effect first.", ephemeral=True
            )
            return

        try:
            combined = combine_preset_definitions(self.selected_presets)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        summary = summarize_preset_definition(combined)
        embed = discord.Embed(
            title="Preview: Combined Effects",
            description=f"**Effects:** {', '.join(self.selected_presets)}\n**Result:** {summary}",
            color=discord.Color.purple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Save", style=discord.ButtonStyle.success, row=1)
    async def save_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Open the naming modal to save the combined preset."""
        if not self.selected_presets:
            await interaction.response.send_message(
                "Please select at least one effect first.", ephemeral=True
            )
            return
        await interaction.response.send_modal(FXNameModal(self))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=1)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Cancel the builder and stop the view."""
        await interaction.response.send_message("FX Builder cancelled.", ephemeral=True)
        self.stop()

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
        from core.repositories import FXPresetRepo

        preset_name = self.name.value.lower()

        # Check for conflicts with built-in presets
        if preset_name in BUILTIN_PRESETS:
            await interaction.response.send_message(
                f"**{preset_name}** conflicts with a built-in preset. Choose a different name.",
                ephemeral=True,
            )
            return

        # Check for conflicts with existing custom presets
        existing = await FXPresetRepo.get_by_name(self.builder_view.guild_id, preset_name)
        if existing:
            await interaction.response.send_message(
                f"A custom preset named **{preset_name}** already exists. Choose a different name.",
                ephemeral=True,
            )
            return

        # Combine selected presets into a definition
        try:
            definition = combine_preset_definitions(self.builder_view.selected_presets)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        # Save to DB
        await FXPresetRepo.create(
            self.builder_view.guild_id,
            preset_name,
            definition,
            self.builder_view.user_id,
        )

        summary = summarize_preset_definition(definition)
        await interaction.response.send_message(
            f"Preset **{preset_name}** created! Effects: {summary}\n"
            f"Use `/setfx {preset_name}` to apply it!",
            ephemeral=True,
        )
        self.builder_view.stop()
