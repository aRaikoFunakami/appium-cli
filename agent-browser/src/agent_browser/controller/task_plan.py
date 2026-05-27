"""Structured task plan primitives for the agent-browser controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class StepKind(str, Enum):
    """High-level operation types used by the structured controller."""

    LAUNCH = "launch"
    NAVIGATE = "navigate"
    SCROLL = "scroll"
    INTERACT = "interact"
    VERIFY = "verify"
    WAIT = "wait"


class StepStatus(str, Enum):
    """Lifecycle state for a task step."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass(slots=True)
class TaskStep:
    """A single mandatory or optional step derived from the user prompt."""

    id: str
    index: int
    kind: StepKind
    raw_text: str
    intent: str
    target_hint: str | None = None
    expected_effect: str | None = None
    mandatory: bool = True
    depends_on: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    last_error: str | None = None
    evidence: list[str] = field(default_factory=list)
    arguments: dict[str, str] = field(default_factory=dict)

    def is_terminal(self) -> bool:
        """Return True once this step should no longer be scheduled."""
        return self.status in {
            StepStatus.DONE,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
        }


@dataclass(slots=True)
class SuccessCriterion:
    """An expected outcome extracted from the prompt."""

    id: str
    description: str
    method: Literal["snapshot_search", "ref_present", "text_present", "llm_judge"]
    args: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class TaskPlan:
    """Ordered task plan plus final success criteria."""

    goal: str
    steps: list[TaskStep]
    success_criteria: list[SuccessCriterion] = field(default_factory=list)
    notes: str = ""

    def get_step(self, step_id: str) -> TaskStep:
        """Return a step by id, raising KeyError if it does not exist."""
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(step_id)

    def blockers_for(self, step: TaskStep) -> list[TaskStep]:
        """Return dependency steps that prevent ``step`` from starting."""
        blockers: list[TaskStep] = []
        for dependency_id in step.depends_on:
            dependency = self.get_step(dependency_id)
            if dependency.status != StepStatus.DONE:
                blockers.append(dependency)
        return blockers

    def is_step_ready(self, step: TaskStep) -> bool:
        """Return True if all dependencies are done and the step is schedulable."""
        if step.status not in {StepStatus.PENDING, StepStatus.READY, StepStatus.BLOCKED}:
            return False
        return not self.blockers_for(step)

    def next_ready_step(self) -> TaskStep | None:
        """Return the first ordered step that is ready to run."""
        for step in self.steps:
            if self.is_step_ready(step):
                step.status = StepStatus.READY
                return step
            if step.status in {StepStatus.PENDING, StepStatus.BLOCKED}:
                step.status = StepStatus.BLOCKED
        return None

    def mark_running(self, step_id: str) -> TaskStep:
        """Mark a ready step as running."""
        step = self.get_step(step_id)
        if not self.is_step_ready(step):
            blockers = ", ".join(blocker.id for blocker in self.blockers_for(step))
            raise ValueError(f"step {step_id} is blocked by: {blockers}")
        step.status = StepStatus.RUNNING
        step.attempts += 1
        return step

    def mark_done(self, step_id: str, evidence: str | None = None) -> TaskStep:
        """Mark a step as completed and optionally attach evidence."""
        step = self.get_step(step_id)
        step.status = StepStatus.DONE
        step.last_error = None
        if evidence:
            step.evidence.append(evidence)
        return step

    def mark_failed(self, step_id: str, error: str) -> TaskStep:
        """Mark a step as failed with an actionable error."""
        step = self.get_step(step_id)
        step.status = StepStatus.FAILED
        step.last_error = error
        return step

    def mandatory_pending_before(self, step: TaskStep) -> list[TaskStep]:
        """Return earlier mandatory steps not yet completed."""
        return [
            prior
            for prior in self.steps
            if prior.index < step.index and prior.mandatory and prior.status != StepStatus.DONE
        ]

    def finished(self) -> bool:
        """Return True when all mandatory steps have completed successfully."""
        return all(
            step.status == StepStatus.DONE
            for step in self.steps
            if step.mandatory
        )

    def failed(self) -> bool:
        """Return True when any mandatory step has failed."""
        return any(
            step.status == StepStatus.FAILED
            for step in self.steps
            if step.mandatory
        )
