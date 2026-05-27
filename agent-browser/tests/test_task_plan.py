"""Tests for structured task plan scheduling."""

from __future__ import annotations

import pytest

from agent_browser.controller.task_plan import (
    StepKind,
    StepStatus,
    TaskPlan,
    TaskStep,
)


def _plan() -> TaskPlan:
    return TaskPlan(
        goal="test",
        steps=[
            TaskStep(
                id="step-1",
                index=1,
                kind=StepKind.NAVIGATE,
                raw_text="tap movie",
                intent="tap movie",
            ),
            TaskStep(
                id="step-2",
                index=2,
                kind=StepKind.SCROLL,
                raw_text="scroll up",
                intent="scroll up",
                depends_on=["step-1"],
            ),
            TaskStep(
                id="step-3",
                index=3,
                kind=StepKind.INTERACT,
                raw_text="tap favorite",
                intent="tap favorite",
                depends_on=["step-2"],
            ),
        ],
    )


def test_next_ready_step_returns_first_unblocked_step() -> None:
    plan = _plan()

    assert plan.next_ready_step().id == "step-1"


def test_later_step_is_blocked_until_dependency_done() -> None:
    plan = _plan()
    favorite_step = plan.get_step("step-3")

    assert plan.is_step_ready(favorite_step) is False
    assert [step.id for step in plan.blockers_for(favorite_step)] == ["step-2"]


def test_mark_running_rejects_blocked_step() -> None:
    plan = _plan()

    with pytest.raises(ValueError, match="step-3 is blocked"):
        plan.mark_running("step-3")


def test_order_advances_after_mark_done() -> None:
    plan = _plan()

    plan.mark_done("step-1", evidence="movie tab selected")
    assert plan.next_ready_step().id == "step-2"

    plan.mark_done("step-2", evidence="content moved")
    assert plan.next_ready_step().id == "step-3"


def test_mandatory_pending_before_tracks_ordered_blockers() -> None:
    plan = _plan()
    plan.mark_done("step-1")
    favorite_step = plan.get_step("step-3")

    assert [step.id for step in plan.mandatory_pending_before(favorite_step)] == ["step-2"]


def test_finished_requires_all_mandatory_steps_done() -> None:
    plan = _plan()

    assert plan.finished() is False
    for step in plan.steps:
        step.status = StepStatus.DONE

    assert plan.finished() is True
