# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the bot
python bot.py

# Install dependencies
pip install -r requirements.txt
pip install -e ".[dev]"       # with test deps
pip install -e ".[postgres]"  # with PostgreSQL support

# Tests
pytest                         # all tests
pytest tests/test_queue.py -v  # single test file

# Lint & format
ruff check .
ruff format .

# Database migrations
alembic upgrade head
```

## Architecture

Discord music bot (Python 3.11+, discord.py) with dual audio backend support and per-guild isolation.

### Dual Audio Backend

**BackendManager** (`core/backend_manager.py`) probes Lavalink on startup; if unavailable, falls back to FFmpeg. Each guild's **MusicPlayer** (`core/player.py`) can switch backends mid-playback — some FX presets (echo, earrape) require FFmpeg, triggering automatic backend switching with position resume.

- **Lavalink backend** (`core/audio_backends.py`): wavelink-based, supports equalizer/timescale/rotation filters
- **FFmpeg backend** (`core/audio_backends.py`): native discord.py voice, uses yt-dlp extraction with 10-min TTL cache (`core/extractor.py`)

### Playback Flow

`MusicPlayer.play_next()` → dequeues from `MusicQueue` (respecting loop mode) → calls `backend.play(track)` → async task waits for track end → auto-advances. On error, tries fallback backend.

### Key Layers

- **Cogs** (`cogs/`): 7 command modules — music, queue, fx, playlists, settings, utility, dev. Both prefix and slash command support.
- **Core** (`core/`): Player, queue, backends, extraction, filters, permissions, DB models/repos, UI components.
- **Repositories** (`core/repositories.py`): Data access layer over async SQLAlchemy (SQLite default, PostgreSQL optional).
- **Permissions** (`core/permissions.py`): 4-tier system — Owner > Admin > DJ > Everyone. DJ is granted when user is alone in VC with bot.

### Filters System

`core/filters.py` defines 14 built-in presets. Each preset specifies both Lavalink filter params and FFmpeg filter strings. Some presets are backend-specific, which triggers the backend switching logic in MusicPlayer.

### Configuration

`config.py` uses Pydantic BaseSettings loading from `.env` (see `.env.example`). Key vars: `BOT_TOKEN`, `BOT_PREFIX`, `DATABASE_URL`, `LAVALINK_*`, `SPOTIPY_*`.

### Database

7 SQLAlchemy models in `core/models.py`: GuildSettings, Playlist, PlaylistTrack, PlaylistVote, FXPreset, History, Stats, Permission. Migrations managed via Alembic.

## Code Style

Ruff enforced: 100-char line length, Python 3.11+ target. Rules: E, F, I, N, W, UP, B, SIM, RUF (E501 ignored).
