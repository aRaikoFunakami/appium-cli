"""Structured controller regression tests for the Twine4Car prompt."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agent_browser.appium_tools import BrowserAgentContext, ToolExecutionResult
from agent_browser.config import AgentBrowserConfig
from agent_browser.controller.controller import run_structured_controller
from agent_browser.controller.executor import ActionOutcome
from agent_browser.memory import WorkingMemory
from agent_browser.world import load_snapshot
from agent_browser.world.model import Snapshot, TextTarget


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "twine4car"


@pytest.mark.asyncio
async def test_twine4car_structured_controller_scrolls_before_tapping_favorite(tmp_path) -> None:
    goal = (ROOT / "prompts" / "t4c.txt").read_text(encoding="utf-8")
    snapshot = load_snapshot(FIXTURE_DIR / "movie_tab_before_scroll")
    favorites_snapshot = Snapshot(
        id="favorites",
        screen_id="favorites",
        context="NATIVE_APP",
        refs={},
        text_targets=[
            TextTarget(text="ホーム"),
            TextTarget(text="映画"),
            TextTarget(text="お気に入り"),
            TextTarget(text="もっと表示する"),
            TextTarget(text="ソニック × シャドウ TOKYO MISSION"),
        ],
    )
    actions: list[tuple[str, dict[str, object]]] = []

    class FakeExecutor:
        def __init__(self, context, world):
            self.context = context
            self.world = world

        async def observe(self):
            self.world.update(snapshot)
            return ToolExecutionResult(
                name="snapshot",
                args_summary="{}",
                output=f"snapshot_id: {snapshot.id}\n",
                ok=True,
                duration_ms=1.0,
            )

        async def execute(self, action):
            actions.append((action.tool, dict(action.args)))
            if action.tool == "tap" and action.args.get("ref") == "tabbackground_6":
                self.world.update(favorites_snapshot)
            return ActionOutcome(
                action=action,
                ok=True,
                raw_text="OK",
                before_snapshot_id=snapshot.id,
                after_snapshot_id=snapshot.id,
                effect_observed=True,
                diff_summary=f"{action.tool} ok",
                duration_ms=1.0,
            )

    cfg = AgentBrowserConfig(
        controller="structured",
        artifacts_dir=tmp_path / "artifacts",
        memory_path=tmp_path / "memory.jsonl",
    )
    context = BrowserAgentContext(config=cfg, memory=WorkingMemory(goal=goal))

    with patch("agent_browser.controller.controller.Executor", FakeExecutor):
        result = await run_structured_controller(goal, cfg, context)

    assert result.success is True
    assert ("scroll_up", {"ref": "movies_section_scroll_view", "percent": 0.8}) in actions
    assert ("tap", {"ref": "iv_favorite_icon"}) in actions
    assert actions.index(("scroll_up", {"ref": "movies_section_scroll_view", "percent": 0.8})) < actions.index(
        ("tap", {"ref": "iv_favorite_icon"})
    )
    assert result.verification_passed is True
    assert result.billing is not None
    assert result.billing.api_calls == 0
    assert result.billing.total_tokens == 0
