"""Shared snapshot utilities for the tree-first model.

This module retains only the lightweight building blocks still used by the
new ``NativeSnapshot`` model and the ref resolver:

- ``LocatorStrategy``: one Appium element-finding strategy
- ``RefEntry``: locator strategies + expected bounds for a ref
- ``parse_bounds``: parse an Android ``[x1,y1][x2,y2]`` bounds string
- ``compress_xml``: strip noisy default attributes from a UIAutomator XML dump

The legacy flat-model classes (``SnapshotElement``, ``SnapshotContainer``,
``SelectionContainer``, ``AccessibilitySnapshot``) and ``compute_screen_id``
have been removed; the tree-first model in ``core.native_snapshot`` replaces
them.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass


_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)]\[(\d+),(\d+)]")


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
        context: Appium context this ref belongs to (e.g. "NATIVE_APP", "CHROMIUM")
        source_type: "native" or "web"
        action_target_ref: optional ref of an ancestor that should receive the action
    """

    strategies: list[LocatorStrategy]
    expected_bounds: tuple[int, int, int, int]
    role: str
    name: str
    context: str = "NATIVE_APP"
    source_type: str = "native"
    action_target_ref: str | None = None


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
