"""Bot configuration via Pydantic BaseSettings and .env file."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotConfig(BaseSettings):
    """All bot configuration loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Required ---
    bot_token: str

    # --- Bot Settings ---
    bot_prefix: str = "!"
    bot_owner_id: int | None = None

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///data/bot.db"

    # --- Lavalink ---
    lavalink_enabled: bool = True
    lavalink_host: str = "localhost"
    lavalink_port: int = 2333
    lavalink_password: str = "youshallnotpass"

    # --- FFmpeg ---
    ffmpeg_path: str = "ffmpeg"

    # --- Spotify ---
    spotipy_client_id: str = ""
    spotipy_client_secret: str = ""

    @property
    def spotify_configured(self) -> bool:
        """Check if Spotify credentials are provided."""
        return bool(self.spotipy_client_id and self.spotipy_client_secret)

    # --- Logging ---
    log_level: str = "INFO"
    log_file: str = "logs/bot.log"

    # --- Feedback ---
    feedback_webhook_url: str = ""
    feedback_channel_id: int | None = None

    # --- Auto-Update ---
    ytdlp_auto_update: bool = True
