"""Filesystem paths used by appium-cli."""

from __future__ import annotations

from pathlib import Path


APP_DIR = Path.home() / ".appium-cli"
SERVER_STATE_PATH = APP_DIR / "server.json"
SERVER_LOG_PATH = APP_DIR / "server.log"
SESSION_SOCKET_PATH = APP_DIR / "session.sock"
SESSION_PID_PATH = APP_DIR / "session.pid"


def ensure_app_dir() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR
