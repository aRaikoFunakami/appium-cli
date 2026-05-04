"""Process-local daemon state."""

from __future__ import annotations

from pathlib import Path
from typing import Any


driver: Any | None = None
current_snapshot: Any | None = None
current_ref_map: dict[str, Any] = {}
tap_history: list[dict[str, Any]] = []
session_metadata: dict[str, Any] = {}
app_dir: Path | None = None


def reset() -> None:
    global driver, current_snapshot, current_ref_map, tap_history, session_metadata, app_dir
    driver = None
    current_snapshot = None
    current_ref_map = {}
    tap_history = []
    session_metadata = {}
    app_dir = None
