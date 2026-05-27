"""Deterministic action planner for structured controller steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from agent_browser.controller.scoring import ScrollScoreContext, rank_scroll_containers
from agent_browser.controller.task_plan import StepKind, TaskStep
from agent_browser.world.model import Snapshot
from agent_browser.world.query import candidate_refs_by_name


ExpectedEffect = Literal[
    "screen_change",
    "ref_movement",
    "tab_selected",
    "favorite_toggled",
    "info_only",
    "noop",
]


@dataclass(slots=True)
class PlannedAction:
    """A deterministic tool call plus the expected effect to verify."""

    tool: str
    args: dict[str, object]
    rationale: str
    expected_effect: ExpectedEffect
    verify_with: Literal["snapshot_diff", "ref_check", "text_check", "none"]
    fallback: list["PlannedAction"] = field(default_factory=list)


@dataclass(slots=True)
class Planner:
    """Plans simple actions from structured task steps and snapshots."""

    main_content_bias: float = 1.0
    header_penalty: float = 1.0

    def plan(self, step: TaskStep, snapshot: Snapshot) -> PlannedAction:
        """Plan one action for the given step."""
        if step.kind == StepKind.SCROLL:
            return self.plan_scroll(step, snapshot)
        if step.kind == StepKind.NAVIGATE:
            return self.plan_navigation(step, snapshot)
        if step.kind == StepKind.INTERACT:
            return self.plan_interaction(step, snapshot)
        if step.kind == StepKind.LAUNCH and "app_id" in step.arguments:
            return PlannedAction(
                tool="activate_app",
                args={"app_id": step.arguments["app_id"]},
                rationale=f"launch app for {step.id}",
                expected_effect="screen_change",
                verify_with="snapshot_diff",
            )
        return PlannedAction(
            tool="snapshot",
            args={"scope": "full", "context": "native", "boxes": False},
            rationale=f"observe before handling {step.id}",
            expected_effect="info_only",
            verify_with="none",
        )

    def plan_scroll(self, step: TaskStep, snapshot: Snapshot) -> PlannedAction:
        """Plan a scroll action against the highest-scored container."""
        direction = step.arguments.get("direction", "down")
        ranking = rank_scroll_containers(
            snapshot,
            ScrollScoreContext(
                direction=direction,
                target_hint=step.target_hint,
                main_content_bias=self.main_content_bias,
                header_penalty=self.header_penalty,
            ),
        )
        if not ranking:
            return PlannedAction(
                tool=f"swipe_{direction}",
                args={},
                rationale="no scrollable containers found; fallback to full-screen swipe",
                expected_effect="ref_movement",
                verify_with="snapshot_diff",
            )

        best, _score = ranking[0]
        fallback = [
            PlannedAction(
                tool=f"scroll_{direction}",
                args={"ref": ref.ref, "percent": 0.8},
                rationale=f"fallback scroll candidate score={score:.2f}",
                expected_effect="ref_movement",
                verify_with="snapshot_diff",
            )
            for ref, score in ranking[1:3]
        ]
        fallback.append(
            PlannedAction(
                tool=f"swipe_{direction}",
                args={"ref": best.ref},
                rationale="gesture fallback for no-movement scroll",
                expected_effect="ref_movement",
                verify_with="snapshot_diff",
            )
        )
        return PlannedAction(
            tool=f"scroll_{direction}",
            args={"ref": best.ref, "percent": 0.8},
            rationale=f"best scroll container for {step.intent}: {best.ref}",
            expected_effect="ref_movement",
            verify_with="snapshot_diff",
            fallback=fallback,
        )

    def plan_navigation(self, step: TaskStep, snapshot: Snapshot) -> PlannedAction:
        """Plan a tap on a text target such as a tab."""
        if step.target_hint:
            targets = snapshot.find_text(step.target_hint)
            for target in targets:
                ref = target.tap_target_ref or target.action_target_ref
                if ref:
                    return PlannedAction(
                        tool="tap",
                        args={"ref": ref},
                        rationale=f"tap text target {step.target_hint}",
                        expected_effect="tab_selected",
                        verify_with="snapshot_diff",
                    )
        return PlannedAction(
            tool="snapshot_search",
            args={"text": step.target_hint or step.intent},
            rationale="need target discovery before navigation",
            expected_effect="info_only",
            verify_with="none",
        )

    def plan_interaction(self, step: TaskStep, snapshot: Snapshot) -> PlannedAction:
        """Plan a simple target interaction."""
        hint = step.target_hint or step.intent
        normalized_hint = _normalize_interaction_hint(hint)
        group_counts = _candidate_group_counts(snapshot, normalized_hint)
        candidates = sorted(
            candidate_refs_by_name(snapshot, normalized_hint),
            key=lambda ref: _interaction_candidate_rank(ref.ref, normalized_hint, group_counts),
        )
        if candidates:
            return PlannedAction(
                tool="tap",
                args={"ref": candidates[0].ref},
                rationale=f"tap matching target {candidates[0].ref}",
                expected_effect="favorite_toggled" if "favorite" in candidates[0].ref.lower() else "screen_change",
                verify_with="ref_check",
            )
        return PlannedAction(
            tool="snapshot_search",
            args={"text": hint},
            rationale="need target discovery before interaction",
            expected_effect="info_only",
            verify_with="none",
        )


def _normalize_interaction_hint(hint: str) -> str:
    lowered = hint.lower()
    if "お気に入り" in hint or "favorite" in lowered:
        return "favorite"
    return hint


def _interaction_candidate_rank(ref: str, hint: str, group_counts: dict[str, int]) -> tuple[int, str]:
    lowered = ref.lower()
    group = _ref_group(lowered)
    if group_counts.get(group, 0) == 1:
        return (0, lowered)
    if lowered.startswith(hint.lower()):
        return (1, lowered)
    return (2, lowered)


def _candidate_group_counts(snapshot: Snapshot, hint: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ref in candidate_refs_by_name(snapshot, hint):
        group = _ref_group(ref.ref.lower())
        counts[group] = counts.get(group, 0) + 1
    return counts


def _ref_group(ref: str) -> str:
    return ref.rsplit("_", 1)[0] if ref.rsplit("_", 1)[-1].isdigit() else ref
