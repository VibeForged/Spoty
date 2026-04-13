"""Bot configuration via Pydantic BaseSettings and .env file."""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotConfig(BaseSettings):
    """All bot configuration loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
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
    lavalink_port: int = 8080
    lavalink_password: str = "youshallnotpass"
    lavalink_secure: bool = False

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

    @field_validator("bot_owner_id", "feedback_channel_id", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        """Allow blank optional numeric values in .env files."""
        if value == "":
            return None
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> object:
        """Convert common sync Postgres URLs to asyncpg URLs for Async SQLAlchemy."""
        if not isinstance(value, str):
            return value

        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)

        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)

        return value
