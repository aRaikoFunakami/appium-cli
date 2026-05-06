"""Tree-first WebView snapshot model."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable

from .snapshot import LocatorStrategy, RefEntry


_ACTIONABLE_ROLES = {
    "button",
    "checkbox",
    "file",
    "link",
    "menuitem",
    "option",
    "radio",
    "select",
    "slider",
    "switch",
    "tab",
    "textbox",
}

_TRUNCATION_WARNING = (
    "WARNING: Snapshot output is truncated; some nodes are omitted. "
    "Increase --max-nodes/--depth or narrow the scope."
)


@dataclass
class WebSnapshotNode:
    """One node in a WebView accessibility/DOM snapshot tree."""

    role: str
    name: str = ""
    ref: str | None = None
    tag: str = ""
    value: str | None = None
    state: list[str] = field(default_factory=list)
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    strategies: list[LocatorStrategy] = field(default_factory=list)
    children: list["WebSnapshotNode"] = field(default_factory=list)
    omitted: bool = False

    @property
    def actionable(self) -> bool:
        return self.ref is not None or self.role in _ACTIONABLE_ROLES

    def iter_nodes(self, include_self: bool = True) -> Iterable["WebSnapshotNode"]:
        if include_self:
            yield self
        for child in self.children:
            yield from child.iter_nodes()

    def find_ref(self, ref: str) -> "WebSnapshotNode | None":
        clean = ref.strip().strip("[]").removeprefix("ref:")
        for node in self.iter_nodes():
            if node.ref == clean:
                return node
        return None

    def to_ref_entry(self, context: str) -> RefEntry | None:
        if not self.ref:
            return None
        return RefEntry(
            strategies=list(self.strategies),
            expected_bounds=self.bounds,
            role=self.role,
            name=self.name,
            context=context,
            source_type="web",
        )

    def to_line(self, *, include_bounds: bool = False) -> str:
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
        if self.value is not None and self.value != self.name:
            parts.append(f'value="{self.value}"')
        if include_bounds and self.bounds != (0, 0, 0, 0):
            parts.append(f"bounds={self.bounds}")
        return " ".join(parts)

    def to_text(self) -> str:
        return self.to_line()


@dataclass
class WebTextMatch:
    node: WebSnapshotNode
    target: WebSnapshotNode | None
    score: int


@dataclass
class WebSnapshot:
    """Full WebView snapshot with a tree source of truth."""

    screen_id: str
    context: str
    root: WebSnapshotNode
    url: str = ""
    title: str = ""
    source_type: str = "web"
    nav: dict[str, Any] = field(default_factory=dict)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False

    @classmethod
    def from_root(
        cls,
        *,
        root: WebSnapshotNode,
        context: str,
        url: str = "",
        title: str = "",
        nav: dict[str, Any] | None = None,
        truncated: bool = False,
    ) -> "WebSnapshot":
        rendered = "\n".join(node.to_line() for node in root.iter_nodes())
        screen_id = hashlib.md5(rendered.encode("utf-8")).hexdigest()[:6]
        return cls(
            screen_id=screen_id,
            context=context,
            root=root,
            url=url,
            title=title,
            nav=nav or ({"back": True} if url else {}),
            truncated=truncated,
        )

    def iter_nodes(self) -> Iterable[WebSnapshotNode]:
        return self.root.iter_nodes()

    def find_ref(self, ref: str) -> WebSnapshotNode | None:
        return self.root.find_ref(ref)

    def to_ref_map(self) -> dict[str, RefEntry]:
        result: dict[str, RefEntry] = {}
        for node in self.iter_nodes():
            entry = node.to_ref_entry(self.context)
            if entry is not None and node.ref:
                result[node.ref] = entry
        return result

    def to_text(self, scope: str | None = None, *, boxes: bool = False) -> str:
        lines: list[str] = []
        app_info = f"{self.context} {self.url}" if self.url else self.context
        lines.append(f"screen: {app_info}")
        lines.append(f"screen_id: {self.screen_id}")
        lines.append(f"context: {self.context}")
        lines.append(f"source: {self.source_type}")
        if self.title:
            lines.append(f"title: {self.title}")
        if self.url:
            lines.append(f"url: {self.url}")
        if self.truncated:
            lines.append("truncated: true")
            lines.append(_TRUNCATION_WARNING)
        lines.append("")

        max_depth = None
        if scope and scope.startswith("depth:"):
            try:
                max_depth = int(scope.split(":", 1)[1])
            except ValueError:
                max_depth = None
        if scope == "inputs":
            for node in self.iter_nodes():
                if node.role == "textbox":
                    lines.append(node.to_line(include_bounds=boxes))
        else:
            self._render_node(self.root, lines, indent=0, boxes=boxes, max_depth=max_depth)

        lines.append("")
        if self.alerts:
            alert_texts = [a.get("message", a.get("type", "unknown")) for a in self.alerts]
            lines.append(f"alerts: {'; '.join(alert_texts)}")
        else:
            lines.append("alerts: none")
        nav_parts = [f"{key}={value}" for key, value in self.nav.items()]
        lines.append(f"nav: {', '.join(nav_parts) if nav_parts else 'none'}")
        return "\n".join(lines)

    def describe_ref(self, ref: str) -> str:
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
        if node.children:
            lines.append("subtree:")
            self._render_node(node, lines, indent=1, boxes=True)
        return "\n".join(lines)

    def find_text(self, text: str, *, inputs_only: bool = False) -> list[WebTextMatch]:
        search_lower = text.lower()
        matches: list[WebTextMatch] = []

        def walk(node: WebSnapshotNode, nearest_target: WebSnapshotNode | None) -> None:
            target = node if node.ref else nearest_target
            if node.ref:
                target = node

            if not inputs_only or node.role == "textbox":
                name_lower = node.name.lower()
                value_lower = (node.value or "").lower()
                if name_lower == search_lower or value_lower == search_lower:
                    score = 100
                elif name_lower.startswith(search_lower) or value_lower.startswith(search_lower):
                    score = 80
                elif search_lower in name_lower or search_lower in value_lower:
                    score = 60
                else:
                    score = 0
                if score:
                    matches.append(WebTextMatch(node=node, target=target, score=score))

            for child in node.children:
                walk(child, target)

        walk(self.root, None)
        matches.sort(key=lambda item: item.score, reverse=True)
        return matches

    @staticmethod
    def _render_node(
        node: WebSnapshotNode,
        lines: list[str],
        *,
        indent: int,
        boxes: bool,
        max_depth: int | None = None,
    ) -> None:
        if max_depth is not None and indent > max_depth:
            lines.append("  " * indent + "- ...")
            return

        if _is_transparent_wrapper(node):
            for child in node.children:
                WebSnapshot._render_node(child, lines, indent=indent, boxes=boxes, max_depth=max_depth)
            return

        lines.append("  " * indent + node.to_line(include_bounds=boxes))
        for child in node.children:
            WebSnapshot._render_node(child, lines, indent=indent + 1, boxes=boxes, max_depth=max_depth)


def _is_transparent_wrapper(node: WebSnapshotNode) -> bool:
    if node.ref or node.name or node.value or node.state or node.omitted:
        return False
    return node.role in {"element", "generic", "group"} and node.tag in {
        "",
        "body",
        "div",
        "html",
        "main",
        "section",
        "span",
    }
