"""Now Playing interactive button view."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from core.queue import LoopMode

if TYPE_CHECKING:
    from core.player import MusicPlayer


class NowPlayingView(discord.ui.View):
    """Interactive buttons for the Now Playing embed.

    Buttons: Pause/Resume, Skip, Stop, Loop, Shuffle
    """

    def __init__(self, player: MusicPlayer, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.player = player

    def _get_pause_label(self) -> str:
        return "Resume" if self.player.is_paused else "Pause"

    def _get_pause_emoji(self) -> str:
        return "\u25b6" if self.player.is_paused else "\u23f8"

    def _get_loop_label(self) -> str:
        mode = self.player.queue.loop_mode
        if mode == LoopMode.OFF:
            return "Loop: Off"
        elif mode == LoopMode.TRACK:
            return "Loop: Track"
        return "Loop: Queue"

    def _check_player(self, interaction: discord.Interaction) -> bool:
        """Return True if player is destroyed (and handle the interaction)."""
        return self.player._destroyed

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.primary, emoji="\u23f8")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._check_player(interaction):
            await interaction.response.send_message("Player is no longer active.", ephemeral=True)
            self.stop()
            return
        if self.player.is_paused:
            await self.player.resume()
        else:
            await self.player.pause()

        button.label = self._get_pause_label()
        button.emoji = self._get_pause_emoji()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="\u23ed")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._check_player(interaction):
            await interaction.response.send_message("Player is no longer active.", ephemeral=True)
            self.stop()
            return
        await self.player.skip()
        await interaction.response.send_message("Skipped!", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="\u23f9")
    async def stop_player(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._check_player(interaction):
            await interaction.response.send_message("Player is no longer active.", ephemeral=True)
            self.stop()
            return
        await self.player.stop()
        await interaction.response.send_message("Stopped playback.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Loop: Off", style=discord.ButtonStyle.secondary, emoji="\U0001f501")
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._check_player(interaction):
            await interaction.response.send_message("Player is no longer active.", ephemeral=True)
            self.stop()
            return
        mode = self.player.queue.loop_mode
        if mode == LoopMode.OFF:
            self.player.queue.loop_mode = LoopMode.TRACK
        elif mode == LoopMode.TRACK:
            self.player.queue.loop_mode = LoopMode.QUEUE
        else:
            self.player.queue.loop_mode = LoopMode.OFF

        button.label = self._get_loop_label()
        await interaction.response.edit_message(view=self)

    async def on_timeout(self) -> None:
        self.clear_items()
