# Spoty Discord Bot

A feature-rich Discord music bot with dual audio backend support, playlists, FX presets, and more.

## Features

- **Dual Audio Backend** — Lavalink (primary) with automatic FFmpeg fallback
- **Music Playback** — Play from YouTube, SoundCloud, Spotify, and direct URLs
- **Queue Management** — Add, remove, shuffle, loop, and reorder tracks
- **Playlists** — Private-by-default playlists with share codes, imports, copies, pagination, and voting
- **Audio Effects** — 12 built-in presets (nightcore, bassboost, 8D, etc.) + custom presets
- **Interactive FX Builder** — Visual UI for combining effects into custom presets
- **Permission System** — 4-tier (Owner/Admin/DJ/Everyone) with per-command role overrides
- **Music Quiz** — Guess-the-song minigame using server play history
- **Ambience Player** — 10 built-in ambient sound presets (rain, ocean, cafe, etc.)
- **Per-Guild Settings** — Custom prefix, DJ role, music channel lock, auto-DJ, and more

## Quick Start

### Docker (Recommended)

1. Copy `.env.example` to `.env` and fill in `BOT_TOKEN`
2. Run:
   ```bash
   docker compose up -d
   ```

### Manual

1. **Prerequisites:** Python 3.11+, FFmpeg
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and configure
4. Run:
   ```bash
   python bot.py
   ```

### Optional: Lavalink

For better audio quality and lower resource usage, set up a [Lavalink](https://github.com/lavalink-devs/Lavalink) server and configure the `LAVALINK_*` variables in `.env`.

## Configuration

All configuration is via environment variables or `.env` file. See `.env.example` for all options.

| Variable | Default | Description |
|----------|---------|-------------|
| `BOT_TOKEN` | *required* | Discord bot token |
| `BOT_PREFIX` | `!` | Default command prefix |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/bot.db` | Database URL (SQLite or PostgreSQL) |
| `LAVALINK_ENABLED` | `true` | Enable Lavalink backend |
| `LAVALINK_HOST` | `localhost` | Lavalink server host |
| `LAVALINK_PORT` | `8080` | Lavalink server port |
| `LAVALINK_PASSWORD` | `youshallnotpass` | Lavalink password |
| `SPOTIPY_CLIENT_ID` | | Spotify API client ID |
| `SPOTIPY_CLIENT_SECRET` | | Spotify API client secret |
| `YTDLP_COOKIES_FILE` | | Path to YouTube cookies file (for age-restricted content) |

## Commands

### Music
`play`, `pause`, `resume`, `stop`, `skip`, `seek`, `volume`, `nowplaying`

### Queue
`queue`, `remove`, `clear`, `shuffle`, `loop`, `move`

### Playlists
`playlist create`, `playlist delete`, `playlist add`, `playlist remove`, `playlist list`, `playlist view`, `playlist play`, `playlist share`, `playlist import`, `playlist copy`, `playlist shuffle`, `playlist like`, `playlist dislike`, `playlist rename`, `playlist info`

Playlists are private by default. Names are stored with spaces converted to underscores for prefix-command use. A share code allows other users to import or copy a playlist, but not edit it.

### Effects
`setfx`, `clearfx`, `currenteffects`, `fxpreset list`, `fxpreset create`, `fxpreset delete`, `fxpreset builder`

### Settings
`settings view`, `settings default_volume`, `prefix`, `set_dj_role`, `autoplay`, `lockqueue`

### Permissions
`permissions view`, `permissions set`, `permissions remove`, `permissions reset`

### Utility
`help`, `ping`, `botinfo`, `uptime`, `lyrics`, `history`, `stats`, `musicquiz`, `ambience`, `backend`

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint and format
ruff check .
ruff format .

# Database migrations
alembic upgrade head
```

## Packaged Builds

The packaged app uses a PyInstaller `onedir` launcher. It starts bundled Lavalink on
`127.0.0.1`, chooses the first free port from `8080` to `8090`, waits for Lavalink
health, then starts the bot with bundled FFmpeg.

### Windows

Builds produce an Inno Setup installer:

```powershell
$env:SPOTY_JRE_DIR="C:\path\to\jre"
$env:SPOTY_FFMPEG_DIR="C:\path\to\ffmpeg"
.\scripts\build-windows.ps1 -AppVersion 1.0.0
```

Output:

```text
release/windows/SpotySetup.exe
```

Installed app files live under `Program Files/Spoty`. User config, database, and logs live under:

```text
%APPDATA%/Spoty/
```

### Linux

Builds produce a portable tarball:

```bash
export SPOTY_JRE_DIR=/path/to/jre
export SPOTY_FFMPEG_DIR=/path/to/ffmpeg
APP_VERSION=1.0.0 bash ./scripts/build-linux.sh
```

Output:

```text
release/linux/SpotyDiscordBot-linux-x64.tar.gz
```

User config, database, and logs live under:

```text
~/.config/spoty/
```

### Packaged Runtime Overrides

| Variable | Description |
|----------|-------------|
| `SPOTY_USER_DIR` | Override the user data directory |
| `SPOTY_LAVALINK_DIR` | Override bundled Lavalink directory |
| `SPOTY_JAVA_BIN` | Override bundled Java executable |
| `SPOTY_FFMPEG_BIN` | Override bundled FFmpeg executable |
| `SPOTY_SKIP_LAVALINK=true` | Use an external Lavalink server instead of bundled Lavalink |

## License

MIT
