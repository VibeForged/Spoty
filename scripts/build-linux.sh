#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_VERSION="${APP_VERSION:-1.0.0}"
JRE_DIR="${SPOTY_JRE_DIR:-}"
FFMPEG_DIR="${SPOTY_FFMPEG_DIR:-}"
DIST_DIR="$ROOT/dist"
APP_DIR="$DIST_DIR/Spoty"
RELEASE_DIR="$ROOT/release/linux"

if [[ -z "$JRE_DIR" ]]; then
  echo "Set SPOTY_JRE_DIR to a Linux JRE directory." >&2
  exit 1
fi
if [[ -z "$FFMPEG_DIR" ]]; then
  echo "Set SPOTY_FFMPEG_DIR to a Linux FFmpeg directory." >&2
  exit 1
fi

mkdir -p "$RELEASE_DIR"

python -m pip install --upgrade pip
python -m pip install -r "$ROOT/requirements.txt"
python -m pip install pyinstaller ruff pytest pytest-asyncio

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  python -m ruff check "$ROOT"
  python -m pytest --tb=short
fi

rm -rf "$APP_DIR"

python -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name spoty \
  --collect-submodules core \
  --collect-submodules cogs \
  --hidden-import aiosqlite \
  --add-data "$ROOT/.env.example:." \
  --add-data "$ROOT/LavaLink:Lavalink" \
  --add-data "$ROOT/alembic:alembic" \
  "$ROOT/launcher.py"

if [ $? -ne 0 ]; then
  echo "PyInstaller failed!" >&2
  exit 1
fi

mv "$DIST_DIR/spoty" "$APP_DIR"
mkdir -p "$APP_DIR/runtime"
cp -R "$JRE_DIR" "$APP_DIR/runtime/jre"
cp -R "$FFMPEG_DIR" "$APP_DIR/runtime/ffmpeg"
cp "$ROOT/README.md" "$APP_DIR/README.md"
cp "$ROOT/LICENSE" "$APP_DIR/LICENSE"

cat > "$APP_DIR/version.json" <<JSON
{
  "bot_version": "$APP_VERSION",
  "lavalink_version": "bundled",
  "java_runtime": "bundled",
  "ffmpeg": "bundled",
  "build_platform": "linux-x64",
  "build_time_utc": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
JSON

chmod +x "$APP_DIR/spoty"
tar -C "$DIST_DIR" -czf "$RELEASE_DIR/SpotyDiscordBot-linux-x64.tar.gz" Spoty

echo "Linux app directory: $APP_DIR"
echo "Linux tarball: $RELEASE_DIR/SpotyDiscordBot-linux-x64.tar.gz"

