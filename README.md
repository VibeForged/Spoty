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
| `YOUTUBE_POT_AUTOREFRESH` | `true` | Auto-generate & push a YouTube PO token to Lavalink (servers) |
| `YOUTUBE_POT_REFRESH_HOURS` | `6` | How often the PO-token sidecar refreshes |
| `YOUTUBE_OAUTH_ENABLED` | `false` | Opt-in YouTube OAuth (use a throwaway account) |

## YouTube on servers / datacenter IPs

On a home/residential IP, YouTube playback works out of the box. On **servers,
VPS, cloud, or Hugging Face Spaces**, YouTube blocks anonymous requests from
datacenter IPs with *"Sign in to confirm you're not a bot."* This is an
IP-reputation block, not a bug.

The Docker image handles this automatically: it runs bundled Lavalink plus a
small **PO-token sidecar** ([scripts/potoken_refresher.mjs](scripts/potoken_refresher.mjs))
that generates a Proof-of-Origin token (browserless, no login) and pushes it to
Lavalink's `youtube-source` plugin every few hours. No configuration needed —
`YOUTUBE_POT_AUTOREFRESH=true` is the default.

A PO token is not bulletproof on heavily-flagged IPs. The strongest free fix is
**opt-in OAuth with a throwaway Google account** (never your personal one):

1. Set `YOUTUBE_OAUTH_ENABLED=true` and restart.
2. Lavalink logs a Google device-code URL — open it and authorize the burner account.
3. Lavalink logs a refresh token — set `YOUTUBE_OAUTH_REFRESH_TOKEN` and
   `YOUTUBE_OAUTH_SKIP_INIT=true`, then restart.

See `.env.example` for all related variables.

## Commands

### Music
`play`, `search`, `playnext`, `previous`, `pause`, `resume`, `stop`, `skip`, `seek`, `forward`, `rewind`, `volume`, `nowplaying`, `sleeptimer`, `join`, `leave`, `replay`, `jump`, `panel`

`search` shows the top results in a dropdown so you can pick the right one; `sleeptimer <minutes>` stops playback after a delay (0 cancels).

`skip` is instant for DJs/admins; if a server sets a vote threshold, other listeners vote to skip.

### Queue
`queue`, `queuesearch`, `remove`, `clear`, `dedupe`, `shuffle`, `loop`, `move`, `grab`

### Auto-DJ
`autodj start`, `autodj stop`, `autodj status`, `autodj skip`, `autodj reset`, `autodj signals`

### Playlists
`playlist create`, `playlist save`, `playlist delete`, `playlist add`, `playlist remove`, `playlist list`, `playlist view`, `playlist play`, `playlist share`, `playlist import`, `playlist copy`, `playlist shuffle`, `playlist like`, `playlist dislike`, `playlist rename`, `playlist info`

`playlist save` snapshots the current queue into a new playlist.

Playlists are private by default. Names are stored with spaces converted to underscores for prefix-command use. A share code allows other users to import or copy a playlist, but not edit it.

### Effects
`setfx`, `clearfx`, `currenteffects`, `fxpreset list`, `fxpreset create`, `fxpreset delete`, `fxpreset rename`, `fxpreset builder`

### Settings
`settings view`, `settings default_volume`, `settings announce_songs`, `settings interactive_buttons`, `settings set_music_channel`, `settings 247`, `settings skip_vote`, `settings lone_user_dj`, `settings queue_limit`, `settings default_fx`, `setup`, `prefix`, `set_dj_role`, `lockqueue`

### Permissions
`permissions view`, `permissions set`, `permissions remove`, `permissions reset`

### Utility
`help`, `ping`, `botinfo`, `uptime`, `lyrics`, `history`, `stats`, `leaderboard`, `musicquiz`, `ambience`, `backend`, `feedback`, `voiceregion`

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
