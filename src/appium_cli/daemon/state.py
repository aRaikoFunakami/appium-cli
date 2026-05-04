"""Process-local daemon state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from appium_cli.core.ref_resolver import RefResolver
from appium_cli.core.snapshot_generator import SnapshotGenerator


driver: Any | None = None
current_snapshot: Any | None = None
current_ref_map: dict[str, Any] = {}
tap_history: list[dict[str, Any]] = []
session_metadata: dict[str, Any] = {}
app_dir: Path | None = None

# Singleton instances
ref_resolver: RefResolver = RefResolver()
snapshot_generator: SnapshotGenerator = SnapshotGenerator()


def reset() -> None:
    global driver, current_snapshot, current_ref_map, tap_history, session_metadata, app_dir
    global ref_resolver, snapshot_generator
    driver = None
    current_snapshot = None
    current_ref_map = {}
    tap_history = []
    session_metadata = {}
    app_dir = None
    ref_resolver = RefResolver()
    snapshot_generator = SnapshotGenerator()
