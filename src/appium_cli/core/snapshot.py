"""Minimal snapshot and ref model compatible with smartestiroid tool output."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any


_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)]\[(\d+),(\d+)]")


@dataclass
class Bounds:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    @property
    def center(self) -> tuple[int, int]:
        return (self.x1 + self.width // 2, self.y1 + self.height // 2)

    def __str__(self) -> str:
        return f"[{self.x1},{self.y1}][{self.x2},{self.y2}]"


@dataclass
class SnapshotElement:
    ref: str
    role: str
    name: str
    value: str | None = None
    state: list[str] = field(default_factory=list)
    bounds: Bounds | None = None
    container_ref: str | None = None
    name_source: str = "text"
    resource_id: str = ""
    class_name: str = ""
    xpath: str = ""

    def to_text(self) -> str:
        text = f'[ref:{self.ref}] {self.role} "{self.name}"'
        if self.name_source == "content-desc":
            text += " (content-desc)"
        if self.value is not None and self.value != self.name:
            text += f' value="{self.value}"'
        visible_state = [item for item in self.state if item != "enabled"]
        if visible_state:
            text += f" [{' '.join(visible_state)}]"
        return text


@dataclass
class SnapshotContainer:
    ref: str
    region: str
    title: str = ""
    children_refs: list[str] = field(default_factory=list)
    scrollable: bool = False
    scroll_direction: str | None = None


@dataclass
class AccessibilitySnapshot:
    screen_id: str
    elements: list[SnapshotElement]
    containers: list[SnapshotContainer]
    alerts: list[str] = field(default_factory=list)
    nav: list[str] = field(default_factory=list)

    def _filter_containers(self, scope: str) -> list[SnapshotContainer]:
        if scope in ("", "full", None):
            return self.containers
        if scope == "active_layer":
            dialogs = [c for c in self.containers if c.region in {"dialog", "menu", "overlay"}]
            return dialogs or self.containers
        if scope == "list":
            return [c for c in self.containers if c.scrollable or c.region == "list"]
        if scope == "topbar":
            return [c for c in self.containers if c.region == "topbar"]
        return [c for c in self.containers if c.region == scope]

    def to_text(self, scope: str = "full") -> str:
        lines = [f"screen: android", f"screen_id: {self.screen_id}", ""]
        rendered: set[str] = set()
        containers = self._filter_containers(scope)
        for container in containers:
            title = f" ({container.title})" if container.title else ""
            scroll = f" [scrollable->{container.scroll_direction or 'unknown'}]" if container.scrollable else ""
            lines.append(f"── [ref:{container.ref}] {container.region}{title}{scroll} ──")
            for ref in container.children_refs:
                element = next((item for item in self.elements if item.ref == ref), None)
                if element is None:
                    continue
                lines.append(element.to_text())
                rendered.add(ref)
            lines.append("")

        orphan_elements = [item for item in self.elements if item.ref not in rendered]
        if orphan_elements:
            lines.append("── elements ──")
            for element in orphan_elements:
                if scope == "inputs" and element.role != "textbox":
                    continue
                lines.append(element.to_text())

        if self.alerts:
            lines.append("")
            lines.append("alerts: " + ", ".join(self.alerts))
        if self.nav:
            lines.append("nav: " + ", ".join(self.nav))
        return "\n".join(lines).rstrip()


def parse_bounds(raw: str | None) -> Bounds | None:
    if not raw:
        return None
    match = _BOUNDS_RE.match(raw)
    if not match:
        return None
    return Bounds(*(int(group) for group in match.groups()))


def compute_screen_id(xml_source: str) -> str:
    return hashlib.sha1(xml_source.encode("utf-8")).hexdigest()[:10]


def role_from_node(attrs: dict[str, str]) -> str:
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


def _node_name(attrs: dict[str, str]) -> tuple[str, str]:
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


def _xpath_for(attrs: dict[str, str], index: int) -> str:
    if attrs.get("resource-id"):
        return f'//*[@resource-id="{attrs["resource-id"]}"]'
    if attrs.get("content-desc"):
        return f'//*[@content-desc="{attrs["content-desc"]}"]'
    if attrs.get("text"):
        return f'//*[@text="{attrs["text"]}"]'
    class_name = attrs.get("class", "*")
    return f"(//{class_name})[{index}]"


def generate_snapshot(xml_source: str, scope: str = "full") -> tuple[AccessibilitySnapshot, dict[str, SnapshotElement]]:
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
        name, name_source = _node_name(attrs)
        state_values = []
        for attr in ("enabled", "checked", "selected", "focused", "scrollable"):
            if attrs.get(attr) == "true":
                state_values.append(attr)
        element = SnapshotElement(
            ref=f"e{element_index}",
            role=role_from_node(attrs),
            name=name,
            value=attrs.get("text") or None,
            state=state_values,
            bounds=bounds,
            container_ref=current_container.ref,
            name_source=name_source,
            resource_id=attrs.get("resource-id", ""),
            class_name=attrs.get("class", ""),
            xpath=_xpath_for(attrs, element_index),
        )
        elements.append(element)
        current_container.children_refs.append(element.ref)

    if not containers[0].children_refs and len(containers) > 1:
        containers.pop(0)
    snapshot = AccessibilitySnapshot(
        screen_id=compute_screen_id(xml_source),
        elements=elements,
        containers=containers,
    )
    return snapshot, {element.ref: element for element in elements}


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


def element_to_ref_entry(element: SnapshotElement) -> dict[str, Any]:
    center = element.bounds.center if element.bounds else None
    return {
        "ref": element.ref,
        "resource_id": element.resource_id,
        "accessibility_id": element.name if element.name_source == "content-desc" else "",
        "xpath": element.xpath,
        "bounds": str(element.bounds) if element.bounds else "",
        "center": center,
        "role": element.role,
        "name": element.name,
    }
