"""Tree-first native (Android/iOS) snapshot model."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable

from .snapshot import LocatorStrategy, RefEntry


_ACTIONABLE_ROLES = {
    "button",
    "row",
    "tab",
    "checkbox",
    "radio",
    "switch",
    "link",
    "menuitem",
    "textbox",
}


_LAYER_CONTAINER_KINDS = {"dialog", "overlay", "sheet"}

_TRUNCATION_WARNING = (
    "WARNING: Snapshot output is truncated; some nodes are omitted. "
    "Increase --max-nodes/--depth or narrow the scope."
)


@dataclass
class NativeSnapshotNode:
    """One node in a native accessibility snapshot tree."""

    role: str
    name: str = ""
    ref: str | None = None
    class_name: str = ""
    resource_id: str = ""
    content_desc: str = ""
    text: str = ""
    value: str | None = None
    state: list[str] = field(default_factory=list)
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    children: list["NativeSnapshotNode"] = field(default_factory=list)
    strategies: list[LocatorStrategy] = field(default_factory=list)
    action_target_ref: str | None = None
    scrollable: bool = False
    scroll_direction: str = ""
    container_kind: str = ""
    omitted: bool = False

    @property
    def actionable(self) -> bool:
        """True when this node carries a ref and represents an interactive role."""
        if self.ref is None:
            return False
        return self.role in _ACTIONABLE_ROLES

    @property
    def editable(self) -> bool:
        """True when this node represents a text input."""
        return self.role == "textbox"

    def iter_nodes(self, include_self: bool = True) -> Iterable["NativeSnapshotNode"]:
        """Yield this node and its descendants depth-first."""
        if include_self:
            yield self
        for child in self.children:
            yield from child.iter_nodes()

    def find_ref(self, ref: str) -> "NativeSnapshotNode | None":
        """Find a descendant (or self) by ref, accepting [ref:x], ref:x, or x forms."""
        clean = ref.strip().strip("[]").removeprefix("ref:")
        for node in self.iter_nodes():
            if node.ref == clean:
                return node
        return None

    def to_ref_entry(self, context: str) -> RefEntry | None:
        """Build a RefEntry for the resolver. Returns None when ref is unset."""
        if not self.ref:
            return None
        return RefEntry(
            strategies=list(self.strategies),
            expected_bounds=self.bounds,
            role=self.role,
            name=self.name,
            context=context,
            source_type="native",
            action_target_ref=self.action_target_ref,
        )

    def to_line(self, *, include_bounds: bool = False) -> str:
        """Render a single line summary of this node."""
        if self.omitted:
            return "- ..."

        parts = [f"- {self.role}"]
        if self.name:
            parts.append(f'"{self.name}"')
        if self.ref:
            parts.append(f"[ref:{self.ref}]")
        visible_states = [item for item in self.state if item != "enabled"]
        if visible_states:
            parts.append(f"[{','.join(visible_states)}]")
        if self.scrollable:
            direction = self.scroll_direction or "any"
            parts.append(f"[scrollable:{direction}]")
        if self.value is not None and self.value != self.name:
            parts.append(f'value="{self.value}"')
        if include_bounds and self.bounds != (0, 0, 0, 0):
            parts.append(f"bounds={self.bounds}")
        return " ".join(parts)

    def to_text(self) -> str:
        """Alias for to_line()."""
        return self.to_line()


@dataclass
class NativeTextMatch:
    """A text match in a native snapshot.

    Attributes:
        node: the node whose name/value matched.
        target: the actionable ancestor (or self) that should receive the action.
        score: 100 exact, 80 prefix, 60 contains.
    """

    node: NativeSnapshotNode
    target: NativeSnapshotNode | None
    score: int


@dataclass
class NativeSnapshot:
    """Full native snapshot with a tree source of truth."""

    screen_id: str
    root: NativeSnapshotNode
    context: str = "NATIVE_APP"
    app_info: str = ""
    source_type: str = "native"
    nav: dict[str, Any] = field(default_factory=dict)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False

    @classmethod
    def from_root(
        cls,
        *,
        root: NativeSnapshotNode,
        app_info: str = "",
        nav: dict[str, Any] | None = None,
        alerts: list[dict[str, Any]] | None = None,
        truncated: bool = False,
        context: str = "NATIVE_APP",
    ) -> "NativeSnapshot":
        """Build a NativeSnapshot, computing screen_id from ref-bearing nodes."""
        canonical = sorted(
            (node.role, node.name) for node in root.iter_nodes() if node.ref
        )
        digest = hashlib.md5(str(canonical).encode("utf-8")).hexdigest()[:6]
        return cls(
            screen_id=digest,
            root=root,
            context=context,
            app_info=app_info,
            nav=nav or {},
            alerts=alerts or [],
            truncated=truncated,
        )

    def iter_nodes(self) -> Iterable[NativeSnapshotNode]:
        """Yield all nodes in the snapshot depth-first."""
        return self.root.iter_nodes()

    def find_ref(self, ref: str) -> NativeSnapshotNode | None:
        """Find a node by ref."""
        return self.root.find_ref(ref)

    def to_ref_map(self) -> dict[str, RefEntry]:
        """Build a {ref: RefEntry} map for the resolver."""
        result: dict[str, RefEntry] = {}
        for node in self.iter_nodes():
            entry = node.to_ref_entry(self.context)
            if entry is not None and node.ref:
                result[node.ref] = entry
        return result

    def find_text(
        self, text: str, *, inputs_only: bool = False
    ) -> list[NativeTextMatch]:
        """Find nodes whose name or value matches text. Carries nearest actionable target."""
        search_lower = text.lower()
        matches: list[NativeTextMatch] = []

        def walk(
            node: NativeSnapshotNode, nearest_target: NativeSnapshotNode | None
        ) -> None:
            if node.ref and node.actionable:
                target: NativeSnapshotNode | None = node
            else:
                target = nearest_target

            if not inputs_only or node.role == "textbox":
                name_lower = node.name.lower()
                value_lower = (node.value or "").lower()
                if name_lower == search_lower or value_lower == search_lower:
                    score = 100
                elif name_lower.startswith(search_lower) or value_lower.startswith(
                    search_lower
                ):
                    score = 80
                elif search_lower in name_lower or search_lower in value_lower:
                    score = 60
                else:
                    score = 0
                if score:
                    matches.append(
                        NativeTextMatch(node=node, target=target, score=score)
                    )

            for child in node.children:
                walk(child, target)

        walk(self.root, None)
        matches.sort(key=lambda item: item.score, reverse=True)
        return matches

    def describe_ref(self, ref: str) -> str:
        """Render a multi-line description of the ref's node and surroundings."""
        node = self.find_ref(ref)
        clean = ref.strip().strip("[]").removeprefix("ref:")
        if node is None:
            return f"ERROR: ref '{clean}' not found. Run snapshot() to refresh."

        lines = [
            f"element: {node.to_text()}",
            f"role: {node.role}",
            f"name: {node.name}",
        ]
        if node.value is not None:
            lines.append(f"value: {node.value}")
        lines.append(f"state: {', '.join(node.state) if node.state else 'none'}")
        lines.append(f"bounds: {node.bounds}")

        container = self._find_owning_container(node)
        if container is not None and container is not node:
            container_name = container.name or ""
            container_ref = container.ref or ""
            kind = container.container_kind or container.role
            descriptor = " ".join(
                part for part in (kind, container_ref, container_name) if part
            )
            lines.append(f"container: {descriptor}")

        if node.children:
            lines.append("subtree:")
            _render_node(node, lines, indent=1, boxes=True)
        return "\n".join(lines)

    def to_text(self, scope: str | None = None, *, boxes: bool = False) -> str:
        """Render the snapshot as text.

        Scope values:
            None / "full"   -> entire root subtree
            "inputs"        -> flat list of textbox nodes
            "depth:N"       -> render but cap depth at N
            "active_layer"  -> first subtree with container_kind in dialog/overlay/sheet
            "ref:<ref>"     -> exact ref subtree
            "near:<ref>"    -> the parent container subtree of the given ref
            Any tree scope may end with ",depth:N" to cap rendered depth.
        """
        lines: list[str] = []
        header_app = self.app_info or self.context
        lines.append(f"screen: {header_app}")
        lines.append(f"screen_id: {self.screen_id}")
        lines.append(f"context: {self.context}")
        lines.append(f"source: {self.source_type}")
        if self.app_info:
            lines.append(f"app_info: {self.app_info}")
        if self.truncated:
            lines.append("truncated: true")
            lines.append(_TRUNCATION_WARNING)
        lines.append("")

        render_scope = scope
        max_depth: int | None = None
        if scope and ",depth:" in scope:
            render_scope, depth_text = scope.rsplit(",depth:", 1)
            try:
                max_depth = int(depth_text)
            except ValueError:
                max_depth = None
        elif scope and scope.startswith("depth:"):
            try:
                max_depth = int(scope.split(":", 1)[1])
            except ValueError:
                max_depth = None

        if render_scope == "inputs":
            for node in self.iter_nodes():
                if node.role == "textbox":
                    lines.append(node.to_line(include_bounds=boxes))
        elif render_scope and render_scope.startswith("ref:"):
            target_ref = render_scope.split(":", 1)[1]
            subtree_root = self.find_ref(target_ref) or self.root
            _render_node(subtree_root, lines, indent=0, boxes=boxes, max_depth=max_depth)
        elif render_scope and render_scope.startswith("near:"):
            target_ref = render_scope.split(":", 1)[1]
            target_node = self.find_ref(target_ref)
            subtree_root: NativeSnapshotNode | None = None
            if target_node is not None:
                subtree_root = self._find_owning_container(target_node) or target_node
            if subtree_root is None:
                subtree_root = self.root
            _render_node(subtree_root, lines, indent=0, boxes=boxes, max_depth=max_depth)
        elif render_scope == "active_layer":
            layer = self._find_active_layer(self.root)
            target_root = layer if layer is not None else self.root
            _render_node(target_root, lines, indent=0, boxes=boxes, max_depth=max_depth)
        else:
            _render_node(self.root, lines, indent=0, boxes=boxes, max_depth=max_depth)

        lines.append("")
        if self.alerts:
            alert_texts = [a.get("message", a.get("type", "unknown")) for a in self.alerts]
            lines.append(f"alerts: {'; '.join(alert_texts)}")
        else:
            lines.append("alerts: none")
        nav_parts = [f"{key}={value}" for key, value in self.nav.items()]
        lines.append(f"nav: {', '.join(nav_parts) if nav_parts else 'none'}")
        return "\n".join(lines)

    def compute_diff(self, other: "NativeSnapshot") -> str:
        """Return a textual diff vs another snapshot keyed by ref."""
        before = {n.ref: n for n in self.iter_nodes() if n.ref}
        after = {n.ref: n for n in other.iter_nodes() if n.ref}

        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        common = sorted(set(before) & set(after))

        lines: list[str] = []
        if added:
            lines.append("added:")
            for ref in added:
                lines.append(f"  + {after[ref].to_line()}")
        if removed:
            lines.append("removed:")
            for ref in removed:
                lines.append(f"  - {before[ref].to_line()}")

        change_lines: list[str] = []
        for ref in common:
            a = before[ref]
            b = after[ref]
            diffs: list[str] = []
            if a.name != b.name:
                diffs.append(f'name: "{a.name}" -> "{b.name}"')
            if a.value != b.value:
                diffs.append(f"value: {a.value!r} -> {b.value!r}")
            if a.state != b.state:
                diffs.append(f"state: {a.state} -> {b.state}")
            if diffs:
                change_lines.append(f"  ~ [ref:{ref}] " + "; ".join(diffs))
        if change_lines:
            lines.append("changed:")
            lines.extend(change_lines)

        if not lines:
            return "no changes"
        return "\n".join(lines)

    def _find_owning_container(
        self, target: NativeSnapshotNode
    ) -> NativeSnapshotNode | None:
        """Walk the tree to find the nearest ancestor with container_kind set."""
        path: list[NativeSnapshotNode] = []

        def walk(node: NativeSnapshotNode) -> bool:
            path.append(node)
            if node is target:
                return True
            for child in node.children:
                if walk(child):
                    return True
            path.pop()
            return False

        if not walk(self.root):
            return None
        for ancestor in reversed(path[:-1]):
            if ancestor.container_kind:
                return ancestor
        return None

    def _find_active_layer(
        self, node: NativeSnapshotNode
    ) -> NativeSnapshotNode | None:
        """Depth-first search for the first node whose container_kind is a layer kind."""
        if node.container_kind in _LAYER_CONTAINER_KINDS:
            return node
        for child in node.children:
            found = self._find_active_layer(child)
            if found is not None:
                return found
        return None


def _render_node(
    node: NativeSnapshotNode,
    lines: list[str],
    *,
    indent: int,
    boxes: bool,
    max_depth: int | None = None,
) -> None:
    """Render a node and its subtree into ``lines`` using 2-space indents."""
    if max_depth is not None and indent > max_depth:
        lines.append("  " * indent + "- ...")
        return
    lines.append("  " * indent + node.to_line(include_bounds=boxes))
    for child in node.children:
        _render_node(
            child, lines, indent=indent + 1, boxes=boxes, max_depth=max_depth
        )
