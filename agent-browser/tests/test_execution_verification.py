"""Tests for executor effect verification."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent_browser.appium_tools import BrowserAgentContext, ToolExecutionResult
from agent_browser.config import AgentBrowserConfig
from agent_browser.controller.executor import Executor, snapshot_id_from_output
from agent_browser.controller.planner import PlannedAction
from agent_browser.memory import WorkingMemory
from agent_browser.world.model import RefView, Snapshot, WorldModel


def _ctx(tmp_path) -> BrowserAgentContext:
    cfg = AgentBrowserConfig(artifacts_dir=tmp_path / "artifacts", memory_path=tmp_path / "mem.jsonl")
    return BrowserAgentContext(config=cfg, memory=WorkingMemory(goal="test"))


def _snapshot(snapshot_id: str, y_offset: int = 0) -> Snapshot:
    return Snapshot(
        id=snapshot_id,
        screen_id=snapshot_id,
        context="NATIVE_APP",
        refs={
            "list": RefView(
                ref="list",
                role="list",
                bounds=(0, 100, 100, 400),
                scrollable=True,
                scroll_direction="vertical",
            ),
            "row": RefView(
                ref="row",
                role="row",
                bounds=(0, 120 + y_offset, 100, 160 + y_offset),
                parent_ref="list",
            ),
        },
        containers=["list"],
    )


def _result(name: str, output: str = "OK", ok: bool = True) -> ToolExecutionResult:
    return ToolExecutionResult(
        name=name,
        args_summary="{}",
        output=output,
        ok=ok,
        duration_ms=1.0,
    )


def test_snapshot_id_from_output() -> None:
    assert snapshot_id_from_output("snapshot_id: native-123\nartifacts: ...") == "native-123"
    assert snapshot_id_from_output("OK") is None


@pytest.mark.asyncio
async def test_scroll_with_movement_reports_effect_observed(tmp_path) -> None:
    snapshots = {
        "before": _snapshot("before"),
        "after": _snapshot("after", y_offset=-80),
    }
    action = PlannedAction(
        tool="scroll_up",
        args={"ref": "list", "percent": 0.8},
        rationale="test",
        expected_effect="ref_movement",
        verify_with="snapshot_diff",
    )
    executor = Executor(
        context=_ctx(tmp_path),
        world=WorldModel(),
        snapshot_loader=lambda snapshot_id: snapshots[snapshot_id],
    )

    with patch("agent_browser.controller.executor.execute_appium_tool", new=AsyncMock()) as mock_tool:
        mock_tool.side_effect = [
            _result("snapshot", "snapshot_id: before\n"),
            _result("scroll_up", "OK\ncan_scroll_more: true"),
            _result("snapshot", "snapshot_id: after\n"),
        ]
        outcome = await executor.execute(action)

    assert outcome.ok is True
    assert outcome.effect_observed is True
    assert outcome.before_snapshot_id == "before"
    assert outcome.after_snapshot_id == "after"
    assert "moved=1" in outcome.diff_summary


@pytest.mark.asyncio
async def test_scroll_without_movement_reports_no_effect(tmp_path) -> None:
    snapshots = {
        "before": _snapshot("before"),
        "after": _snapshot("after"),
    }
    action = PlannedAction(
        tool="scroll_up",
        args={"ref": "list", "percent": 0.8},
        rationale="test",
        expected_effect="ref_movement",
        verify_with="snapshot_diff",
    )
    executor = Executor(
        context=_ctx(tmp_path),
        world=WorldModel(),
        snapshot_loader=lambda snapshot_id: snapshots[snapshot_id],
    )

    with patch("agent_browser.controller.executor.execute_appium_tool", new=AsyncMock()) as mock_tool:
        mock_tool.side_effect = [
            _result("snapshot", "snapshot_id: before\n"),
            _result("scroll_up", "OK\ncan_scroll_more: true"),
            _result("snapshot", "snapshot_id: after\n"),
        ]
        outcome = await executor.execute(action)

    assert outcome.ok is False
    assert outcome.effect_observed is False
    assert outcome.error == "no visible movement detected"


@pytest.mark.asyncio
async def test_favorite_tap_without_visible_diff_defers_verification(tmp_path) -> None:
    snapshots = {
        "before": _snapshot("before"),
        "after": _snapshot("after"),
    }
    action = PlannedAction(
        tool="tap",
        args={"ref": "favoriteicon"},
        rationale="test",
        expected_effect="favorite_toggled",
        verify_with="ref_check",
    )
    executor = Executor(
        context=_ctx(tmp_path),
        world=WorldModel(),
        snapshot_loader=lambda snapshot_id: snapshots[snapshot_id],
    )

    with patch("agent_browser.controller.executor.execute_appium_tool", new=AsyncMock()) as mock_tool:
        mock_tool.side_effect = [
            _result("snapshot", "snapshot_id: before\n"),
            _result("tap", "OK"),
            _result("snapshot", "snapshot_id: after\n"),
        ]
        outcome = await executor.execute(action)

    assert outcome.ok is True
    assert outcome.effect_observed is True
    assert outcome.diff_summary == "favorite tap accepted; visible state verification deferred"
