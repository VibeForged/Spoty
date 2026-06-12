"""Reusable yes/no confirmation view for destructive commands."""

from __future__ import annotations

import contextlib

import discord
from discord.ext import commands


class ConfirmView(discord.ui.View):
    """A short-lived Confirm/Cancel prompt restricted to the invoking user.

    Usage:
        view = ConfirmView(ctx.author.id)
        msg = await ctx.send("Are you sure?", view=view, ephemeral=True)
        await view.wait()
        if view.value:  # confirmed
            ...
    """

    def __init__(self, author_id: int, timeout: float = 30.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This confirmation isn't for you.", ephemeral=True
            )
            return False
        return True

    def _finish(self) -> None:
        for child in self.children:
            child.disabled = True
        self.stop()

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.value = True
        self._finish()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.value = False
        self._finish()
        await interaction.response.edit_message(view=self)

    async def on_timeout(self) -> None:
        self.value = False
        for child in self.children:
            child.disabled = True


async def confirm_action(ctx: commands.Context, prompt: str) -> bool:
    """Send a confirm/cancel prompt and return whether the user confirmed."""
    view = ConfirmView(ctx.author.id)
    message = await ctx.send(prompt, view=view, ephemeral=True)
    await view.wait()
    # Best-effort cleanup of the prompt's components.
    with contextlib.suppress(discord.HTTPException):
        await message.edit(view=view)
    return bool(view.value)
