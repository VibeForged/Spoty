"""Packaged application launcher for Spoty Discord Bot.

The launcher owns the bundled Lavalink process, chooses a safe local port,
sets packaged runtime defaults, and starts the bot as a child process.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

APP_NAME = "Spoty"
HOST = "127.0.0.1"
PORT_RANGE = range(8080, 8091)
HEALTH_TIMEOUT_SECONDS = 45
WATCHDOG_INTERVAL_SECONDS = 2
LAVALINK_PASSWORD = "youshallnotpass"


def is_frozen() -> bool:
    """Return whether the app is running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def app_base_dir() -> Path:
    """Return the install/source directory that contains bundled assets."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundled_data_dir(base_dir: Path) -> Path:
    """Return the directory where PyInstaller stores bundled data files."""
    pyinstaller_dir = getattr(sys, "_MEIPASS", None)
    if pyinstaller_dir:
        return Path(pyinstaller_dir).resolve()

    internal_dir = base_dir / "_internal"
    if internal_dir.exists():
        return internal_dir

    return base_dir


def user_data_dir(env: dict[str, str] | None = None, platform_name: str | None = None) -> Path:
    """Return the platform user-data directory for mutable app files."""
    env = env or os.environ
    override = env.get("SPOTY_USER_DIR")
    if override:
        return Path(override).expanduser()

    platform_name = platform_name or sys.platform
    if platform_name.startswith("win"):
        appdata = env.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME

    return Path.home() / ".config" / "spoty"


def runtime_executable(base_dir: Path, env_name: str, relative_parts: tuple[str, ...]) -> Path:
    """Resolve a bundled runtime executable with an environment override."""
    override = os.environ.get(env_name)
    if override:
        return Path(override).expanduser()
    return base_dir.joinpath(*relative_parts)


def lavalink_dir(base_dir: Path) -> Path:
    """Resolve the bundled Lavalink directory with an environment override."""
    override = os.environ.get("SPOTY_LAVALINK_DIR")
    if override:
        return Path(override).expanduser()

    for root in (base_dir, bundled_data_dir(base_dir)):
        for dirname in ("Lavalink", "LavaLink"):
            candidate = root / dirname
            if (candidate / "Lavalink.jar").exists():
                return candidate

    return bundled_data_dir(base_dir) / "Lavalink"


def java_bin(base_dir: Path) -> Path:
    """Return the bundled Java executable path."""
    executable = "java.exe" if sys.platform.startswith("win") else "java"
    configured = runtime_executable(
        base_dir, "SPOTY_JAVA_BIN", ("runtime", "jre", "bin", executable)
    )
    if configured.exists() or os.environ.get("SPOTY_JAVA_BIN"):
        return configured

    fallback = base_dir / "runtime" / "jre" / executable
    if fallback.exists():
        return fallback

    return configured


def ffmpeg_bin(base_dir: Path) -> Path:
    """Return the bundled FFmpeg executable path."""
    executable = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    configured = runtime_executable(
        base_dir, "SPOTY_FFMPEG_BIN", ("runtime", "ffmpeg", "bin", executable)
    )
    if configured.exists() or os.environ.get("SPOTY_FFMPEG_BIN"):
        return configured

    fallback = base_dir / "runtime" / "ffmpeg" / executable
    if fallback.exists():
        return fallback

    return configured


def is_truthy(value: str | None) -> bool:
    """Return whether an environment-style value means true."""
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_port_free(port: int, host: str = HOST) -> bool:
    """Return whether a TCP port can be bound locally."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def select_lavalink_port(ports: range = PORT_RANGE) -> int:
    """Select the first available Lavalink port."""
    for port in ports:
        if is_port_free(port):
            return port
    first = ports.start
    last = ports.stop - 1
    raise RuntimeError(f"No available Lavalink port in range {first}-{last}")


def wait_for_lavalink(
    port: int, password: str, timeout_seconds: int = HEALTH_TIMEOUT_SECONDS
) -> None:
    """Wait until Lavalink responds to an authenticated health request."""
    deadline = time.monotonic() + timeout_seconds
    headers = {
        "Authorization": password,
        "User-Id": "0",
        "Client-Name": "Spoty-Launcher/1.0",
    }
    urls = [
        f"http://{HOST}:{port}/version",
        f"http://{HOST}:{port}/v4/info",
    ]

    while time.monotonic() < deadline:
        for url in urls:
            request = Request(url, headers=headers)
            try:
                with urlopen(request, timeout=2) as response:
                    if response.status < 500:
                        return
            except URLError:
                pass
            except TimeoutError:
                pass
        time.sleep(1)

    raise TimeoutError(f"Lavalink did not become healthy on {HOST}:{port}")


