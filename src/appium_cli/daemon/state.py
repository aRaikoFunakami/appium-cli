"""Process-local daemon state.

current_snapshot holds either a NativeSnapshot or WebSnapshot instance — both
expose a tree-first API (find_ref, find_text, describe_ref, to_text, to_ref_map).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from appium_cli.core.ref_resolver import RefResolver


driver: Any | None = None
current_snapshot: Any | None = None
current_ref_map: dict[str, Any] = {}
tap_history: list[dict[str, Any]] = []
session_metadata: dict[str, Any] = {}
app_dir: Path | None = None

# Context tracking
current_context: str = "NATIVE_APP"
snapshots_by_context: dict[str, Any] = {}
ref_maps_by_context: dict[str, dict[str, Any]] = {}

# Singleton instances
ref_resolver: RefResolver = RefResolver()


def reset() -> None:
    global driver, current_snapshot, current_ref_map, tap_history, session_metadata, app_dir
    global current_context, snapshots_by_context, ref_maps_by_context
    global ref_resolver
    driver = None
    current_snapshot = None
    current_ref_map = {}
    tap_history = []
    session_metadata = {}
    app_dir = None
    current_context = "NATIVE_APP"
    snapshots_by_context = {}
    ref_maps_by_context = {}
    ref_resolver = RefResolver()
