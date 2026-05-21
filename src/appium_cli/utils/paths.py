"""Filesystem paths used by appium-cli."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_RUNTIME_DIR_ENV = "APPIUM_CLI_RUNTIME_DIR"
_RUNTIME_DIR_PREFIX = ".appium-cli-"
_RUNTIME_DIR_HASH_LEN = 12


def get_app_dir() -> Path:
    """Return the project-local .appium-cli directory (cwd-based)."""
    return Path.cwd() / ".appium-cli"


def ensure_app_dir() -> Path:
    d = get_app_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_runtime_dir() -> Path:
    """Return the tmp-backed runtime directory for Unix sockets and PID files.

    Unix domain socket operations (``bind``, ``unlink``, ``stat``) can fail on
    filesystems such as virtiofs used by Docker Desktop devcontainers, even when
    regular file IO succeeds. Persistent artifacts stay in the workspace-local
    ``.appium-cli/`` directory; only the runtime coordination files live here.

    The directory is per-workspace by hashing the resolved cwd, so multiple
    devcontainers sharing ``/tmp`` do not collide. ``APPIUM_CLI_RUNTIME_DIR``
    overrides the location for tests and unusual deployments.
    """
    override = os.environ.get(_RUNTIME_DIR_ENV)
    if override:
        return Path(override)
    cwd_repr = str(Path.cwd().resolve()).encode("utf-8")
    digest = hashlib.sha256(cwd_repr).hexdigest()[:_RUNTIME_DIR_HASH_LEN]
    return Path("/tmp") / f"{_RUNTIME_DIR_PREFIX}{digest}"


def ensure_runtime_dir() -> Path:
    d = get_runtime_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def server_state_path() -> Path:
    return get_app_dir() / "server.json"


def server_log_path() -> Path:
    return get_app_dir() / "server.log"


def session_socket_path() -> Path:
    return get_runtime_dir() / "session.sock"


def session_pid_path() -> Path:
    return get_runtime_dir() / "session.pid"


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


def _timestamp_for_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z"


def _sanitize_filename_part(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    sanitized = sanitized.strip("._-")
    return sanitized or "unknown"


def generate_snapshot_id(source: str, screen_id: str | None = None) -> str:
    """Generate a timestamped snapshot id safe for filenames."""
    parts = [_sanitize_filename_part(source), _timestamp_for_filename()]
    if screen_id:
        parts.append(_sanitize_filename_part(screen_id))
    return "-".join(parts)


def snapshot_artifact_dir() -> Path:
    """Return the shared snapshot artifact directory."""
    return get_app_dir() / "snapshots"


def ensure_snapshot_artifact_dir() -> Path:
    d = snapshot_artifact_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


_SNAPSHOT_ARTIFACT_SUFFIXES = {
    "meta": ".meta.json",
    "compact": ".compact.yml",
    "full": ".full.yml",
    "refs": ".refs.json",
    "index": ".index.json",
}


def snapshot_artifact_path(snapshot_id: str, artifact: str) -> Path:
    """Return the path for one artifact in a snapshot bundle."""
    try:
        suffix = _SNAPSHOT_ARTIFACT_SUFFIXES[artifact]
    except KeyError as exc:
        valid = ", ".join(sorted(_SNAPSHOT_ARTIFACT_SUFFIXES))
        raise ValueError(f"Unknown snapshot artifact '{artifact}'. Expected one of: {valid}") from exc
    return snapshot_artifact_dir() / f"{_sanitize_filename_part(snapshot_id)}{suffix}"


def snapshot_bundle_paths(snapshot_id: str) -> dict[str, Path]:
    """Return all standard artifact paths for a snapshot bundle."""
    return {
        artifact: snapshot_artifact_path(snapshot_id, artifact)
        for artifact in _SNAPSHOT_ARTIFACT_SUFFIXES
    }


def latest_snapshot_path(source: str | None = None, context: str | None = None) -> Path:
    """Return the latest snapshot pointer path.

    Without arguments this is the global latest pointer. With source/context it
    is scoped, for example ``latest-native.json`` or
    ``latest-web-WEBVIEW_chrome.json``.
    """
    if not source and not context:
        return snapshot_artifact_dir() / "latest.json"

    parts = []
    if source:
        parts.append(_sanitize_filename_part(source))
    if context:
        sanitized_context = _sanitize_filename_part(context)
        if sanitized_context not in parts:
            parts.append(sanitized_context)
    return snapshot_artifact_dir() / f"latest-{'-'.join(parts)}.json"


def write_json_artifact(path: Path, data: dict[str, Any]) -> None:
    """Write JSON artifact data with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_text_artifact(path: Path, content: str) -> None:
    """Write a UTF-8 text artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_latest_snapshot_pointer(
    metadata: dict[str, Any],
    *,
    source: str | None = None,
    context: str | None = None,
) -> None:
    """Write global and optionally scoped latest snapshot pointer metadata."""
    write_json_artifact(latest_snapshot_path(), metadata)
    if source or context:
        write_json_artifact(latest_snapshot_path(source=source, context=context), metadata)


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