def copy_env_example(base_dir: Path, data_dir: Path) -> None:
    """Place a config template in the user data directory without creating secrets."""
    source = bundled_data_dir(base_dir) / ".env.example"
    target_dir = base_dir if is_frozen() else data_dir
    target = target_dir / ".env.example"
    if source.exists() and not target.exists():
        shutil.copy2(source, target)


def ensure_root_env_file(base_dir: Path) -> None:
    """For packaged builds, expose editable .env in the app root."""
    if not is_frozen():
        return

    env_example = base_dir / ".env.example"
    env_file = base_dir / ".env"
    if env_example.exists() and not env_file.exists():
        shutil.copy2(env_example, env_file)


def _read_env_value(env_path: Path, key: str) -> str | None:
    """Read a single KEY=value from a dotenv-style file."""
    if not env_path.exists():
        return None

    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            lhs, rhs = line.split("=", 1)
            if lhs.strip().upper() != key.upper():
                continue
            return rhs.strip().strip("'\"")
    except OSError:
        return None

    return None


def ensure_required_config(data_dir: Path) -> None:
    """Fail early with a clear message when required config is missing."""
    if os.environ.get("BOT_TOKEN"):
        return

    default_env_path = app_base_dir() / ".env" if is_frozen() else data_dir / ".env"
    env_path = Path(os.environ.get("SPOTY_ENV_FILE", default_env_path))
    token = _read_env_value(env_path, "BOT_TOKEN")
    if token and token != "your_discord_bot_token_here":
        return

    raise RuntimeError(
        "BOT_TOKEN is not configured. Set BOT_TOKEN in your environment or create "
        f"'{env_path}' with BOT_TOKEN=<your token>. A template is available at "
        f"'{(app_base_dir() if is_frozen() else data_dir) / '.env.example'}'."
    )


