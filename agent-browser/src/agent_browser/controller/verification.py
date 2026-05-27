"""Deterministic final success checks for structured controller runs."""

from __future__ import annotations

from dataclasses import dataclass

from agent_browser.controller.task_plan import TaskPlan
from agent_browser.world.model import Bounds, RefView, Snapshot, TextTarget, WorldModel


_FAVORITES_MARKERS = ("お気に入り", "favorite", "favorites")


@dataclass(slots=True)
class FinalVerification:
    """Result of checking whether expected outcomes are satisfied."""

    passed: bool
    reason: str


def verify_success_criteria(plan: TaskPlan, world: WorldModel) -> FinalVerification:
    """Verify final success criteria that can be checked deterministically."""
    if not plan.success_criteria:
        return FinalVerification(passed=True, reason="no explicit success criteria")

    criteria_text = "\n".join(criterion.description for criterion in plan.success_criteria).lower()
    if any(marker in criteria_text for marker in _FAVORITES_MARKERS):
        snapshot = world.current()
        if snapshot is None:
            return FinalVerification(passed=False, reason="no final snapshot for favorites verification")
        return _verify_recorded_content_visible(plan, snapshot)

    return FinalVerification(passed=True, reason="no deterministic criteria matched")


def record_interacted_content(plan: TaskPlan, snapshot: Snapshot, action_ref: str) -> str | None:
    """Find and record the content label associated with an interaction ref."""
    content = infer_content_identity(plan, snapshot, action_ref)
    if content is None:
        return None
    for step in plan.steps:
        if step.arguments.get("last_action_ref") == action_ref:
            step.evidence.append(f"content_text:{content}")
            break
    return content


def infer_content_identity(plan: TaskPlan, snapshot: Snapshot, action_ref: str) -> str | None:
    """Infer a stable content text near the action target without app-specific refs."""
    ref = snapshot.refs.get(action_ref)
    if ref is None:
        return None
    candidates = _content_text_candidates(plan, snapshot)
    if not candidates:
        return None

    contained = [
        target
        for target in candidates
        if target.target_bounds is not None and ref.bounds is not None and _contains(target.target_bounds, ref.bounds)
    ]
    if contained:
        return _reading_order(contained)[0].text

    # A singleton/global favorite control often applies to the currently focused
    # content item. Prefer the first content-like label in reading order rather
    # than a duplicated card icon.
    return _reading_order(candidates)[0].text


def _verify_recorded_content_visible(plan: TaskPlan, snapshot: Snapshot) -> FinalVerification:
    expected_texts = _recorded_content_texts(plan)
    if not expected_texts:
        return FinalVerification(passed=False, reason="no interacted content identity recorded")

    visible_texts = {target.text.strip() for target in snapshot.text_targets if target.text.strip()}
    for expected in expected_texts:
        if expected in visible_texts:
            return FinalVerification(passed=True, reason=f"favorites content visible: {expected}")
    return FinalVerification(
        passed=False,
        reason=f"recorded content not visible in final page: {expected_texts[0]}",
    )


def _recorded_content_texts(plan: TaskPlan) -> list[str]:
    texts: list[str] = []
    for step in plan.steps:
        for item in step.evidence:
            if item.startswith("content_text:"):
                texts.append(item.removeprefix("content_text:"))
    return texts


def _content_text_candidates(plan: TaskPlan, snapshot: Snapshot) -> list[TextTarget]:
    excluded = _excluded_texts(plan)
    candidates: list[TextTarget] = []
    for target in snapshot.text_targets:
        text = target.text.strip()
        if not text or text in excluded:
            continue
        if target.target_role in {"button", "list"}:
            continue
        if _looks_like_short_control(text):
            continue
        candidates.append(target)
    return candidates


def _excluded_texts(plan: TaskPlan) -> set[str]:
    excluded: set[str] = set()
    for step in plan.steps:
        if step.target_hint:
            excluded.add(step.target_hint)
    return excluded


def _looks_like_short_control(text: str) -> bool:
    return len(text) <= 2


def _reading_order(targets: list[TextTarget]) -> list[TextTarget]:
    return sorted(targets, key=lambda target: (target.bounds or (0, 0, 0, 0))[1::-1])


def _contains(outer: Bounds, inner: Bounds) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]
