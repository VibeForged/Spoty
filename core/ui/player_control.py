"""Persistent Player Control Panel View."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from core.filters import BUILTIN_PRESETS
from core.queue import LoopMode

if TYPE_CHECKING:
    from bot import MusicBot
    from core.player import MusicPlayer


async def _check_dj_interaction(interaction: discord.Interaction, bot: MusicBot) -> bool:
    """Check if the user interacting has DJ permissions."""
    from core.permissions import Tier, check_tier, get_user_tier

    class FakeCtx:
        def __init__(self):
            self.bot = bot
            self.author = interaction.user
            self.guild = interaction.guild

    dj_role_id = None
    settings = await bot.get_guild_settings(interaction.guild_id)
    if settings:
        dj_role_id = settings.dj_role_id

    tier = await get_user_tier(FakeCtx(), dj_role_id)
    return check_tier(tier, Tier.DJ)


def build_panel_embed(player: MusicPlayer | None) -> discord.Embed:
    """Build the persistent player control panel embed."""
    embed = discord.Embed(
        title="Spoty Player Control Panel",
        color=discord.Color.purple(),
    )
    if player and player.current:
        track = player.current
        embed.description = f"**Now Playing:**\n[{track.title}]({track.url})"
        embed.add_field(name="Duration", value=track.duration_str, inline=True)
        if track.requester_name and track.requester_name != "Unknown":
            embed.add_field(name="Requested by", value=track.requester_name, inline=True)

        status = []
        if player.is_paused:
            status.append("Paused")

        vol = getattr(player, "volume", 100)
        status.append(f"Volume: {vol}%")

        fx = getattr(player, "active_filters", [])
        if fx:
            status.append(f"FX: {', '.join(fx)}")

        embed.add_field(
            name="Status", value=" | ".join(status) if status else "Playing", inline=False
        )

        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
    else:
        embed.description = "**Nothing is currently playing.**\n*Join a voice channel and use a music command to start!*"

    return embed


class FXSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label="Clear FX", value="clear", emoji="🚫")]
        # Add a few popular built-in presets
        popular = ["bassboost", "nightcore", "vaporwave", "karaoke", "tremolo"]
        for p in popular:
            if p in BUILTIN_PRESETS:
                options.append(discord.SelectOption(label=p.title(), value=p))

        super().__init__(
            placeholder="Select Audio Effect...",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
            custom_id="panel_fx_select",
        )

    async def callback(self, interaction: discord.Interaction):
        view: PlayerControlPanel = self.view
        if not await _check_dj_interaction(interaction, view.bot):
            return await interaction.response.send_message(
                "You need the DJ role to use this.", ephemeral=True
            )

        player = view.player
        if not player or player._destroyed:
            await interaction.response.send_message("Player is not active.", ephemeral=True)
            return

        val = self.values[0]
        if val == "clear":
            await player.apply_filters([])
            await interaction.response.send_message("Cleared all audio effects.", ephemeral=True)
        else:
            await player.apply_filters([val])
            await interaction.response.send_message(
                f"Applied {val.title()} effect.", ephemeral=True
            )

        await view.update_panel(interaction)


class VolumeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Volume: 25%", value="25"),
            discord.SelectOption(label="Volume: 50%", value="50"),
            discord.SelectOption(label="Volume: 75%", value="75"),
            discord.SelectOption(label="Volume: 100%", value="100"),
            discord.SelectOption(label="Volume: 150%", value="150"),
        ]
        super().__init__(
            placeholder="Adjust Volume...",
            min_values=1,
            max_values=1,
            options=options,
            row=2,
            custom_id="panel_vol_select",
        )

    async def callback(self, interaction: discord.Interaction):
        view: PlayerControlPanel = self.view
        if not await _check_dj_interaction(interaction, view.bot):
            return await interaction.response.send_message(
                "You need the DJ role to use this.", ephemeral=True
            )

        player = view.player
        if not player or player._destroyed:
            await interaction.response.send_message("Player is not active.", ephemeral=True)
            return

        vol = int(self.values[0])
        await player.set_volume(vol)
        await interaction.response.send_message(f"Volume set to {vol}%.", ephemeral=True)
        await view.update_panel(interaction)


class PlayerControlPanel(discord.ui.View):
    """Persistent interactive buttons for the Player Control Panel."""

    def __init__(self, bot: MusicBot, guild_id: int) -> None:
        # Timeout is None so the view is persistent
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id

        self.add_item(FXSelect())
        self.add_item(VolumeSelect())

    @property
    def player(self) -> MusicPlayer | None:
        return self.bot.get_player(self.guild_id)

    def _get_pause_label(self) -> str:
        if self.player and self.player.is_paused:
            return "Resume"
        return "Pause"

    def _get_pause_emoji(self) -> str:
        if self.player and self.player.is_paused:
            return "\u25b6"
        return "\u23f8"

    def _get_loop_label(self) -> str:
        if not self.player:
            return "Loop: Off"
        mode = self.player.queue.loop_mode
        if mode == LoopMode.OFF:
            return "Loop: Off"
        elif mode == LoopMode.TRACK:
            return "Loop: Track"
        return "Loop: Queue"

    async def update_panel(self, interaction: discord.Interaction | None = None) -> None:
        """Update the panel's visual state based on the player."""
        # Update button labels
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "panel_pause":
                    child.label = self._get_pause_label()
                    child.emoji = self._get_pause_emoji()
                elif child.custom_id == "panel_loop":
                    child.label = self._get_loop_label()

        embed = build_panel_embed(self.player)
        if interaction:
            # Check if interaction is already responded to
            if interaction.response.is_done():
                await interaction.message.edit(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        else:
            # We don't have an interaction context, we just want to update the message.
            # This is handled by core/player.py passing the message to edit.
            pass

    @discord.ui.button(
        label="Pause",
        style=discord.ButtonStyle.primary,
        emoji="\u23f8",
        custom_id="panel_pause",
        row=0,
    )
    async def pause_resume(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await _check_dj_interaction(interaction, self.bot):
            return await interaction.response.send_message(
                "You need the DJ role to use this.", ephemeral=True
            )

        if not self.player or self.player._destroyed:
            await interaction.response.send_message("Player is not active.", ephemeral=True)
            return
        if self.player.is_paused:
            await self.player.resume()
        else:
            await self.player.pause()

        await self.update_panel(interaction)

    @discord.ui.button(
        label="Skip",
        style=discord.ButtonStyle.secondary,
        emoji="\u23ed",
        custom_id="panel_skip",
        row=0,
    )
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await _check_dj_interaction(interaction, self.bot):
            return await interaction.response.send_message(
                "You need the DJ role to use this.", ephemeral=True
            )

        if not self.player or self.player._destroyed:
            await interaction.response.send_message("Player is not active.", ephemeral=True)
            return
        await self.player.skip()
        await interaction.response.send_message("Skipped!", ephemeral=True)
        # update_panel will be called by player.py when track actually changes

    @discord.ui.button(
        label="Stop",
        style=discord.ButtonStyle.danger,
        emoji="\u23f9",
        custom_id="panel_stop",
        row=0,
    )
    async def stop_player(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await _check_dj_interaction(interaction, self.bot):
            return await interaction.response.send_message(
                "You need the DJ role to use this.", ephemeral=True
            )

        if not self.player or self.player._destroyed:
            await interaction.response.send_message("Player is not active.", ephemeral=True)
            return
        await self.player.stop()
        await interaction.response.send_message("Stopped playback.", ephemeral=True)
        # update_panel will be called by player.py

    @discord.ui.button(
        label="Loop: Off",
        style=discord.ButtonStyle.secondary,
        emoji="\U0001f501",
        custom_id="panel_loop",
        row=0,
    )
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await _check_dj_interaction(interaction, self.bot):
            return await interaction.response.send_message(
                "You need the DJ role to use this.", ephemeral=True
            )

        if not self.player or self.player._destroyed:
            await interaction.response.send_message("Player is not active.", ephemeral=True)
            return
        mode = self.player.queue.loop_mode
        if mode == LoopMode.OFF:
            self.player.queue.loop_mode = LoopMode.TRACK
        elif mode == LoopMode.TRACK:
            self.player.queue.loop_mode = LoopMode.QUEUE
        else:
            self.player.queue.loop_mode = LoopMode.OFF

        await self.update_panel(interaction)

    @discord.ui.button(
        label="Shuffle",
        style=discord.ButtonStyle.secondary,
        emoji="\U0001f500",
        custom_id="panel_shuffle",
        row=0,
    )
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await _check_dj_interaction(interaction, self.bot):
            return await interaction.response.send_message(
                "You need the DJ role to use this.", ephemeral=True
            )

        if not self.player or self.player._destroyed:
            await interaction.response.send_message("Player is not active.", ephemeral=True)
            return
        self.player.queue.shuffle()
        await interaction.response.send_message("Queue shuffled!", ephemeral=True)
