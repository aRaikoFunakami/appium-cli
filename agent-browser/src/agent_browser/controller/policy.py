"""Policy checks for structured task execution."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_browser.controller.task_plan import StepKind, TaskPlan, TaskStep


@dataclass(slots=True)
class PolicyDecision:
    """Result of checking whether an action is allowed."""

    allowed: bool
    reason: str | None = None


@dataclass(slots=True)
class PolicyEngine:
    """Enforces ordered mandatory steps and basic action constraints."""

    plan: TaskPlan
    strict_step_order: bool = True
    current_refs: set[str] = field(default_factory=set)

    def allow(self, step: TaskStep, tool: str, args: dict[str, object] | None = None) -> PolicyDecision:
        """Return whether a tool call is allowed for a plan step."""
        args = args or {}

        if self.strict_step_order:
            pending = self.plan.mandatory_pending_before(step)
            if pending:
                return PolicyDecision(
                    allowed=False,
                    reason=f"mandatory earlier step pending: {pending[0].id}",
                )

        stale_ref_decision = self._check_stale_ref(tool, args)
        if not stale_ref_decision.allowed:
            return stale_ref_decision

        if step.kind == StepKind.SCROLL and tool not in {
            "snapshot",
            "snapshot_actionable_tree",
            "snapshot_search",
            "snapshot_refs",
            "list_containers",
            "scroll",
            "scroll_up",
            "scroll_down",
            "scroll_left",
            "scroll_right",
            "swipe",
            "swipe_up",
            "swipe_down",
            "swipe_left",
            "swipe_right",
        }:
            return PolicyDecision(
                allowed=False,
                reason=f"{tool} is blocked while current step is scroll",
            )

        return PolicyDecision(allowed=True)

    def _check_stale_ref(self, tool: str, args: dict[str, object]) -> PolicyDecision:
        if tool in {"snapshot", "snapshot_actionable_tree", "snapshot_search", "snapshot_refs", "list_containers"}:
            return PolicyDecision(allowed=True)
        ref = args.get("ref") or args.get("container_ref")
        if isinstance(ref, str) and self.current_refs and ref not in self.current_refs:
            return PolicyDecision(allowed=False, reason=f"stale or unknown ref: {ref}")
        return PolicyDecision(allowed=True)
