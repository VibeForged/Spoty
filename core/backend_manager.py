"""Backend selection and Lavalink lifecycle management."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
import discord
import wavelink
from loguru import logger

from core.audio_backends import BackendUnavailableError, FFmpegBackend, LavalinkBackend

if TYPE_CHECKING:
    from bot import MusicBot


class BackendManager:
    """Coordinates Lavalink initialization and guild backend creation."""

    def __init__(self, bot: MusicBot) -> None:
        self.bot = bot
        self.lavalink_ready = False
        self.last_lavalink_error: str | None = None
        self._lavalink_node_identifier = "primary"
        self._setup_attempted = False

    async def setup(self) -> None:
        """Initialize the preferred Lavalink backend if configured."""
        if not self.bot.config.lavalink_enabled:
            logger.info("Lavalink disabled in config; FFmpeg will be used by default")
            self.lavalink_ready = False
            return

        try:
            logger.debug(
                "Effective Lavalink config: host={}, port={}, password={}, secure={}",
                self.bot.config.lavalink_host,
                self.bot.config.lavalink_port,
                "<set>" if self.bot.config.lavalink_password else "<unset>",
                self.bot.config.lavalink_secure,
            )

            scheme = "https" if self.bot.config.lavalink_secure else "http"
            uri = f"{scheme}://{self.bot.config.lavalink_host}:{self.bot.config.lavalink_port}"
            self._setup_attempted = True

            if self.bot.user is None:
                self.lavalink_ready = False
                self.last_lavalink_error = "discord client user is not ready yet"
                logger.info("Deferring Lavalink connection until Discord client is ready: {}", uri)
                return

            await self._probe_lavalink(uri)
            node = wavelink.Node(
                identifier=self._lavalink_node_identifier,
                uri=uri,
                password=self.bot.config.lavalink_password,
                client=self.bot,
            )
            await wavelink.Pool.connect(nodes=[node], client=self.bot)
            self.refresh_lavalink_state()
            self.last_lavalink_error = None
            if self.lavalink_ready:
                logger.info("Lavalink connected successfully: {}", uri)
            else:
                logger.info(
                    "Lavalink connection initiated: {}; waiting for node to reach CONNECTED state",
                    uri,
                )
        except Exception as exc:
            self.lavalink_ready = False
            self.last_lavalink_error = str(exc)
            logger.warning("Lavalink unavailable, FFmpeg fallback will be used: {}", exc)

    async def shutdown(self) -> None:
        """Disconnect backend resources."""
        try:
            node = self.get_lavalink_node()
        except Exception:
            return
        await node.close(eject=True)

    async def ensure_ready(self) -> bool:
        """Attempt Lavalink setup once the Discord client is fully ready."""
        if not self.bot.config.lavalink_enabled:
            return False
        if self.refresh_lavalink_state():
            return True
        await self.setup()
        return self.refresh_lavalink_state()

    def get_lavalink_node(self):
        """Return the configured Lavalink node when available."""
        self.refresh_lavalink_state()
        if not self.lavalink_ready:
            raise BackendUnavailableError(self.last_lavalink_error or "Lavalink is not ready")
        return wavelink.Pool.get_node(self._lavalink_node_identifier)

    def refresh_lavalink_state(self) -> bool:
        """Refresh the cached Lavalink readiness flag from the actual node status."""
        try:
            node = wavelink.Pool.get_node(self._lavalink_node_identifier)
        except Exception:
            self.lavalink_ready = False
            return False

        self.lavalink_ready = node.status is wavelink.NodeStatus.CONNECTED
        if not self.lavalink_ready and self.last_lavalink_error is None:
            self.last_lavalink_error = f"node status is {node.status}"
        return self.lavalink_ready

    async def _probe_lavalink(self, uri: str) -> None:
        """Run a small authenticated REST probe to surface config/auth mismatches."""
        headers = {
            "Authorization": self.bot.config.lavalink_password,
            "User-Id": str(self.bot.user.id),
            "Client-Name": "Spoty-ReReborn/1.0",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{uri}/version", headers=headers) as response:
                if response.status >= 400:
                    detail = ""
                    if response.status in {401, 403}:
                        detail = (
                            " (authentication rejected; check LAVALINK_PASSWORD and the "
                            "server's application.yml password)"
                        )
                    raise BackendUnavailableError(
                        f"Lavalink /version probe failed with HTTP {response.status} at {uri}{detail}"
                    )
            async with session.get(f"{uri}/v4/info", headers=headers) as response:
                if response.status >= 400:
                    detail = ""
                    if response.status in {401, 403}:
                        detail = (
                            " (authentication rejected; check LAVALINK_PASSWORD and the "
                            "server's application.yml password)"
                        )
                    raise BackendUnavailableError(
                        f"Lavalink /v4/info probe failed with HTTP {response.status} at {uri}{detail}"
                    )

    async def connect_preferred(self, channel: discord.VoiceChannel):
        """Connect to the preferred backend for a voice channel."""
        if self.bot.config.lavalink_enabled and await self.ensure_ready():
            try:
                node = self.get_lavalink_node()
                vc = await channel.connect(cls=wavelink.Player, self_deaf=True)
                logger.info(
                    "Connected guild {} using Lavalink node {}",
                    channel.guild.id,
                    node.identifier,
                )
                return LavalinkBackend(vc, self.bot.config)
            except Exception as exc:
                self.last_lavalink_error = str(exc)
                logger.warning("Lavalink voice connect failed for guild {}: {}", channel.guild.id, exc)
        elif self.bot.config.lavalink_enabled:
            detail = self.last_lavalink_error or "node is not CONNECTED"
            logger.info(
                "Lavalink not ready for guild {} ({}); using FFmpeg fallback",
                channel.guild.id,
                detail,
            )

        return await self.connect_ffmpeg(channel)

    async def connect_ffmpeg(self, channel: discord.VoiceChannel) -> FFmpegBackend:
        """Connect to FFmpeg native voice for a channel."""
        vc = await channel.connect(self_deaf=True)
        logger.info("Connected guild {} using FFmpeg", channel.guild.id)
        return FFmpegBackend(vc, self.bot.config)

    async def fallback_backend(self, channel: discord.VoiceChannel) -> FFmpegBackend:
        """Create the FFmpeg fallback backend for a channel."""
        return await self.connect_ffmpeg(channel)

    def backend_status(self) -> str:
        """Return a concise backend status summary."""
        self.refresh_lavalink_state()
        if self.lavalink_ready:
            return "Lavalink ready, FFmpeg fallback enabled"
        if self.bot.config.lavalink_enabled:
            detail = f" ({self.last_lavalink_error})" if self.last_lavalink_error else ""
            return f"FFmpeg fallback active; Lavalink unavailable{detail}"
        return "FFmpeg only"
