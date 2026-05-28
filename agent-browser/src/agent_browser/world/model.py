"""World model data structures built from appium-cli snapshot artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


Bounds = tuple[int, int, int, int]


@dataclass(slots=True)
class RefView:
    """A normalized view of a snapshot ref."""

    ref: str
    role: str = ""
    name: str = ""
    bounds: Bounds | None = None
    actionable: bool = False
    editable: bool = False
    scrollable: bool = False
    scroll_direction: str | None = None
    container_kind: str | None = None
    parent_ref: str | None = None
    children: list[str] = field(default_factory=list)

    def contains(self, other: "RefView") -> bool:
        """Return True if this ref's bounds fully contain another ref."""
        if self.bounds is None or other.bounds is None or self.ref == other.ref:
            return False
        x1, y1, x2, y2 = self.bounds
        ox1, oy1, ox2, oy2 = other.bounds
        return x1 <= ox1 and y1 <= oy1 and x2 >= ox2 and y2 >= oy2

    @property
    def area(self) -> int:
        """Return bounded area in pixels."""
        if self.bounds is None:
            return 0
        x1, y1, x2, y2 = self.bounds
        return max(0, x2 - x1) * max(0, y2 - y1)


@dataclass(slots=True)
class TextTarget:
    """A text node plus its best actionable target."""

    text: str
    bounds: Bounds | None = None
    tap_target_ref: str | None = None
    action_target_ref: str | None = None
    target_role: str = ""
    target_bounds: Bounds | None = None


@dataclass(slots=True)
class Snapshot:
    """A normalized appium-cli snapshot artifact set."""

    id: str
    screen_id: str
    context: str
    refs: dict[str, RefView]
    text_targets: list[TextTarget] = field(default_factory=list)
    visible_texts: list[str] = field(default_factory=list)
    containers: list[str] = field(default_factory=list)
    screen_bounds: Bounds | None = None
    raw_artifact_paths: dict[str, Path] = field(default_factory=dict)

    def ref(self, ref: str) -> RefView:
        """Return a ref view by stable ref name."""
        return self.refs[ref]

    def scrollable_containers(self) -> list[RefView]:
        """Return scrollable container refs in snapshot order."""
        return [
            self.refs[ref]
            for ref in self.containers
            if ref in self.refs and self.refs[ref].scrollable
        ]

    def refs_within(self, container_ref: str) -> list[RefView]:
        """Return refs assigned under a container."""
        container = self.refs[container_ref]
        child_refs = set(container.children)
        return [ref for ref in self.refs.values() if ref.ref in child_refs]

    def find_text(self, text: str) -> list[TextTarget]:
        """Return text targets containing the given substring."""
        lowered = text.lower()
        return [target for target in self.text_targets if lowered in target.text.lower()]


@dataclass(slots=True)
class WorldModel:
    """Tracks the current and previous snapshots."""

    _current: Snapshot | None = None
    _previous: Snapshot | None = None

    def update(self, snapshot: Snapshot) -> Snapshot:
        """Set a new current snapshot and retain the previous one."""
        self._previous = self._current
        self._current = snapshot
        return snapshot

    def current(self) -> Snapshot | None:
        """Return the current snapshot if one is loaded."""
        return self._current

    def previous(self) -> Snapshot | None:
        """Return the previous snapshot if one is loaded."""
        return self._previous

    def has_current(self) -> bool:
        """Return True if a current snapshot is loaded."""
        return self._current is not None
