"""Effect verification for structured controller actions."""

from __future__ import annotations

from dataclasses import dataclass

from agent_browser.controller.planner import PlannedAction
from agent_browser.world.diff import diff_snapshots
from agent_browser.world.model import Snapshot


@dataclass(slots=True)
class EffectReport:
    """Observed effect summary for a tool call."""

    observed: bool
    summary: str


def verify_effect(
    action: PlannedAction,
    *,
    before: Snapshot | None,
    after: Snapshot | None,
) -> EffectReport:
    """Verify whether a planned action achieved its expected effect."""
    if action.verify_with == "none" or action.expected_effect in {"info_only", "noop"}:
        return EffectReport(observed=True, summary="verification not required")
    if before is None or after is None:
        return EffectReport(observed=False, summary="missing before/after snapshot")

    diff = diff_snapshots(before, after)
    if action.expected_effect == "ref_movement":
        observed = bool(diff.moved_refs or diff.added_refs or diff.removed_refs or diff.changed_texts)
        return EffectReport(
            observed=observed,
            summary=_diff_summary(diff) if observed else "no visible movement detected",
        )
    if action.verify_with == "snapshot_diff":
        if action.expected_effect == "tab_selected" and not diff.has_changes:
            return EffectReport(
                observed=True,
                summary="tab tap accepted; target may already be selected",
            )
        return EffectReport(
            observed=diff.has_changes,
            summary=_diff_summary(diff) if diff.has_changes else "no snapshot diff detected",
        )
    if action.verify_with == "ref_check":
        if action.expected_effect == "favorite_toggled" and not diff.has_changes:
            return EffectReport(
                observed=True,
                summary="favorite tap accepted; visible state verification deferred",
            )
        return EffectReport(
            observed=diff.has_changes,
            summary=_diff_summary(diff) if diff.has_changes else "target state did not visibly change",
        )
    return EffectReport(observed=False, summary=f"unsupported verification mode: {action.verify_with}")


def _diff_summary(diff) -> str:
    parts: list[str] = []
    if diff.added_refs:
        parts.append(f"added={len(diff.added_refs)}")
    if diff.removed_refs:
        parts.append(f"removed={len(diff.removed_refs)}")
    if diff.moved_refs:
        parts.append(f"moved={len(diff.moved_refs)}")
    if diff.changed_texts:
        parts.append("texts_changed")
    return ", ".join(parts) or "no changes"
