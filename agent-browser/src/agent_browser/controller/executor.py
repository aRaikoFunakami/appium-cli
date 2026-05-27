"""Executor wrapper around appium-cli tools with effect verification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from agent_browser.appium_tools import BrowserAgentContext, ToolExecutionResult, execute_appium_tool
from agent_browser.controller.effects import verify_effect
from agent_browser.controller.planner import PlannedAction
from agent_browser.world.artifacts import load_snapshot
from agent_browser.world.model import Snapshot, WorldModel


SnapshotLoader = Callable[[str], Snapshot]


@dataclass(slots=True)
class ActionOutcome:
    """Result of executing and verifying one planned action."""

    action: PlannedAction
    ok: bool
    raw_text: str
    before_snapshot_id: str | None
    after_snapshot_id: str | None
    effect_observed: bool
    diff_summary: str
    duration_ms: float
    error: str | None = None


@dataclass(slots=True)
class Executor:
    """Executes actions through appium-cli and updates WorldModel snapshots."""

    context: BrowserAgentContext
    world: WorldModel
    snapshots_dir: Path = Path(".appium-cli/snapshots")
    snapshot_loader: SnapshotLoader | None = None

    async def observe(self) -> ToolExecutionResult:
        """Take a native snapshot and update the world model when artifacts exist."""
        result = await execute_appium_tool("snapshot", {"scope": "full", "context": "native", "boxes": False}, self.context)
        if result.ok:
            snapshot_id = snapshot_id_from_output(result.output)
            if snapshot_id:
                self.world.update(self._load_snapshot(snapshot_id))
        return result

    async def execute(self, action: PlannedAction) -> ActionOutcome:
        """Execute an action and verify its effect when required."""
        before = self.world.current()
        if before is None and action.verify_with != "none":
            await self.observe()
            before = self.world.current()

        result = await execute_appium_tool(action.tool, dict(action.args), self.context)
        after: Snapshot | None = None
        if result.ok and action.verify_with != "none":
            observe_result = await self.observe()
            if observe_result.ok:
                after = self.world.current()

        report = verify_effect(action, before=before, after=after)
        ok = result.ok and report.observed
        return ActionOutcome(
            action=action,
            ok=ok,
            raw_text=result.output,
            before_snapshot_id=before.id if before else None,
            after_snapshot_id=after.id if after else None,
            effect_observed=report.observed,
            diff_summary=report.summary,
            duration_ms=result.duration_ms,
            error=None if ok else (result.output if not result.ok else report.summary),
        )

    def _load_snapshot(self, snapshot_id: str) -> Snapshot:
        if self.snapshot_loader is not None:
            return self.snapshot_loader(snapshot_id)
        return load_snapshot(snapshot_id, snapshots_dir=self.snapshots_dir)


def snapshot_id_from_output(output: str) -> str | None:
    """Extract snapshot_id from appium-cli snapshot output."""
    match = re.search(r"snapshot_id:\s*(?P<id>\S+)", output)
    if match:
        return match.group("id")
    return None
