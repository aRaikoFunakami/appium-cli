"""SnapshotGenerator: Appium XML page source to AccessibilitySnapshot.

Faithful port of smartestiroid's android/snapshot_generator.py.
Generates stable resource-id-derived refs, semantic region detection,
position hints, and multi-strategy RefEntry for each element.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from xml.etree import ElementTree as ET

from .snapshot import (
    AccessibilitySnapshot,
    LocatorStrategy,
    RefEntry,
    SelectionContainer,
    SnapshotContainer,
    SnapshotElement,
    compute_screen_id,
)


# ============================================================
# Constants
# ============================================================

_TAPPABLE_ATTRIBUTES = frozenset(
    {"clickable", "long-clickable", "checkable", "editable"}
)

_TEXT_DISPLAY_CLASSES = frozenset(
    {
        "android.widget.TextView",
        "android.widget.ImageView",
        "android.widget.Image",
    }
)

_CLASS_TO_ROLE: dict[str, str] = {
    "android.widget.Button": "button",
    "android.widget.ImageButton": "button",
    "android.widget.EditText": "textbox",
    "android.widget.CheckBox": "checkbox",
    "android.widget.Switch": "switch",
    "android.widget.ToggleButton": "switch",
    "android.widget.RadioButton": "radio",
    "android.widget.TextView": "text",
    "android.widget.ImageView": "image",
    "android.widget.Image": "image",
    "android.widget.Spinner": "select",
}

_TOOLBAR_CLASSES = frozenset(
    {
        "android.widget.Toolbar",
        "androidx.appcompat.widget.Toolbar",
        "android.support.v7.widget.Toolbar",
        "com.android.internal.widget.ActionBarContainer",
        "android.app.ActionBar",
    }
)

_LIST_CLASSES = frozenset(
    {
        "androidx.recyclerview.widget.RecyclerView",
        "android.support.v7.widget.RecyclerView",
        "android.widget.ListView",
        "android.widget.ScrollView",
        "android.widget.HorizontalScrollView",
        "androidx.core.widget.NestedScrollView",
    }
)

_OVERLAY_CLASSES = frozenset(
    {
        "android.app.AlertDialog",
        "android.widget.PopupWindow",
        "com.google.android.material.bottomsheet.BottomSheetDialog",
    }
)

_TAB_CLASSES = frozenset(
    {
        "com.google.android.material.bottomnavigation.BottomNavigationView",
        "android.widget.TabWidget",
        "com.google.android.material.tabs.TabLayout",
    }
)

_SELECTION_CONTAINER_CLASSES = frozenset(
    _TAB_CLASSES | {
        "android.widget.RadioGroup",
        "android.widget.Spinner",
        "com.google.android.material.button.MaterialButtonToggleGroup",
    }
)

_PACKAGE_PREFIX_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*:id/")

_SELECTED_INDICATOR_KEYWORDS: tuple[str, ...] = (
    "tab_under",
    "tab_indicator",
    "indicator",
    "selector_line",
    "_selected_line",
    "selected_underline",
)


# ============================================================
# SnapshotGenerator
# ============================================================


class SnapshotGenerator:
    """Appium XML page source to AccessibilitySnapshot converter.

    Attributes:
        screen_width: device screen width (px)
        screen_height: device screen height (px)
    """

    def __init__(
        self,
        screen_width: int = 1080,
        screen_height: int = 2340,
    ) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self._ref_counters: dict[str, int] = {}

    def generate(
        self,
        xml_source: str,
        app_info: str = "",
        scope: str = "full",
    ) -> tuple[AccessibilitySnapshot, dict[str, RefEntry]]:
        """Generate snapshot and ref mapping from XML.

        Args:
            xml_source: Appium driver.page_source XML
            app_info: package + activity string
            scope: scope filter ("full" / "topbar" / "list" etc.)

        Returns:
            Tuple of (AccessibilitySnapshot, ref -> RefEntry mapping)
        """
        self._ref_counters = {}

        root = ET.fromstring(xml_source)

        # Try to get screen dimensions from root node
        w = root.get("width")
        h = root.get("height")
        if w and h:
            self.screen_width = int(w)
            self.screen_height = int(h)

        # 1. Collect all extractable elements
        raw_elements = self._collect_elements(root)

        # 2. Detect semantic regions
        containers = self._detect_regions(root)

        # 3. Assign elements to containers
        self._assign_containers(raw_elements, containers)

        # 4. Assign position hints
        self._assign_position_hints(raw_elements, containers)

        # 5. Generate refs and build RefEntry map
        ref_map: dict[str, RefEntry] = {}
        for elem_info in raw_elements:
            ref = self._generate_ref(elem_info)
            elem_info["ref"] = ref
            ref_map[ref] = self._build_ref_entry(elem_info, ref)

        # 5b. Register container refs in ref_map
        for container in containers:
            if container.ref not in ref_map:
                ref_map[container.ref] = self._build_container_ref_entry(container)

        # 6. Build SnapshotElement list
        elements: list[SnapshotElement] = []
        for ei in raw_elements:
            elements.append(self._build_snapshot_element(ei))

        # 7. Update container children_refs
        self._update_container_children(containers, elements)

        # 8. Compute screen_id
        screen_id = compute_screen_id(elements)

        # 9. Detect alerts
        alerts = self._detect_alerts(root)

        # 10. Detect navigation
        nav = self._detect_nav(root)

        # 11. Extract selection containers
        selection_containers = self._extract_selection_containers(
            root, raw_elements, containers,
        )

        # 12. Extract selected labels and body texts
        selected_labels = self._extract_selected_labels(root)
        body_texts = self._extract_body_texts(root)

        snapshot = AccessibilitySnapshot(
            screen_id=screen_id,
            app_info=app_info,
            containers=containers,
            elements=elements,
            alerts=alerts,
            nav=nav,
            selection_containers=selection_containers,
            selected_labels=selected_labels,
            body_texts=body_texts,
        )

        # 13. Scope filter
        if scope != "full":
            snapshot = self._apply_scope(snapshot, scope)

        return snapshot, ref_map

    # ────────────────────────────────────────
    # Selection containers
    # ────────────────────────────────────────

    def _extract_selection_containers(
        self,
        root: ET.Element,
        raw_elements: list[dict[str, Any]],
        containers: list[SnapshotContainer],
    ) -> list[SelectionContainer]:
        """Extract SelectionContainer (TabLayout / Spinner / RadioGroup etc.)."""
        bounds_to_ref: dict[tuple[int, int, int, int], str] = {}
        for ei in raw_elements:
            b = ei.get("bounds")
            if b and "ref" in ei:
                bounds_to_ref[tuple(b)] = ei["ref"]
        for container in containers:
            bounds = getattr(container, "_bounds", None)
            if bounds and container.ref:
                bounds_to_ref.setdefault(tuple(bounds), container.ref)

        results: list[SelectionContainer] = []
        for node in root.iter():
            cls = self._get_class(node)
            if not cls:
                continue
            resource_id = node.get("resource-id", "").lower()

            is_standard = cls in _SELECTION_CONTAINER_CLASSES
            is_recycler_tab = (
                "RecyclerView" in cls
                and ("tab" in resource_id or "nav" in resource_id)
            )
            if not (is_standard or is_recycler_tab):
                continue

            container_bounds = self._parse_bounds(node.get("bounds", ""))
            container_ref = bounds_to_ref.get(container_bounds, "") if container_bounds else ""
            if not container_ref and resource_id:
                clean_id = _PACKAGE_PREFIX_RE.sub("", resource_id)
                container_ref = self._to_snake_case(clean_id)

            options: list[dict[str, Any]] = []
            selected_index: int | None = None

            target_children = (
                list(node) if is_standard else self._collect_recycler_options(node)
            )

            for i, child in enumerate(target_children):
                child_bounds = self._parse_bounds(child.get("bounds", ""))
                child_ref = bounds_to_ref.get(child_bounds, "") if child_bounds else ""
                if not child_ref:
                    continue
                child_text = self._extract_node_label(child)
                is_selected = self._is_selected_option(child)
                options.append({
                    "ref": child_ref,
                    "name": child_text,
                    "selected": is_selected,
                })
                if is_selected:
                    selected_index = i

            if options:
                results.append(SelectionContainer(
                    container_ref=container_ref,
                    container_class=cls,
                    options=options,
                    selected_index=selected_index,
                ))

        return results

    @staticmethod
    def _collect_recycler_options(container: ET.Element) -> list[ET.Element]:
        results: list[ET.Element] = []
        for node in container.iter():
            if node is container:
                continue
            if node.get("clickable", "false") == "true":
                results.append(node)
        return results

    @staticmethod
    def _extract_node_label(node: ET.Element) -> str:
        direct = node.get("text", "").strip() or node.get("content-desc", "").strip()
        if direct:
            return direct
        for child in node.iter():
            if child is node:
                continue
            text = child.get("text", "").strip() or child.get("content-desc", "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _is_selected_option(node: ET.Element) -> bool:
        if node.get("selected", "false") == "true" or node.get("checked", "false") == "true":
            return True
        for child in node.iter():
            if child is node:
                continue
            if child.get("selected", "false") == "true" or child.get("checked", "false") == "true":
                return True
            resource_id = child.get("resource-id", "").lower()
            if resource_id and any(
                token in resource_id for token in ("indicator", "underline", "under_line", "tab_under")
            ):
                if child.get("displayed", "true") != "false":
                    return True
        return False

    # ────────────────────────────────────────
    # Element collection
    # ────────────────────────────────────────

    def _collect_elements(self, root: ET.Element) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        self._walk_tree(root, results)
        return results

    def _walk_tree(
        self, node: ET.Element, results: list[dict[str, Any]], depth: int = 0
    ) -> None:
        if self._is_extractable(node):
            info = self._extract_element_info(node)
            if info:
                results.append(info)
        for child in node:
            self._walk_tree(child, results, depth + 1)

    def _get_class(self, node: ET.Element) -> str:
        cls = node.get("class", "")
        if cls:
            return cls
        tag = node.tag
        if tag and "." in tag:
            return tag
        return ""

    def _is_extractable(self, node: ET.Element) -> bool:
        enabled = node.get("enabled", "false") == "true"
        enabled_missing = node.get("enabled") is None
        effectively_enabled = enabled or enabled_missing

        if effectively_enabled:
            for attr in _TAPPABLE_ATTRIBUTES:
                if node.get(attr, "false") == "true":
                    return True

        cls = self._get_class(node)
        text = node.get("text", "").strip()
        content_desc = node.get("content-desc", "").strip()
        if text or content_desc:
            if cls in _TEXT_DISPLAY_CLASSES or effectively_enabled:
                return True

        return False

    def _extract_element_info(self, node: ET.Element) -> dict[str, Any] | None:
        cls = self._get_class(node)
        text = node.get("text", "").strip()
        content_desc = node.get("content-desc", "").strip()
        resource_id = node.get("resource-id", "").strip()
        bounds = self._parse_bounds(node.get("bounds", ""))

        if not bounds:
            return None

        role = self._determine_role(node, cls)
        name = content_desc or text
        name_source = (
            "content-desc" if content_desc else ("text" if text else None)
        )
        value = self._determine_value(node, role, text, content_desc)
        elem_state = self._collect_state(node)

        is_interactive = any(
            node.get(attr, "false") == "true" for attr in _TAPPABLE_ATTRIBUTES
        )

        return {
            "class": cls,
            "role": role,
            "name": name,
            "value": value,
            "state": elem_state,
            "bounds": bounds,
            "resource_id": resource_id,
            "content_desc": content_desc,
            "text": text,
            "name_source": name_source,
            "is_interactive": is_interactive,
            "container_ref": None,
            "position_hint": None,
            "node": node,
        }

    def _determine_role(self, node: ET.Element, cls: str) -> str:
        if cls in _CLASS_TO_ROLE:
            role = _CLASS_TO_ROLE[cls]
            if role == "image" and node.get("clickable", "false") == "true":
                return "button"
            return role
        if "Tab" in cls:
            return "tab"
        if node.get("clickable", "false") == "true":
            return "button"
        if node.get("text", "").strip() or node.get("content-desc", "").strip():
            return "text"
        return "text"

    def _determine_value(
        self, node: ET.Element, role: str, text: str, content_desc: str
    ) -> str | None:
        if role == "textbox":
            return text
        if role in ("switch", "checkbox", "radio"):
            checked = node.get("checked", "false")
            return "on" if checked == "true" else "off"
        if role == "text" and content_desc and text and text != content_desc:
            return text
        return None

    def _collect_state(self, node: ET.Element) -> list[str]:
        state: list[str] = []
        enabled_attr = node.get("enabled")
        if enabled_attr == "true" or enabled_attr is None:
            state.append("enabled")
        else:
            state.append("disabled")
        if node.get("selected", "false") == "true":
            state.append("selected")
        if node.get("checked", "false") == "true":
            state.append("checked")
        if node.get("focused", "false") == "true":
            state.append("focused")
        return state

    # ────────────────────────────────────────
    # Region detection
    # ────────────────────────────────────────

    def _detect_regions(self, root: ET.Element) -> list[SnapshotContainer]:
        containers: list[SnapshotContainer] = []
        self._scan_for_regions(root, containers)

        if not containers:
            content_container = SnapshotContainer(
                ref="content_main",
                region="content",
                title=None,
                children_refs=[],
            )
            content_container._bounds = (0, 0, self.screen_width, self.screen_height)  # type: ignore[attr-defined]
            content_container._resource_id = ""  # type: ignore[attr-defined]
            containers.append(content_container)

        return containers

    def _scan_for_regions(
        self, node: ET.Element, containers: list[SnapshotContainer]
    ) -> None:
        cls = self._get_class(node)
        resource_id = node.get("resource-id", "")
        bounds = self._parse_bounds(node.get("bounds", ""))

        # topbar
        if self._is_toolbar(cls, resource_id, bounds):
            title = self._extract_toolbar_title(node)
            ref = self._make_container_ref("topbar", resource_id)
            c = SnapshotContainer(ref=ref, region="topbar", title=title, children_refs=[])
            c._bounds = bounds  # type: ignore[attr-defined]
            c._resource_id = resource_id  # type: ignore[attr-defined]
            containers.append(c)
            return

        # list
        is_scrollable = node.get("scrollable", "false") == "true"
        if cls in _LIST_CLASSES or is_scrollable:
            title = self._find_nearby_title(node)
            ref = self._make_container_ref("list", resource_id)
            direction = self._infer_scroll_direction(cls, node, bounds)
            c = SnapshotContainer(
                ref=ref,
                region="list",
                title=title,
                children_refs=[],
                scrollable=is_scrollable,
                scroll_direction=direction,
            )
            c._bounds = bounds  # type: ignore[attr-defined]
            c._resource_id = resource_id  # type: ignore[attr-defined]
            containers.append(c)
            is_list_node = True
        else:
            is_list_node = False

        # overlay/dialog
        if not is_list_node and (
            cls in _OVERLAY_CLASSES or self._looks_like_overlay(node, resource_id, bounds)
        ):
            title = self._extract_dialog_title(node)
            ref = self._make_container_ref("overlay", resource_id)
            c = SnapshotContainer(ref=ref, region="overlay", title=title, children_refs=[])
            c._bounds = bounds  # type: ignore[attr-defined]
            c._resource_id = resource_id  # type: ignore[attr-defined]
            containers.append(c)
            return

        # tabs
        if cls in _TAB_CLASSES or (
            bounds
            and bounds[1] > self.screen_height * 0.85
            and "nav" in resource_id.lower()
        ):
            ref = self._make_container_ref("tabs", resource_id)
            c = SnapshotContainer(ref=ref, region="tabs", title=None, children_refs=[])
            c._bounds = bounds  # type: ignore[attr-defined]
            c._resource_id = resource_id  # type: ignore[attr-defined]
            containers.append(c)
            return

        for child in node:
            self._scan_for_regions(child, containers)

    def _infer_scroll_direction(
        self,
        cls: str,
        node: ET.Element,
        bounds: tuple[int, int, int, int] | None,
    ) -> str:
        if "HorizontalScrollView" in cls:
            return "horizontal"
        if cls in (
            "android.widget.ScrollView",
            "androidx.core.widget.NestedScrollView",
            "android.widget.ListView",
        ):
            return "vertical"

        child_bounds = []
        for child in node:
            cb = self._parse_bounds(child.get("bounds", ""))
            if cb:
                child_bounds.append(cb)
        if len(child_bounds) >= 2:
            b0, b1 = child_bounds[0], child_bounds[1]
            x_diff = abs(b1[0] - b0[0])
            y_diff = abs(b1[1] - b0[1])
            if x_diff > y_diff:
                return "horizontal"
            else:
                return "vertical"

        if bounds:
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            if width > 0 and height > 0:
                if width / height > 3:
                    return "horizontal"
                elif height / width > 2:
                    return "vertical"

        return ""

    def _is_toolbar(
        self, cls: str, resource_id: str, bounds: tuple[int, int, int, int] | None
    ) -> bool:
        if cls in _TOOLBAR_CLASSES:
            return True
        if "toolbar" in resource_id.lower() and bounds:
            return bounds[1] < self.screen_height * 0.15
        return False

    def _looks_like_overlay(
        self,
        node: ET.Element,
        resource_id: str,
        bounds: tuple[int, int, int, int] | None,
    ) -> bool:
        rid_lower = resource_id.lower()
        return any(
            kw in rid_lower
            for kw in ("dialog", "popup", "promo", "overlay", "bottomsheet", "signin")
        )

    def _extract_toolbar_title(self, node: ET.Element) -> str | None:
        for child in node.iter():
            text = child.get("text", "").strip()
            cls = child.get("class", "")
            if text and "TextView" in cls:
                return text
        return None

    def _extract_dialog_title(self, node: ET.Element) -> str | None:
        for child in node.iter():
            text = child.get("text", "").strip()
            if text:
                return text
        return None

    def _find_nearby_title(self, node: ET.Element) -> str | None:
        for child in node:
            text = child.get("text", "").strip()
            if text:
                return text
        return None

    def _make_container_ref(self, region: str, resource_id: str) -> str:
        if resource_id:
            clean_id = _PACKAGE_PREFIX_RE.sub("", resource_id)
            clean_id = self._to_snake_case(clean_id)
            return clean_id

        key = f"_container_{region}"
        count = self._ref_counters.get(key, 0) + 1
        self._ref_counters[key] = count
        if count == 1:
            return region
        return f"{region}_{count}"

    # ────────────────────────────────────────
    # Container assignment / position hints
    # ────────────────────────────────────────

    def _assign_containers(
        self,
        elements: list[dict[str, Any]],
        containers: list[SnapshotContainer],
    ) -> None:
        for elem in elements:
            eb = elem["bounds"]
            best_container: SnapshotContainer | None = None
            best_area = float("inf")

            for container in containers:
                cb = getattr(container, "_bounds", None)
                if cb is None:
                    continue
                if self._contains(cb, eb):
                    area = (cb[2] - cb[0]) * (cb[3] - cb[1])
                    if area < best_area:
                        best_area = area
                        best_container = container

            if best_container:
                elem["container_ref"] = best_container.ref

    def _assign_position_hints(
        self,
        elements: list[dict[str, Any]],
        containers: list[SnapshotContainer],
    ) -> None:
        scrollable_refs = {c.ref for c in containers if c.scrollable}

        by_container: dict[str, list[dict[str, Any]]] = {}
        for elem in elements:
            cref = elem.get("container_ref")
            if cref:
                by_container.setdefault(cref, []).append(elem)

        for _cref, group in by_container.items():
            if len(group) <= 1:
                continue
            if _cref in scrollable_refs:
                continue

            by_role: dict[str, list[dict[str, Any]]] = {}
            for e in group:
                by_role.setdefault(e["role"], []).append(e)

            for _role, role_group in by_role.items():
                if len(role_group) <= 1:
                    continue
                sorted_by_x = sorted(role_group, key=lambda e: e["bounds"][0])
                sorted_by_x[-1]["position_hint"] = "right-most"
                sorted_by_x[0]["position_hint"] = "left-most"

    # ────────────────────────────────────────
    # Ref generation
    # ────────────────────────────────────────

    def _generate_ref(self, elem_info: dict[str, Any]) -> str:
        resource_id = elem_info.get("resource_id", "")
        content_desc = elem_info.get("content_desc", "")
        name = elem_info.get("name", "")
        role = elem_info.get("role", "text")

        # Priority 1: resource-id
        if resource_id:
            base = _PACKAGE_PREFIX_RE.sub("", resource_id)
            base = self._to_snake_case(base)
            return self._unique_ref(base)

        # Priority 2: content-desc
        if content_desc:
            base = self._to_snake_case(content_desc)[:16]
            return self._unique_ref(base)

        # Priority 3: role + name
        if name:
            role_prefix = self._role_prefix(role)
            name_part = self._to_snake_case(name)[:16]
            base = f"{role_prefix}_{name_part}"
            return self._unique_ref(base)

        # Priority 4: role only
        role_prefix = self._role_prefix(role)
        return self._unique_ref(role_prefix)

    def _unique_ref(self, base: str) -> str:
        if not base:
            base = "elem"

        count = self._ref_counters.get(base, 0) + 1
        self._ref_counters[base] = count

        if count == 1:
            return base
        return f"{base}_{count}"

    def _role_prefix(self, role: str) -> str:
        prefixes = {
            "button": "btn",
            "textbox": "input",
            "checkbox": "chk",
            "switch": "sw",
            "radio": "radio",
            "text": "txt",
            "image": "img",
            "tab": "tab",
            "select": "sel",
            "listitem": "item",
        }
        return prefixes.get(role, role)

    # ────────────────────────────────────────
    # RefEntry generation
    # ────────────────────────────────────────

    def _build_ref_entry(self, elem_info: dict[str, Any], ref: str) -> RefEntry:
        strategies: list[LocatorStrategy] = []
        resource_id = elem_info.get("resource_id", "")
        content_desc = elem_info.get("content_desc", "")
        text = elem_info.get("text", "")
        cls = elem_info.get("class", "")

        if resource_id:
            strategies.append(LocatorStrategy(by="id", value=resource_id))

        if content_desc:
            strategies.append(
                LocatorStrategy(by="accessibility_id", value=content_desc)
            )

        if text:
            strategies.append(
                LocatorStrategy(
                    by="xpath",
                    value=f"//{cls}[@text='{text}']" if cls else f"//*[@text='{text}']",
                )
            )

        bounds = elem_info["bounds"]
        cx = (bounds[0] + bounds[2]) // 2
        cy = (bounds[1] + bounds[3]) // 2
        strategies.append(
            LocatorStrategy(by="coordinates", value=f"{cx},{cy}")
        )

        return RefEntry(
            strategies=strategies,
            expected_bounds=bounds,
            role=elem_info["role"],
            name=elem_info["name"],
        )

    def _build_container_ref_entry(self, container: SnapshotContainer) -> RefEntry:
        strategies: list[LocatorStrategy] = []
        resource_id: str = getattr(container, "_resource_id", "")
        bounds: tuple[int, int, int, int] | None = getattr(
            container, "_bounds", None
        )

        if resource_id:
            strategies.append(LocatorStrategy(by="id", value=resource_id))

        if bounds:
            cx = (bounds[0] + bounds[2]) // 2
            cy = (bounds[1] + bounds[3]) // 2
            strategies.append(
                LocatorStrategy(by="coordinates", value=f"{cx},{cy}")
            )

        return RefEntry(
            strategies=strategies,
            expected_bounds=bounds or (0, 0, 0, 0),
            role="container",
            name=container.title or container.ref,
        )

    # ────────────────────────────────────────
    # SnapshotElement generation
    # ────────────────────────────────────────

    def _build_snapshot_element(self, elem_info: dict[str, Any]) -> SnapshotElement:
        return SnapshotElement(
            ref=elem_info["ref"],
            role=elem_info["role"],
            name=elem_info["name"],
            value=elem_info.get("value"),
            state=elem_info.get("state", []),
            bounds=elem_info["bounds"],
            container_ref=elem_info.get("container_ref"),
            position_hint=elem_info.get("position_hint"),
            name_source=elem_info.get("name_source"),
        )

    # ────────────────────────────────────────
    # Container children_refs update
    # ────────────────────────────────────────

    def _update_container_children(
        self,
        containers: list[SnapshotContainer],
        elements: list[SnapshotElement],
    ) -> None:
        for container in containers:
            container.children_refs = [
                e.ref for e in elements if e.container_ref == container.ref
            ]

    # ────────────────────────────────────────
    # Alerts / navigation detection
    # ────────────────────────────────────────

    def _detect_alerts(self, root: ET.Element) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        for node in root.iter():
            cls = self._get_class(node)
            if "Toast" in cls or "Snackbar" in cls:
                text = self._extract_dialog_title(node) or "notification"
                alerts.append({"type": "toast", "message": text})
            elif "AlertDialog" in cls:
                text = self._extract_dialog_title(node) or "dialog"
                alerts.append({"type": "dialog", "message": text})
        return alerts

    def _detect_nav(self, root: ET.Element) -> dict[str, Any]:
        has_back = False
        for node in root.iter():
            content_desc = node.get("content-desc", "").lower()
            resource_id = node.get("resource-id", "").lower()
            if "back" in content_desc or "navigate up" in content_desc:
                has_back = True
            if "back" in resource_id:
                has_back = True
        return {"back": has_back}

    # ────────────────────────────────────────
    # Scope filter
    # ────────────────────────────────────────

    def _apply_scope(
        self, snapshot: AccessibilitySnapshot, scope: str
    ) -> AccessibilitySnapshot:
        filtered_containers = snapshot._filter_containers(scope)
        allowed_refs: set[str] = set()
        for c in filtered_containers:
            allowed_refs.update(c.children_refs)

        if scope.startswith("near:"):
            target_ref = scope[5:]
            allowed_refs.add(target_ref)

        if scope == "inputs":
            filtered_elements = [
                e for e in snapshot.elements if e.role == "textbox"
            ]
        elif allowed_refs:
            filtered_elements = [
                e for e in snapshot.elements if e.ref in allowed_refs
            ]
        else:
            filtered_elements = []

        return AccessibilitySnapshot(
            screen_id=snapshot.screen_id,
            app_info=snapshot.app_info,
            containers=filtered_containers,
            elements=filtered_elements,
            alerts=snapshot.alerts,
            nav=snapshot.nav,
            selected_labels=snapshot.selected_labels,
            body_texts=snapshot.body_texts,
        )

    # ────────────────────────────────────────
    # Selected labels / body texts (Phase H)
    # ────────────────────────────────────────

    def _extract_selected_labels(self, root: ET.Element) -> list[str]:
        labels: list[str] = []
        nodes = list(root.iter())

        def _nearest_text(
            target_bounds: tuple[int, int, int, int],
            y_band: int = 200,
            x_max: int = 400,
        ) -> str | None:
            tx1, ty1, tx2, ty2 = target_bounds
            tcx = (tx1 + tx2) / 2
            tcy = (ty1 + ty2) / 2
            best: tuple[float, str] | None = None
            for n in nodes:
                cls = n.attrib.get("class", "")
                text = n.attrib.get("text", "").strip()
                if "TextView" not in cls or not text:
                    continue
                bb = self._parse_bounds(n.attrib.get("bounds", ""))
                if not bb:
                    continue
                cx = (bb[0] + bb[2]) / 2
                cy = (bb[1] + bb[3]) / 2
                if abs(cy - tcy) > y_band:
                    continue
                d = abs(cx - tcx)
                if d > x_max:
                    continue
                if best is None or d < best[0]:
                    best = (d, text)
            return best[1] if best else None

        # 1. selected="true" + clickable
        for n in nodes:
            if n.attrib.get("selected") != "true":
                continue
            if n.attrib.get("clickable") != "true":
                continue
            t = n.attrib.get("text", "").strip()
            if t:
                labels.append(t)
                continue
            bb = self._parse_bounds(n.attrib.get("bounds", ""))
            if bb:
                near = _nearest_text(bb)
                if near:
                    labels.append(near)

        # 2. Indicator / underline view -> nearest TextView
        for n in nodes:
            rid = n.attrib.get("resource-id", "") or ""
            if not any(k in rid for k in _SELECTED_INDICATOR_KEYWORDS):
                continue
            bb = self._parse_bounds(n.attrib.get("bounds", ""))
            if not bb:
                continue
            near = _nearest_text(bb)
            if near:
                labels.append(near)

        # Deduplicate preserving order
        seen: set[str] = set()
        out: list[str] = []
        for label in labels:
            if label not in seen:
                seen.add(label)
                out.append(label)
        return out

    def _extract_body_texts(self, root: ET.Element, limit: int = 20) -> list[str]:
        parent: dict[ET.Element, ET.Element] = {
            c: p for p in root.iter() for c in p
        }

        def _has_clickable_ancestor(n: ET.Element) -> bool:
            p = parent.get(n)
            while p is not None:
                if p.attrib.get("clickable") == "true":
                    return True
                p = parent.get(p)
            return False

        out: list[str] = []
        seen: set[str] = set()
        for n in root.iter():
            if "TextView" not in n.attrib.get("class", ""):
                continue
            t = n.attrib.get("text", "").strip()
            if not t or t in seen:
                continue
            if _has_clickable_ancestor(n):
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= limit:
                break
        return out

    # ────────────────────────────────────────
    # Utility
    # ────────────────────────────────────────

    @staticmethod
    def _parse_bounds(bounds_str: str) -> tuple[int, int, int, int] | None:
        if not bounds_str:
            return None
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
        if not match:
            return None
        return (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
        )

    @staticmethod
    def _contains(
        outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]
    ) -> bool:
        return (
            outer[0] <= inner[0]
            and outer[1] <= inner[1]
            and outer[2] >= inner[2]
            and outer[3] >= inner[3]
        )

    @staticmethod
    def _to_snake_case(text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        text = re.sub(r"[^\w]", "_", text, flags=re.UNICODE)
        text = re.sub(r"_+", "_", text)
        text = text.strip("_")
        return text.lower()
