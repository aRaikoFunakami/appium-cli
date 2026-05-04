"""Filesystem paths used by appium-cli."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def get_app_dir() -> Path:
    """Return the project-local .appium-cli directory (cwd-based)."""
    return Path.cwd() / ".appium-cli"


def ensure_app_dir() -> Path:
    d = get_app_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def server_state_path() -> Path:
    return get_app_dir() / "server.json"


def server_log_path() -> Path:
    return get_app_dir() / "server.log"


def session_socket_path() -> Path:
    return get_app_dir() / "session.sock"


def session_pid_path() -> Path:
    return get_app_dir() / "session.pid"


def current_session_path() -> Path:
    return get_app_dir() / "current-session"


def generate_session_id() -> str:
    """Generate a timestamp-based session id safe for filenames."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z"
    return f"session-{ts}"


def session_artifact_dir(session_id: str) -> Path:
    return get_app_dir() / session_id


def session_log_path(session_id: str) -> Path:
    return get_app_dir() / f"{session_id}.log"


def daemon_log_path(session_id: str) -> Path:
    return session_artifact_dir(session_id) / "daemon.log"


def screenshot_path(session_id: str) -> Path:
    """Generate a timestamped screenshot filename under the session artifact dir."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z"
    return session_artifact_dir(session_id) / f"screenshot-{ts}.png"


def read_current_session() -> str | None:
    """Read the current session id from the current-session file, or None."""
    p = current_session_path()
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def write_current_session(session_id: str) -> None:
    ensure_app_dir()
    current_session_path().write_text(session_id + "\n", encoding="utf-8")


def clear_current_session() -> None:
    current_session_path().unlink(missing_ok=True)
