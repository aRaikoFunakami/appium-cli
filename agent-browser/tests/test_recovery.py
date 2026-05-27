"""Tests for deterministic recovery decisions."""

from __future__ import annotations

from agent_browser.controller.executor import ActionOutcome
from agent_browser.controller.planner import PlannedAction
from agent_browser.controller.recovery import RecoveryManager
from agent_browser.controller.task_compiler import TaskCompiler


def _outcome(action: PlannedAction, *, error: str | None = None, effect_observed: bool = False) -> ActionOutcome:
    return ActionOutcome(
        action=action,
        ok=False,
        raw_text=error or "OK",
        before_snapshot_id="before",
        after_snapshot_id="after",
        effect_observed=effect_observed,
        diff_summary="",
        duration_ms=1.0,
        error=error,
    )


def test_stale_ref_recovery_takes_fresh_snapshot() -> None:
    plan = TaskCompiler().compile("1. Tap the favorite button")
    step = plan.get_step("step-1")
    action = PlannedAction(
        tool="tap",
        args={"ref": "favoriteicon"},
        rationale="test",
        expected_effect="favorite_toggled",
        verify_with="ref_check",
    )

    recovery = RecoveryManager(plan).recover(
        step,
        _outcome(action, error="FAILED: ref 'favoriteicon' cannot be resolved"),
    )

    assert recovery is not None
    assert recovery.reason == "stale_ref"
    assert recovery.resume_step_id == "step-1"
    assert recovery.action.tool == "snapshot"


def test_no_movement_scroll_uses_first_fallback_action() -> None:
    plan = TaskCompiler().compile("1. Scroll up")
    step = plan.get_step("step-1")
    fallback = PlannedAction(
        tool="scroll_up",
        args={"ref": "movies_section_scroll_view", "percent": 0.8},
        rationale="fallback",
        expected_effect="ref_movement",
        verify_with="snapshot_diff",
    )
    action = PlannedAction(
        tool="scroll_up",
        args={"ref": "rv_tab_menu", "percent": 0.8},
        rationale="bad candidate",
        expected_effect="ref_movement",
        verify_with="snapshot_diff",
        fallback=[fallback],
    )

    recovery = RecoveryManager(plan).recover(step, _outcome(action, effect_observed=False))

    assert recovery is not None
    assert recovery.reason == "scroll_no_movement"
    assert recovery.action is fallback
    assert recovery.resume_step_id == "step-1"


def test_no_movement_scroll_without_fallback_uses_fullscreen_swipe() -> None:
    plan = TaskCompiler().compile("1. Scroll up")
    step = plan.get_step("step-1")
    action = PlannedAction(
        tool="scroll_up",
        args={"ref": "rv_tab_menu", "percent": 0.8},
        rationale="bad candidate",
        expected_effect="ref_movement",
        verify_with="snapshot_diff",
    )

    recovery = RecoveryManager(plan).recover(step, _outcome(action, effect_observed=False))

    assert recovery is not None
    assert recovery.action.tool == "swipe_up"
