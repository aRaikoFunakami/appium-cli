"""Snapshot data model compatible with smartestiroid.

Data classes:
- SnapshotElement: an actionable or visible element in the UI tree
- SnapshotContainer: a semantic region (topbar, list, dialog, overlay, tabs, content)
- AccessibilitySnapshot: the full screen snapshot
- LocatorStrategy: one Appium element-finding strategy
- RefEntry: locator strategies + expected bounds for a ref
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any


_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)]\[(\d+),(\d+)]")


# ============================================================
# LocatorStrategy / RefEntry
# ============================================================


@dataclass
class LocatorStrategy:
    """Appium element-finding strategy.

    Attributes:
        by: "id" / "accessibility_id" / "xpath" / "coordinates"
        value: search value (resource-id, accessibility id, xpath expr, or "x,y")
    """

    by: str
    value: str


@dataclass
class RefEntry:
    """Information needed to resolve a ref to an Appium WebElement.

    Attributes:
        strategies: ordered list of locator strategies (tried in order)
        expected_bounds: (x1, y1, x2, y2) for bounds verification
        role: element role
        name: accessibility label
    """

    strategies: list[LocatorStrategy]
    expected_bounds: tuple[int, int, int, int]
    role: str
    name: str


# ============================================================
# SnapshotElement
# ============================================================


@dataclass
class SnapshotElement:
    """One element in the accessibility snapshot.

    Attributes:
        ref: stable ref ID (e.g. "tabbackground_4", "btn_login")
        role: element role (button / textbox / text / checkbox / ...)
        name: accessibility label or text
        value: input value, check state, etc.
        state: state list (enabled / selected / checked / focused / disabled)
        bounds: bounding box (x1, y1, x2, y2)
        container_ref: ref of the owning container
        position_hint: relative position in container ("left-most", "right-most")
        name_source: origin of name ("text" / "content-desc" / None)
    """

    ref: str
    role: str
    name: str
    value: str | None = None
    state: list[str] = field(default_factory=list)
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    container_ref: str | None = None
    position_hint: str | None = None
    name_source: str | None = None

    def to_text(self) -> str:
        parts: list[str] = [f"[ref:{self.ref}]", self.role]
        if self.name_source == "content-desc":
            parts.append(f'"{self.name}" (content-desc)')
        else:
            parts.append(f'"{self.name}"')
        if self.value is not None and self.value != self.name:
            parts.append(f'value="{self.value}"')
        visible_states = [s for s in self.state if s != "enabled"]
        if visible_states:
            parts.append(f"[{','.join(visible_states)}]")
        if self.position_hint:
            parts.append(f"({self.position_hint})")
        return " ".join(parts)


# ============================================================
# SnapshotContainer
# ============================================================


@dataclass
class SnapshotContainer:
    """A semantic UI region.

    Attributes:
        ref: container ref ID (e.g. "rv_tab_menu", "topbar")
        region: region type (topbar / list / dialog / menu / content / tabs / overlay)
        title: optional region title
        children_refs: ordered list of child element refs
        scrollable: whether the container is scrollable
        scroll_direction: "horizontal" / "vertical" / ""
    """

    ref: str
    region: str
    title: str | None = None
    children_refs: list[str] = field(default_factory=list)
    scrollable: bool = False
    scroll_direction: str = ""


# ============================================================
# SelectionContainer
# ============================================================


@dataclass
class SelectionContainer:
    """Selection container (TabLayout / Spinner / RadioGroup etc.).

    Represents exclusive-selection UI where one option is active.

    Attributes:
        container_ref: ref of the container element
        container_class: Android class name
        options: list of options [{ref, name, selected}]
        selected_index: index of the currently selected option (None = unknown)
    """

    container_ref: str
    container_class: str
    options: list[dict[str, Any]] = field(default_factory=list)
    selected_index: int | None = None


# ============================================================
# AccessibilitySnapshot
# ============================================================


@dataclass
class AccessibilitySnapshot:
    """Full screen accessibility snapshot.

    Attributes:
        screen_id: screen identity hash (6-char hex)
        app_info: package + activity string
        containers: semantic region list
        elements: actionable/visible element list
        alerts: detected alerts/toasts
        nav: navigation info (back availability, etc.)
        selected_labels: labels of currently selected tabs/buttons
        body_texts: read-only body texts (not inside clickable ancestors)
        selection_containers: exclusive-selection containers (TabLayout / Spinner etc.)
    """

    screen_id: str
    app_info: str = ""
    containers: list[SnapshotContainer] = field(default_factory=list)
    elements: list[SnapshotElement] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    nav: dict[str, Any] = field(default_factory=dict)
    selection_containers: list[SelectionContainer] = field(default_factory=list)
    selected_labels: list[str] = field(default_factory=list)
    body_texts: list[str] = field(default_factory=list)

    def _filter_containers(self, scope: str | None) -> list[SnapshotContainer]:
        if scope is None or scope == "full":
            return self.containers
        if scope == "active_layer":
            dialogs = [c for c in self.containers if c.region in {"dialog", "overlay", "menu"}]
            return dialogs or self.containers
        if scope.startswith("near:"):
            target_ref = scope[5:]
            return [c for c in self.containers if target_ref in c.children_refs]
        return [c for c in self.containers if c.region == scope]

    def to_text(self, scope: str | None = None) -> str:
        lines: list[str] = []
        lines.append(f"screen: {self.app_info}" if self.app_info else "screen: android")
        lines.append(f"screen_id: {self.screen_id}")

        layout_summary = self._generate_layout_summary()
        if layout_summary:
            lines.append("")
            lines.extend(layout_summary)

        lines.append("")

        target_containers = self._filter_containers(scope)
        rendered_refs: set[str] = set()
        for container in target_containers:
            lines.extend(self._render_container(container, rendered_refs))

        orphan_elements = [e for e in self.elements if e.ref not in rendered_refs]
        if orphan_elements:
            if target_containers:
                lines.append("")
            for elem in orphan_elements:
                if scope == "inputs" and elem.role != "textbox":
                    continue
                lines.append(elem.to_text())

        lines.append("")
        if self.alerts:
            alert_texts = [a.get("message", a.get("type", "unknown")) for a in self.alerts]
            lines.append(f"alerts: {'; '.join(alert_texts)}")
        else:
            lines.append("alerts: none")

        nav_parts = [f"{k}={v}" for k, v in self.nav.items()]
        lines.append(f"nav: {', '.join(nav_parts) if nav_parts else 'none'}")

        return "\n".join(lines)

    def compute_diff(self, other: AccessibilitySnapshot) -> str:
        diff_lines: list[str] = []
        if self.screen_id == other.screen_id:
            diff_lines.append(f"screen_id: {self.screen_id} (unchanged)")
        else:
            diff_lines.append(f"screen_id: {self.screen_id} -> {other.screen_id} (changed)")

        old_map = {e.ref: e for e in self.elements}
        new_map = {e.ref: e for e in other.elements}
        changes: list[str] = []

        for ref in sorted(set(old_map) - set(new_map)):
            e = old_map[ref]
            changes.append(f'  - [ref:{ref}] removed ({e.role} "{e.name}")')
        for ref in sorted(set(new_map) - set(old_map)):
            e = new_map[ref]
            changes.append(f'  + [ref:{ref}] added: {e.role} "{e.name}"')
        for ref in sorted(set(old_map) & set(new_map)):
            old_e, new_e = old_map[ref], new_map[ref]
            element_changes: list[str] = []
            if old_e.name != new_e.name:
                element_changes.append(f'name: "{old_e.name}" -> "{new_e.name}"')
            if old_e.value != new_e.value:
                element_changes.append(f'value: "{old_e.value}" -> "{new_e.value}"')
            if old_e.state != new_e.state:
                element_changes.append(f"state: {old_e.state} -> {new_e.state}")
            if element_changes:
                changes.append(f"  ~ [ref:{ref}] {'; '.join(element_changes)}")

        if changes:
            diff_lines.append("diff:")
            diff_lines.extend(changes)
        else:
            diff_lines.append("diff: no changes")
        return "\n".join(diff_lines)

    # --- private helpers ---

    def _generate_layout_summary(self) -> list[str]:
        active_containers = [
            c for c in self.containers
            if any(e.container_ref == c.ref for e in self.elements)
        ]
        if len(active_containers) < 2:
            return []

        lines: list[str] = []
        for i, container in enumerate(active_containers[:10]):
            if i == 0:
                connector = "\u250c"
            elif i == len(active_containers[:10]) - 1:
                connector = "\u2514"
            else:
                connector = "\u251c"

            hint = self._infer_container_hint(container)
            hint_part = f" \u2500\u2500 {hint}" if hint else ""
            scroll_part = ""
            if container.scrollable:
                scroll_part = f" [scrollable\u2192{container.scroll_direction or '?'}]"
            title_part = f" ({container.title})" if container.title else ""
            lines.append(
                f"{connector} [ref:{container.ref}] "
                f"{container.region}{title_part}{scroll_part}{hint_part}"
            )

            children = [e for e in self.elements if e.container_ref == container.ref]
            role_groups: dict[str, list[str]] = {}
            for child in children:
                role_groups.setdefault(child.role, []).append(child.name)
            indent = "\u2502   " if i < len(active_containers[:10]) - 1 else "    "
            for role, names in role_groups.items():
                sample = ", ".join(f'"{n}"' for n in names[:4])
                if len(names) > 4:
                    sample += ", ..."
                lines.append(f"{indent}{role}({len(names)}): {sample}")

        if len(active_containers) > 10:
            lines.append(f"...other {len(active_containers) - 10} containers omitted")
        return lines

    def _infer_container_hint(self, container: SnapshotContainer) -> str:
        children = [e for e in self.elements if e.container_ref == container.ref]
        interactive = [e for e in children if e.role in ("button", "tab")]
        if container.region == "topbar":
            return ""
        if container.region in ("overlay", "dialog"):
            return "\u30aa\u30fc\u30d0\u30fc\u30ec\u30a4/\u30c0\u30a4\u30a2\u30ed\u30b0"
        if container.region == "tabs":
            return "\u30bf\u30d6\u30ca\u30d3\u30b2\u30fc\u30b7\u30e7\u30f3"
        if container.region == "list":
            if (container.scrollable
                    and container.scroll_direction == "horizontal"
                    and len(interactive) >= 3):
                return "\u6a2a\u30b9\u30af\u30ed\u30fc\u30eb\u30ca\u30d3\u30b2\u30fc\u30b7\u30e7\u30f3"
            if not container.scrollable and 2 <= len(interactive) <= 6:
                return "\u30b3\u30f3\u30c6\u30f3\u30c4\u5185\u30d5\u30a3\u30eb\u30bf\u30fc/\u30b5\u30d6\u30bf\u30d6"
        return ""

    def _render_container(self, container: SnapshotContainer, rendered_refs: set[str]) -> list[str]:
        lines: list[str] = []
        title_part = f" ({container.title})" if container.title else ""
        scroll_part = ""
        if container.scrollable:
            scroll_part = f" [scrollable\u2192{container.scroll_direction or 'unknown'}]"
        lines.append(f"\u2500\u2500 [ref:{container.ref}] {container.region}{title_part}{scroll_part} \u2500\u2500")
        child_elements = [e for e in self.elements if e.ref in container.children_refs]
        ref_order = {ref: i for i, ref in enumerate(container.children_refs)}
        child_elements.sort(key=lambda e: ref_order.get(e.ref, 999))
        for elem in child_elements:
            lines.append(elem.to_text())
            rendered_refs.add(elem.ref)
        lines.append("")
        return lines


# ============================================================
# Utility functions
# ============================================================


def compute_screen_id(elements: list[SnapshotElement]) -> str:
    """Compute screen identity hash from (role, name) pairs."""
    identity = sorted((e.role, e.name) for e in elements)
    return hashlib.md5(str(identity).encode()).hexdigest()[:6]


def parse_bounds(raw: str | None) -> tuple[int, int, int, int] | None:
    if not raw:
        return None
    match = _BOUNDS_RE.match(raw)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)),
            int(match.group(3)), int(match.group(4)))


def compress_xml(xml_source: str) -> str:
    try:
        root = ET.fromstring(xml_source)
    except ET.ParseError:
        return xml_source
    for node in root.iter():
        for key in list(node.attrib):
            value = node.attrib[key]
            if key in {"index", "package", "displayed", "drawing-order"}:
                del node.attrib[key]
            elif key in {"text", "content-desc", "resource-id", "hint"} and value == "":
                del node.attrib[key]
            elif key in {"clickable", "checkable", "checked", "selected", "focusable", "focused", "scrollable"} and value == "false":
                del node.attrib[key]
            elif key == "enabled" and value == "true":
                del node.attrib[key]
    return ET.tostring(root, encoding="unicode")


# ============================================================
# Legacy compatibility (will be removed after SnapshotGenerator port)
# ============================================================

_PACKAGE_PREFIX_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*:id/")


def _legacy_role_from_node(attrs: dict[str, str]) -> str:
    class_name = attrs.get("class", "")
    if attrs.get("scrollable") == "true":
        return "scrollview"
    if "EditText" in class_name:
        return "textbox"
    if "Button" in class_name:
        return "button"
    if "CheckBox" in class_name:
        return "checkbox"
    if "RadioButton" in class_name:
        return "radio"
    if "TextView" in class_name:
        return "text"
    if attrs.get("clickable") == "true":
        return "button"
    return class_name.rsplit(".", 1)[-1].lower() or "element"


def _legacy_node_name(attrs: dict[str, str]) -> tuple[str, str]:
    text = attrs.get("text", "")
    if text:
        return text, "text"
    desc = attrs.get("content-desc", "")
    if desc:
        return desc, "content-desc"
    rid = attrs.get("resource-id", "")
    if rid:
        return rid.rsplit("/", 1)[-1], "resource-id"
    class_name = attrs.get("class", "")
    return class_name.rsplit(".", 1)[-1] or "element", "class"


def _legacy_xpath_for(attrs: dict[str, str], index: int) -> str:
    if attrs.get("resource-id"):
        return f'//*[@resource-id="{attrs["resource-id"]}"]'
    if attrs.get("content-desc"):
        return f'//*[@content-desc="{attrs["content-desc"]}"]'
    if attrs.get("text"):
        return f'//*[@text="{attrs["text"]}"]'
    class_name = attrs.get("class", "*")
    return f"(//{class_name})[{index}]"


def generate_snapshot(
    xml_source: str, scope: str = "full"
) -> tuple[AccessibilitySnapshot, dict[str, SnapshotElement]]:
    """Legacy snapshot generator. Will be replaced by SnapshotGenerator."""
    root = ET.fromstring(xml_source)
    elements: list[SnapshotElement] = []
    containers: list[SnapshotContainer] = []
    current_container = SnapshotContainer(ref="c1", region="content")
    containers.append(current_container)
    element_index = 0
    container_index = 1

    for node in root.iter():
        attrs = dict(node.attrib)
        bounds = parse_bounds(attrs.get("bounds"))
        has_name = bool(attrs.get("text") or attrs.get("content-desc") or attrs.get("resource-id"))
        actionable = attrs.get("clickable") == "true" or attrs.get("focusable") == "true" or attrs.get("scrollable") == "true"
        if attrs.get("scrollable") == "true" and bounds is not None:
            container_index += 1
            current_container = SnapshotContainer(
                ref=f"c{container_index}",
                region="list",
                title=attrs.get("text") or attrs.get("content-desc") or "",
                scrollable=True,
                scroll_direction="vertical",
            )
            containers.append(current_container)

        if not (has_name or actionable):
            continue
        element_index += 1
        name, name_source = _legacy_node_name(attrs)
        state_values: list[str] = []
        for attr in ("enabled", "focusable", "checked", "selected", "focused", "scrollable"):
            if attrs.get(attr) == "true":
                state_values.append(attr)
        if attrs.get("clickable") == "true":
            state_values.append("clickable")
        else:
            state_values.append("not-clickable")

        element = SnapshotElement(
            ref=f"e{element_index}",
            role=_legacy_role_from_node(attrs),
            name=name,
            value=attrs.get("text") or None,
            state=state_values,
            bounds=bounds or (0, 0, 0, 0),
            container_ref=current_container.ref,
            name_source=name_source,
        )
        elements.append(element)
        current_container.children_refs.append(element.ref)

    if not containers[0].children_refs and len(containers) > 1:
        containers.pop(0)

    snapshot_obj = AccessibilitySnapshot(
        screen_id=hashlib.sha1(xml_source.encode("utf-8")).hexdigest()[:10],
        elements=elements,
        containers=containers,
    )
    return snapshot_obj, {element.ref: element for element in elements}


def element_to_ref_entry(element: SnapshotElement) -> dict[str, Any]:
    """Legacy ref entry builder. Will be replaced by SnapshotGenerator._build_ref_entry."""
    cx = (element.bounds[0] + element.bounds[2]) // 2 if element.bounds != (0, 0, 0, 0) else None
    cy = (element.bounds[1] + element.bounds[3]) // 2 if element.bounds != (0, 0, 0, 0) else None
    center = (cx, cy) if cx is not None else None
    return {
        "ref": element.ref,
        "resource_id": "",
        "accessibility_id": element.name if element.name_source == "content-desc" else "",
        "xpath": "",
        "bounds": f"[{element.bounds[0]},{element.bounds[1]}][{element.bounds[2]},{element.bounds[3]}]" if element.bounds != (0, 0, 0, 0) else "",
        "center": center,
        "role": element.role,
        "name": element.name,
    }
