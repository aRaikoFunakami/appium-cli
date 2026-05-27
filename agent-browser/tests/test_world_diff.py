"""Tests for lightweight snapshot diffing."""

from __future__ import annotations

from pathlib import Path

from agent_browser.world import load_snapshot
from agent_browser.world.diff import diff_snapshots


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "twine4car"


def test_identical_snapshot_has_no_changes() -> None:
    before = load_snapshot(FIXTURE_DIR / "movie_tab_before_scroll")
    after = load_snapshot(FIXTURE_DIR / "movie_tab_before_scroll")

    diff = diff_snapshots(before, after)

    assert diff.has_changes is False
    assert diff.added_refs == []
    assert diff.removed_refs == []
    assert diff.moved_refs == []
