"""Discord Music Bot — Entry point.

Loads configuration, initializes the database, loads all cogs, and starts the bot.
"""

from __future__ import annotations

import sys
from pathlib import Path

import discord
import wavelink
from cachetools import LRUCache
from discord.ext import commands
from dotenv import load_dotenv
from loguru import logger

from config import BotConfig, get_config
from core.backend_manager import BackendManager
from core.database import close_db, init_db, run_migrations
from core.models import GuildSettings
from core.player import MusicPlayer
from core.repositories import GuildSettingsRepo

# All cogs to load on startup
COGS = [
    "cogs.music",
    "cogs.queue_cog",
    "cogs.fx",
    "cogs.playlists",
    "cogs.settings",
    "cogs.autodj",
    "cogs.utility",
    "cogs.dev",
]


class MusicBot(commands.Bot):
    """Custom Bot subclass with per-guild player management."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config

        # Dynamic per-guild prefix
        async def get_prefix(bot: MusicBot, message: discord.Message) -> list[str]:
            prefixes = [config.bot_prefix]
            if message.guild:
                settings = await self.get_guild_settings(message.guild.id)
                if settings and settings.prefix:
                    prefixes = [settings.prefix]
            # Always allow mention as prefix
            return commands.when_mentioned_or(*prefixes)(bot, message)

        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True
        intents.members = False  # Not needed, saves memory

        super().__init__(
            command_prefix=get_prefix,
            intents=intents,
            help_command=None,  # Custom help in utility cog
            owner_id=config.bot_owner_id,
        )

        # Per-guild player instances
        self.players: dict[int, MusicPlayer] = {}

        # Bounded cache for guild settings (LRU prevents unbounded growth at scale)
        self._settings_cache: LRUCache[int, GuildSettings] = LRUCache(maxsize=2000)
        self.backend_manager = BackendManager(self)

        # Auto-DJ recommendation engine (shared across all guilds)
        from core.autodj.engine import AutoDJEngine

        self.autodj_engine = AutoDJEngine()

    async def get_guild_settings(self, guild_id: int) -> GuildSettings | None:
        """Get guild settings with in-memory caching."""
        if guild_id in self._settings_cache:
            return self._settings_cache[guild_id]

        settings = await GuildSettingsRepo.get_or_create(guild_id)
        self._settings_cache[guild_id] = settings
        return settings

    def invalidate_settings_cache(self, guild_id: int) -> None:
        """Invalidate cached settings for a guild (call after settings update)."""
        self._settings_cache.pop(guild_id, None)

    def get_player(self, guild_id: int) -> MusicPlayer | None:
        """Get the music player for a guild."""
        return self.players.get(guild_id)

    async def create_player(
        self,
        guild_id: int,
        channel: discord.VoiceChannel,
        text_channel: discord.TextChannel | None = None,
    ) -> MusicPlayer:
        """Create and register a backend-aware player for a guild."""
        player = await MusicPlayer.create(self, guild_id, channel)
        player.text_channel = text_channel
        self.players[guild_id] = player
        return player

    async def setup_hook(self) -> None:
        """Called after login, before connecting to the gateway."""
        # Initialize database
        await init_db(self.config.database_url)
        await self.backend_manager.setup()

        # Auto-update yt-dlp if configured
        if self.config.ytdlp_auto_update:
            from core.extractor import update_ytdlp

            logger.info("Auto-updating yt-dlp...")
            if await update_ytdlp():
                logger.info("yt-dlp updated successfully")
            else:
                logger.warning("yt-dlp update failed (may already be latest)")

        # Load all cogs
        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info("Loaded cog: {}", cog)
            except Exception as e:
                logger.error("Failed to load cog {}: {}", cog, e)

        logger.info("Setup complete — {} cogs loaded", len(self.extensions))
        logger.info("Audio backend status: {}", self.backend_manager.backend_status())

    async def on_ready(self) -> None:
        logger.info("Bot ready as {} (ID: {})", self.user, self.user.id)
        logger.info("Connected to {} guilds", len(self.guilds))

        if self.config.lavalink_enabled and not self.backend_manager.lavalink_ready:
            await self.backend_manager.ensure_ready()
            logger.info("Audio backend status after ready: {}", self.backend_manager.backend_status())

        # Set activity
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=f"{self.config.bot_prefix}help | music",
            )
        )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Create default settings when joining a new guild."""
        logger.info("Joined guild: {} ({})", guild.name, guild.id)
        await GuildSettingsRepo.get_or_create(guild.id)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Clean up when removed from a guild."""
        logger.info("Left guild: {} ({})", guild.name, guild.id)
        # Destroy player if active
        player = self.players.get(guild.id)
        if player:
            await player.destroy()
        # Invalidate cache
        self.invalidate_settings_cache(guild.id)

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Handle voice state changes for inactivity detection."""
        if member.id == self.user.id:
            # Bot was disconnected
            if before.channel and not after.channel:
                player = self.players.get(member.guild.id)
                if (
                    player
                    and not getattr(player, "_backend_switch_in_progress", False)
                    and self.players.get(member.guild.id) is player
                ):
                    await player.destroy()
            return

        # Check if bot is alone in voice channel
        player = self.players.get(member.guild.id)
        if player and player.voice_client and player.voice_client.channel:
            try:
                channel = player.voice_client.channel
                non_bot_members = [m for m in channel.members if not m.bot]
                if not non_bot_members:
                    # Bot is alone — start inactivity timer
                    player._start_inactive_timer()
                else:
                    # Someone joined back — cancel timer
                    player._cancel_inactive_timer()
            except Exception:
                logger.debug("Error checking voice channel members", exc_info=True)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        """Global error handler for prefix commands."""
        from core.errors import MusicBotError

        if isinstance(error, commands.CommandNotFound):
            return  # Silently ignore unknown commands

        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                embed=discord.Embed(
                    title="Cooldown",
                    description=f"Please wait {error.retry_after:.1f}s before using this command again.",
                    color=discord.Color.orange(),
                ),
                delete_after=5,
            )
            return

        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                embed=discord.Embed(
                    title="Missing Argument",
                    description=f"Missing required argument: `{error.param.name}`",
                    color=discord.Color.red(),
                ),
                delete_after=10,
            )
            return

        if isinstance(error, commands.CheckFailure) and isinstance(error, MusicBotError):
            await ctx.send(
                embed=discord.Embed(
                    title="Error",
                    description=error.message,
                    color=discord.Color.red(),
                ),
                delete_after=10,
            )
            return

        # Unwrap CommandInvokeError
        original = getattr(error, "original", error)
        if isinstance(original, MusicBotError):
            await ctx.send(
                embed=discord.Embed(
                    title="Error",
                    description=original.message,
                    color=discord.Color.red(),
                ),
                delete_after=10,
            )
            return

        # Unexpected error
        logger.exception("Unhandled error in command {}: {}", ctx.command, error)
        await ctx.send(
            embed=discord.Embed(
                title="Unexpected Error",
                description="An unexpected error occurred. Please try again later.",
                color=discord.Color.red(),
            ),
            delete_after=10,
        )

    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload) -> None:
        self.backend_manager.last_lavalink_error = None
        self.backend_manager.refresh_lavalink_state()
        logger.info("Lavalink node ready: {}", payload.node.identifier)

    async def on_wavelink_node_disconnected(
        self, payload: wavelink.NodeDisconnectedEventPayload
    ) -> None:
        self.backend_manager.last_lavalink_error = "node disconnected"
        self.backend_manager.refresh_lavalink_state()
        logger.warning("Lavalink node disconnected: {}", payload.node.identifier)

    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload) -> None:
        if payload.player is None or payload.player.guild is None:
            return
        player = self.players.get(payload.player.guild.id)
        if player:
            await player.handle_lavalink_event()

    async def on_wavelink_track_exception(
        self, payload: wavelink.TrackExceptionEventPayload
    ) -> None:
        if payload.player is None or payload.player.guild is None:
            return
        player = self.players.get(payload.player.guild.id)
        if player:
            if isinstance(payload.exception, dict):
                message = payload.exception.get("message", "Unknown Lavalink exception")
            else:
                message = str(payload.exception)
            await player.handle_lavalink_event(Exception(message))

    async def on_wavelink_websocket_closed(
        self, payload: wavelink.WebsocketClosedEventPayload
    ) -> None:
        if payload.player is None or payload.player.guild is None:
            return
        player = self.players.get(payload.player.guild.id)
        if player:
            await player.handle_lavalink_event(Exception(f"Websocket closed: {payload.reason}"))

    async def close(self) -> None:
        """Graceful shutdown — destroy all players and close DB."""
        logger.info("Shutting down...")

        # Destroy all players
        for guild_id in list(self.players.keys()):
            player = self.players.get(guild_id)
            if player:
                await player.destroy()

        await self.backend_manager.shutdown()

        # Shutdown extractor thread pool
        from core.extractor import shutdown_pool
        shutdown_pool()

        # Close database
        await close_db()

        await super().close()
        logger.info("Shutdown complete")


def setup_logging(config: BotConfig) -> None:
    """Configure loguru logging."""
    # Remove default handler
    logger.remove()

    # Console handler
    logger.add(
        sys.stderr,
        level=config.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    )

    # File handler
    if config.log_file:
        log_path = Path(config.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            config.log_file,
            level="DEBUG",
            rotation="10 MB",
            retention="7 days",
            compression="zip",
        )


def main() -> None:
    """Entry point."""
    import keep_alive
    keep_alive.keep_alive()

    # Load environment variables
    load_dotenv()

    # Set up basic logging format for stdout
    logger.remove()

    config = get_config()
    setup_logging(config)

    logger.info("Starting Discord Music Bot...")

    # Apply database migrations (synchronously, before the bot event loop starts).
    run_migrations(config.database_url)

    bot = MusicBot(config)

    try:
        bot.run(config.bot_token, log_handler=None)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.exception("Fatal error: {}", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
