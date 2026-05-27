"""Tests for structured controller policy decisions."""

from __future__ import annotations

from agent_browser.controller.policy import PolicyEngine
from agent_browser.controller.task_compiler import TaskCompiler


def test_blocks_later_interaction_until_mandatory_scroll_done() -> None:
    goal = """\
1. Launch the app
2. Select the Movie tab
3. Scroll up
4. Tap the favorite button
"""
    plan = TaskCompiler().compile(goal)
    policy = PolicyEngine(plan=plan)
    favorite_step = plan.get_step("step-4")

    decision = policy.allow(favorite_step, "tap", {"ref": "favoriteicon"})

    assert decision.allowed is False
    assert decision.reason == "mandatory earlier step pending: step-1"


def test_blocks_tap_during_current_scroll_step() -> None:
    goal = """\
1. Select the Movie tab
2. Scroll up
3. Tap the favorite button
"""
    plan = TaskCompiler().compile(goal)
    plan.mark_done("step-1")
    policy = PolicyEngine(plan=plan)
    scroll_step = plan.get_step("step-2")

    decision = policy.allow(scroll_step, "tap", {"ref": "favoriteicon"})

    assert decision.allowed is False
    assert decision.reason == "tap is blocked while current step is scroll"


def test_allows_scroll_tool_for_scroll_step_after_dependencies_done() -> None:
    goal = """\
1. Select the Movie tab
2. Scroll up
3. Tap the favorite button
"""
    plan = TaskCompiler().compile(goal)
    plan.mark_done("step-1")
    policy = PolicyEngine(plan=plan, current_refs={"movies_section_scroll_view"})
    scroll_step = plan.get_step("step-2")

    decision = policy.allow(scroll_step, "scroll_up", {"ref": "movies_section_scroll_view"})

    assert decision.allowed is True


def test_blocks_unknown_ref_when_current_refs_are_known() -> None:
    plan = TaskCompiler().compile("1. Tap the login button")
    policy = PolicyEngine(plan=plan, current_refs={"login"})
    step = plan.get_step("step-1")

    decision = policy.allow(step, "tap", {"ref": "missing"})

    assert decision.allowed is False
    assert decision.reason == "stale or unknown ref: missing"