def prepare_user_data(base_dir: Path, data_dir: Path) -> None:
    """Create user-data directories needed by the packaged app."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)
    copy_env_example(base_dir, data_dir)
    ensure_root_env_file(base_dir)


def build_child_env(base_dir: Path, data_dir: Path, port: int | None) -> dict[str, str]:
    """Build environment variables for the bot child process."""
    env = os.environ.copy()
    env["SPOTY_CHILD_BOT"] = "1"
    default_env_path = base_dir / ".env" if is_frozen() else data_dir / ".env"
    env.setdefault("SPOTY_ENV_FILE", str(default_env_path))
    env.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(data_dir / 'bot.db').as_posix()}")
    env.setdefault("LOG_FILE", str(data_dir / "logs" / "bot.log"))
    env.setdefault("FFMPEG_PATH", str(ffmpeg_bin(base_dir)))

    if port is not None:
        env["LAVALINK_ENABLED"] = "true"
        env["LAVALINK_HOST"] = HOST
        env["LAVALINK_PORT"] = str(port)
        env.setdefault("LAVALINK_PASSWORD", LAVALINK_PASSWORD)
        env["LAVALINK_SECURE"] = "false"

    return env


def bot_command() -> list[str]:
    """Return the command used to launch the bot child process."""
    if is_frozen():
        return [str(Path(sys.executable).resolve())]
    return [sys.executable, str(Path(__file__).resolve())]


def start_lavalink(base_dir: Path, port: int, password: str) -> subprocess.Popen:
    """Start bundled Lavalink on the selected local port."""
    ll_dir = lavalink_dir(base_dir)
    jar_path = ll_dir / "Lavalink.jar"
    if not jar_path.exists():
        raise FileNotFoundError(f"Lavalink jar not found: {jar_path}")

    java_path = java_bin(base_dir)
    if not java_path.exists():
        raise FileNotFoundError(f"Bundled Java not found: {java_path}")

    command = [
        str(java_path),
        "-jar",
        str(jar_path),
        f"--server.address={HOST}",
        f"--server.port={port}",
        f"--lavalink.server.password={password}",
    ]
    return subprocess.Popen(command, cwd=ll_dir)


def start_potoken_refresher(base_dir: Path, port: int, password: str) -> subprocess.Popen | None:
    """Start the Node PO-token refresher that pushes fresh tokens to Lavalink.

    This generates a YouTube Proof-of-Origin token (browserless) and POSTs it to
    Lavalink's youtube-source `/youtube` endpoint so playback works from
    datacenter/server IPs without a login.

    Non-fatal: returns None (with a warning) if disabled via env, if the script
    is missing, or if Node is not installed (e.g. the Windows packaged build).
    """
    if not is_truthy(os.environ.get("YOUTUBE_POT_AUTOREFRESH", "true")):
        print("PO-token auto-refresh disabled (YOUTUBE_POT_AUTOREFRESH).", flush=True)
        return None

    script = base_dir / "scripts" / "potoken_refresher.mjs"
    if not script.exists():
        print(f"PO-token refresher script not found at {script}; skipping.", flush=True)
        return None

    env = os.environ.copy()
    env["LAVALINK_HOST"] = HOST
    env["LAVALINK_PORT"] = str(port)
    env["LAVALINK_PASSWORD"] = password

    try:
        process = subprocess.Popen(["node", str(script)], env=env)
        print("Started PO-token refresher sidecar.", flush=True)
        return process
    except (FileNotFoundError, OSError) as exc:
        print(f"Could not start PO-token refresher (Node missing?): {exc}", flush=True)
        return None


def stop_process(process: subprocess.Popen, timeout_seconds: int = 10) -> None:
    """Terminate a child process gracefully, then force-kill if needed."""
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_seconds)


def load_version_info(base_dir: Path) -> dict[str, object]:
    """Load optional packaged version metadata."""
    path = base_dir / "version.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def print_startup_summary(base_dir: Path, data_dir: Path, port: int | None) -> None:
    """Print concise startup metadata for support diagnostics."""
    version_info = load_version_info(base_dir)
    print(f"Spoty launcher starting from: {base_dir}", flush=True)
    print(f"User data directory: {data_dir}", flush=True)
    print(f"Lavalink port: {port if port is not None else 'external/disabled'}", flush=True)
    if version_info:
        print(f"Version metadata: {json.dumps(version_info, sort_keys=True)}", flush=True)


def run_bot_child() -> int:
    """Run the bot in child mode."""
    from bot import main

    main()
    return 0


def run_launcher() -> int:
    """Run the packaged launcher."""
    base_dir = app_base_dir()
    data_dir = user_data_dir()
    prepare_user_data(base_dir, data_dir)
    ensure_required_config(data_dir)

    skip_lavalink = is_truthy(os.environ.get("SPOTY_SKIP_LAVALINK"))
    port = None if skip_lavalink else select_lavalink_port()
    lavalink_process = None
    refresher_process = None
    bot_process = None

    print_startup_summary(base_dir, data_dir, port)

    try:
        if port is not None:
            password = os.environ.get("LAVALINK_PASSWORD", LAVALINK_PASSWORD)
            lavalink_process = start_lavalink(base_dir, port, password)
            wait_for_lavalink(port, password)
            refresher_process = start_potoken_refresher(base_dir, port, password)

        env = build_child_env(base_dir, data_dir, port)
        bot_process = subprocess.Popen(bot_command(), env=env)

        while True:
            bot_return_code = bot_process.poll()
            if bot_return_code is not None:
                return int(bot_return_code)

            if lavalink_process is not None and lavalink_process.poll() is not None:
                print("Lavalink exited unexpectedly; stopping bot.", flush=True)
                stop_process(bot_process)
                return int(lavalink_process.returncode or 1)

            time.sleep(WATCHDOG_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        return 130
    finally:
        if bot_process is not None:
            stop_process(bot_process)
        if refresher_process is not None:
            stop_process(refresher_process)
        if lavalink_process is not None:
            stop_process(lavalink_process)


def main() -> int:
    """CLI entrypoint."""
    if is_truthy(os.environ.get("SPOTY_CHILD_BOT")):
        return run_bot_child()
    return run_launcher()


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        signal.signal(signal.SIGTERM, lambda _sig, _frame: sys.exit(143))
    raise SystemExit(main())
