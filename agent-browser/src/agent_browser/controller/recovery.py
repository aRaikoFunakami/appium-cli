"""Deterministic recovery decisions for structured controller failures."""

from __future__ import annotations

from dataclasses import dataclass

from agent_browser.controller.executor import ActionOutcome
from agent_browser.controller.planner import PlannedAction
from agent_browser.controller.task_plan import StepKind, StepStatus, TaskPlan, TaskStep


@dataclass(slots=True)
class RecoveryAction:
    """A recovery decision produced after a failed action outcome."""

    action: PlannedAction
    reason: str
    resume_step_id: str | None = None


@dataclass(slots=True)
class RecoveryManager:
    """Turns common failure modes into deterministic next actions."""

    plan: TaskPlan

    def recover(self, step: TaskStep, outcome: ActionOutcome) -> RecoveryAction | None:
        """Return the next recovery action, or None if manual/LLM escalation is needed."""
        error_text = (outcome.error or outcome.raw_text or "").lower()
        if self._is_stale_ref_error(error_text):
            return RecoveryAction(
                action=PlannedAction(
                    tool="snapshot",
                    args={"scope": "full", "context": "native", "boxes": False},
                    rationale="refresh snapshot after stale ref",
                    expected_effect="info_only",
                    verify_with="none",
                ),
                reason="stale_ref",
                resume_step_id=step.id,
            )

        if step.kind == StepKind.SCROLL and not outcome.effect_observed:
            if outcome.action.fallback:
                return RecoveryAction(
                    action=outcome.action.fallback[0],
                    reason="scroll_no_movement",
                    resume_step_id=step.id,
                )
            direction = step.arguments.get("direction", "down")
            return RecoveryAction(
                action=PlannedAction(
                    tool=f"swipe_{direction}",
                    args={},
                    rationale="fallback full-screen swipe after no-movement scroll",
                    expected_effect="ref_movement",
                    verify_with="snapshot_diff",
                ),
                reason="scroll_no_movement",
                resume_step_id=step.id,
            )

        return None

    def earliest_incomplete_step(self) -> TaskStep | None:
        """Return the earliest mandatory step without strong completion evidence."""
        for step in self.plan.steps:
            if step.mandatory and step.status != StepStatus.DONE:
                return step
        return None

    def _is_stale_ref_error(self, error_text: str) -> bool:
        return any(
            token in error_text
            for token in (
                "stale",
                "cannot be resolved",
                "not registered",
                "unknown ref",
                "no such ref",
            )
        )
