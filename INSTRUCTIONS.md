# Spoty Discord Bot — Setup & Usage Instructions

## Prerequisites

- **Python 3.11+** (3.12 recommended)
- **FFmpeg** — must be in PATH or set `FFMPEG_PATH` in `.env`
- **pip** — Python package manager
- **Git** — for version control

### Optional

- **Lavalink 4** — for high-quality audio (falls back to FFmpeg if unavailable)
- **PostgreSQL** — for production (defaults to SQLite)
- **Docker & Docker Compose** — for containerized deployment

---

## Step 1: Install Dependencies

```bash
# Core dependencies
pip install -r requirements.txt

# For development (adds ruff, pytest, pytest-asyncio)
pip install ruff pytest pytest-asyncio

# Optional: PostgreSQL support
pip install asyncpg
```

### Dependency Breakdown

| Package | Purpose |
|---------|---------|
| `discord.py[voice]` | Discord API + voice support |
| `PyNaCl` | Voice encryption |
| `yt-dlp` | YouTube/SoundCloud audio extraction |
| `wavelink` | Lavalink client |
| `SQLAlchemy[asyncio]` + `aiosqlite` | Async database |
| `alembic` | Database migrations |
| `pydantic-settings` | Configuration management |
| `spotipy` | Spotify playlist import |
| `syncedlyrics` | Lyrics fetching |
| `rapidfuzz` | Fuzzy text matching (music quiz) |
| `cachetools` | TTL cache for yt-dlp |
| `loguru` | Logging |
| `aiohttp` | HTTP client |

---

## Step 2: Configure the Bot

```bash
# Copy the example config
cp .env.example .env
```

Edit `.env` and set at minimum:

```ini
BOT_TOKEN=your_discord_bot_token_here
```

### Getting a Bot Token

1. Go to https://discord.com/developers/applications
2. Create a new application
3. Go to Bot tab, click "Reset Token", copy it
4. Enable **Message Content Intent**, **Server Members Intent** under Privileged Gateway Intents
5. Go to OAuth2 > URL Generator, select `bot` + `applications.commands` scopes
6. Select permissions: Send Messages, Connect, Speak, Embed Links, Read Message History, Use Slash Commands
7. Copy the generated URL and open it to invite the bot to your server

### Optional Configuration

