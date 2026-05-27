"""Snapshot diff primitives used by effect verification."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_browser.world.model import Snapshot


@dataclass(slots=True)
class SnapshotDiff:
    """Small structural diff between two snapshots."""

    before_id: str
    after_id: str
    added_refs: list[str] = field(default_factory=list)
    removed_refs: list[str] = field(default_factory=list)
    moved_refs: list[str] = field(default_factory=list)
    changed_texts: bool = False

    @property
    def has_changes(self) -> bool:
        """Return True if any structural change was detected."""
        return bool(self.added_refs or self.removed_refs or self.moved_refs or self.changed_texts)


def diff_snapshots(before: Snapshot, after: Snapshot) -> SnapshotDiff:
    """Compute a lightweight ref/text diff between snapshots."""
    before_refs = set(before.refs)
    after_refs = set(after.refs)
    common_refs = before_refs & after_refs
    before_texts = {target.text for target in before.text_targets}
    after_texts = {target.text for target in after.text_targets}

    return SnapshotDiff(
        before_id=before.id,
        after_id=after.id,
        added_refs=sorted(after_refs - before_refs),
        removed_refs=sorted(before_refs - after_refs),
        moved_refs=sorted(
            ref
            for ref in common_refs
            if before.refs[ref].bounds != after.refs[ref].bounds
        ),
        changed_texts=before_texts != after_texts,
    )
