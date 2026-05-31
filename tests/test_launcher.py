"""Tests for packaged launcher helpers."""

from __future__ import annotations

import socket
import uuid
import shutil
from pathlib import Path

import launcher


def _workspace_tmp_dir() -> Path:
    path = Path(".pytest_tmp_launcher") / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=False)
    return path.resolve()


def test_user_data_dir_windows_uses_appdata():
    result = launcher.user_data_dir(
        env={"APPDATA": r"C:\Users\Test\AppData\Roaming"},
        platform_name="win32",
    )

    assert result == Path(r"C:\Users\Test\AppData\Roaming") / "Spoty"


def test_user_data_dir_linux_uses_config_home(monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: Path("/home/test"))

    result = launcher.user_data_dir(env={}, platform_name="linux")

    assert result == Path("/home/test/.config/spoty")


def test_user_data_dir_honors_override():
    result = launcher.user_data_dir(env={"SPOTY_USER_DIR": "/tmp/custom"}, platform_name="linux")

    assert result == Path("/tmp/custom")


def test_bundled_data_dir_prefers_pyinstaller_meipass(monkeypatch):
    monkeypatch.setattr(launcher.sys, "_MEIPASS", "/tmp/spoty/_internal", raising=False)

    result = launcher.bundled_data_dir(Path("/opt/spoty"))

    assert result == Path("/tmp/spoty/_internal").resolve()


def test_bundled_data_dir_uses_internal_dir():
    root = _workspace_tmp_dir()
    try:
        internal_dir = root / "_internal"
        internal_dir.mkdir()

        result = launcher.bundled_data_dir(root)

        assert result == internal_dir
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_lavalink_dir_finds_pyinstaller_internal_data():
    root = _workspace_tmp_dir()
    try:
        internal_lavalink = root / "_internal" / "Lavalink"
        internal_lavalink.mkdir(parents=True)
        (internal_lavalink / "Lavalink.jar").touch()

        result = launcher.lavalink_dir(root)

        assert result == internal_lavalink
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_select_lavalink_port_skips_occupied_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((launcher.HOST, 0))
        occupied_port = sock.getsockname()[1]

        selected = launcher.select_lavalink_port(range(occupied_port, occupied_port + 2))

    assert selected == occupied_port + 1


def test_build_child_env_sets_packaged_defaults(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LOG_FILE", raising=False)
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.delenv("SPOTY_ENV_FILE", raising=False)

    base_dir = Path("/opt/spoty")
    data_dir = Path("/home/test/.config/spoty")

    env = launcher.build_child_env(base_dir, data_dir, 8081)

    assert env["SPOTY_CHILD_BOT"] == "1"
    assert env["SPOTY_ENV_FILE"] == str(data_dir / ".env")
    assert env["DATABASE_URL"] == f"sqlite+aiosqlite:///{(data_dir / 'bot.db').as_posix()}"
    assert env["LOG_FILE"] == str(data_dir / "logs" / "bot.log")
    assert env["LAVALINK_HOST"] == "127.0.0.1"
    assert env["LAVALINK_PORT"] == "8081"
    executable = "ffmpeg.exe" if launcher.sys.platform.startswith("win") else "ffmpeg"
    assert env["FFMPEG_PATH"] == str(base_dir / "runtime" / "ffmpeg" / "bin" / executable)


def test_runtime_helpers_support_flat_executable_layout():
    root = _workspace_tmp_dir()
    java_executable = "java.exe" if launcher.sys.platform.startswith("win") else "java"
    ffmpeg_executable = "ffmpeg.exe" if launcher.sys.platform.startswith("win") else "ffmpeg"
    try:
        java_path = root / "runtime" / "jre" / java_executable
        ffmpeg_path = root / "runtime" / "ffmpeg" / ffmpeg_executable
        java_path.parent.mkdir(parents=True)
        ffmpeg_path.parent.mkdir(parents=True)
        java_path.touch()
        ffmpeg_path.touch()

        assert launcher.java_bin(root) == java_path
        assert launcher.ffmpeg_bin(root) == ffmpeg_path
    finally:
        shutil.rmtree(root, ignore_errors=True)
