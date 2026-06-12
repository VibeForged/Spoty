"""Bot configuration via Pydantic BaseSettings and .env file."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotConfig(BaseSettings):
    """All bot configuration loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=os.environ.get("SPOTY_ENV_FILE", ".env"),
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

    # --- yt-dlp ---
    ytdlp_cookies_file: str = ""
    # Worker threads for the (blocking) yt-dlp extractor, shared across all guilds.
    ytdlp_max_workers: int = 8

    # --- Last.fm (free API for Auto-DJ recommendations) ---
    lastfm_api_key: str = ""

    # --- Logging ---
    log_level: str = "INFO"
    log_file: str = "logs/bot.log"

    # --- Feedback ---
    feedback_webhook_url: str = ""
    feedback_channel_id: int | None = None

    # --- Auto-Update ---
    # Off by default: running `pip install --upgrade yt-dlp` at runtime is unsafe
    # and non-reproducible. Update yt-dlp by bumping the pin and rebuilding instead.
    ytdlp_auto_update: bool = False

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


@lru_cache(maxsize=1)
def get_config() -> BotConfig:
    """Return the process-wide BotConfig singleton.

    Avoids re-parsing the .env file on every call (e.g. on hot paths like the
    yt-dlp extractor and Auto-DJ sources).
    """
    return BotConfig()