| Variable | Description |
|----------|-------------|
| `SPOTIPY_CLIENT_ID` / `SPOTIPY_CLIENT_SECRET` | Enable Spotify playlist import (get from https://developer.spotify.com/dashboard) |
| `LAVALINK_HOST` / `LAVALINK_PORT` / `LAVALINK_PASSWORD` | Connect to a Lavalink server |
| `DATABASE_URL` | Use PostgreSQL: `postgresql+asyncpg://user:pass@localhost:5432/musicbot` |

---

## Step 3: Set Up the Database

### Option A: Auto-create (default)

The bot automatically creates SQLite tables on first run. No action needed.

### Option B: Use Alembic Migrations (recommended for production)

```bash
# Apply all migrations
alembic upgrade head

# If using PostgreSQL, update alembic.ini first:
# sqlalchemy.url = postgresql+asyncpg://user:pass@localhost:5432/musicbot
```

---

## Step 4: Run the Bot

```bash
python bot.py
```

The bot will:
1. Initialize the database
2. Probe Lavalink (fall back to FFmpeg if unavailable)
3. Auto-update yt-dlp (if `YTDLP_AUTO_UPDATE=true`)
4. Load all 7 cogs
5. Connect to Discord

---

## Running with Docker

```bash
# Build and start bot + Lavalink
docker compose up -d

# View logs
docker compose logs -f bot

# Stop
docker compose down
```

The `docker-compose.yml` includes:
- **bot** service — the Discord bot
- **lavalink** service — Lavalink 4 audio server with health check

Data is persisted in Docker volumes (`bot-data`, `bot-logs`).

---

## Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_repositories.py -v
pytest tests/test_models.py -v
pytest tests/test_queue.py -v
pytest tests/test_filters.py -v
pytest tests/test_permissions.py -v

# Run with short traceback
pytest --tb=short

# Run only a specific test class
pytest tests/test_repositories.py::TestPlaylistService -v

# Run only a specific test
pytest tests/test_repositories.py::TestPlaylistService::test_create_list_and_share_code -v
```

### Test Structure

| File | What it tests |
|------|---------------|
| `tests/test_repositories.py` | All database repository CRUD (24 tests) |
| `tests/test_models.py` | ORM relationships, cascades, constraints (4 tests) |
| `tests/test_queue.py` | Queue operations (add, remove, shuffle, loop) |
| `tests/test_filters.py` | FX preset system (combine, serialize, FFmpeg strings) |
| `tests/test_permissions.py` | Permission tier system |
| `tests/test_extractor.py` | yt-dlp extraction helpers |

---

## Linting & Formatting

```bash
# Check for lint errors
ruff check .

# Auto-fix fixable issues
ruff check . --fix

# Format code
ruff format .

# Check formatting without changing files
ruff format . --check
```

Ruff rules configured: E, F, I, N, W, UP, B, SIM, RUF (E501 ignored). Line length: 100 chars.

---

## Project Structure

```
spoty_discord_bot/
├── bot.py                  # Entry point — MusicBot class, event handlers
├── config.py               # Pydantic settings from .env
├── alembic.ini             # Alembic configuration
├── requirements.txt        # Python dependencies
├── Dockerfile              # Container image
├── docker-compose.yml      # Bot + Lavalink services
├── .env.example            # Config template
│
├── cogs/                   # Command modules (7 cogs)
│   ├── music.py            # play, pause, resume, stop, skip, seek, volume, nowplaying
│   ├── queue_cog.py        # queue, remove, clear, shuffle, loop, move
│   ├── fx.py               # setfx, clearfx, currenteffects, fxpreset (create/delete/builder)
│   ├── playlists.py        # playlist CRUD, import (YT/Spotify/share), like/dislike, copy, shuffle
│   ├── settings.py         # settings view/edit, prefix, DJ role, permissions
│   ├── utility.py          # help, ping, botinfo, lyrics, history, stats, musicquiz, ambience
│   └── dev.py              # Developer/owner-only commands (reload, sync, eval)
│
├── core/                   # Business logic
│   ├── audio_backends.py   # Lavalink + FFmpeg backend implementations
│   ├── backend_manager.py  # Probes Lavalink, manages fallback
│   ├── checks.py           # Permission check decorators (@is_dj, @is_admin, etc.)
│   ├── database.py         # Async SQLAlchemy engine & session factory
│   ├── errors.py           # Custom exception hierarchy
│   ├── extractor.py        # yt-dlp wrapper with TTL cache
│   ├── filters.py          # 12 built-in FX presets + FFmpeg/Lavalink translators
│   ├── models.py           # 8 SQLAlchemy ORM models
│   ├── permissions.py      # 4-tier permission system + per-command overrides
│   ├── player.py           # MusicPlayer — per-guild playback orchestrator
│   ├── queue.py            # MusicQueue — track queue with loop modes
│   ├── quiz.py             # MusicQuiz — text-based guess-the-song game
│   ├── repositories.py     # Data access layer (9 repo classes)
│   ├── track.py            # Track dataclass
│   └── ui/
│       ├── now_playing.py  # Now-playing embed with buttons
│       └── fx_builder.py   # Interactive FX preset builder (dropdown + modal)
│
├── alembic/                # Database migrations
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
│
├── tests/                  # Test suite
│   ├── conftest.py         # Fixtures (sample_track, in-memory DB)
│   ├── test_repositories.py
│   ├── test_models.py
│   ├── test_queue.py
│   ├── test_filters.py
│   ├── test_permissions.py
│   └── test_extractor.py
│
└── .github/workflows/
    └── ci.yml              # GitHub Actions: lint + test on push/PR
```

---

## Feature Overview (Phases 1-6)

### Phase 1-2: Core (already done before this implementation)
- Dual audio backend (Lavalink + FFmpeg fallback)
- Music playback, queue management, basic FX
- Playlist CRUD, settings, utility commands

### Phase 3: Playlist Advanced Features (implemented)
- `!playlist import <url/share_code>` — Import from YouTube, Spotify, or share code
- `!playlist like/dislike <name> <position>` — Vote on tracks
- `!playlist copy <source> <new_name>` — Copy playlists
- `!playlist shuffle <name>` — Permanently shuffle track order

### Phase 4: Interactive FX Builder (implemented)
- `!fxpreset builder` — Visual UI with dropdown + preview + save
- Validates against built-in and existing custom presets
- Combines multiple effects into one preset

### Phase 5: Permission Management (implemented)
- `!permissions view` — See all permission overrides
- `!permissions set <command> <role> allow/deny` — Override command access per role
- `!permissions remove/reset` — Remove overrides
- Integrates with existing DJ/Admin check system

### Phase 6: Entertainment (implemented)
- `!musicquiz` — 5-round guess-the-song game using server history + fuzzy matching
- `!ambience play <sound>` — 10 ambient sounds (rain, ocean, cafe, etc.)
- `!ambience list` / `!ambience stop`

### Phase 7: Infrastructure (implemented)
- Alembic initial migration
- Dockerfile + docker-compose.yml
- GitHub Actions CI (lint + test)
- README.md
- Expanded test suite (28 new tests)

---

## Troubleshooting

### Bot won't start
- Check `BOT_TOKEN` is set correctly in `.env`
- Ensure Python 3.11+ is installed: `python --version`
- Check logs in `logs/bot.log`

### No audio
- Verify FFmpeg is installed: `ffmpeg -version`
- If using Lavalink, check it's running: `curl http://localhost:8080/version`
- The bot auto-falls back to FFmpeg if Lavalink is unavailable

### Spotify import not working
- Set `SPOTIPY_CLIENT_ID` and `SPOTIPY_CLIENT_SECRET` in `.env`
- Get credentials from https://developer.spotify.com/dashboard

### Tests failing
- Make sure `pytest-asyncio` is installed: `pip install pytest-asyncio`
- Make sure `aiosqlite` is installed (needed for in-memory test DB)
- Run `pip install -r requirements.txt` to ensure all deps are present

### Database issues
- Delete `data/bot.db` to start fresh (SQLite)
- Run `alembic upgrade head` to apply migrations
- Check `DATABASE_URL` format in `.env`
