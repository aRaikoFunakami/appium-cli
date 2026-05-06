"""NativeSnapshotGenerator: tree-first Appium XML to NativeSnapshot.

Implements the 7-pass pipeline documented in the appium-cli native tree-first
plan (Phase 1b):

    1. parse_xml             - XML to internal _RawNode tree
    2. infer_semantics       - role/name/value/state/scrollable hints
    3. prune_and_collapse    - drop noise, collapse transparent wrappers
    4. detect_containers     - classify groups (topbar, list, tabs, dialog...)
    5. assign_refs           - stable, attribute-derived refs
    6. build_locator_strategies
    7. (screen_id is computed by NativeSnapshot.from_root)

Designed to be a faithful tree-first replacement for the older flat
``SnapshotGenerator``: ref derivation, role inference, and container heuristics
are ported from that module.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree as ET

from .native_snapshot import NativeSnapshot, NativeSnapshotNode
from .snapshot import LocatorStrategy, parse_bounds


# ============================================================
# Constants (ported from snapshot_generator.py for self-containment)
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
    _TAB_CLASSES
    | {
        "android.widget.RadioGroup",
        "android.widget.Spinner",
        "com.google.android.material.button.MaterialButtonToggleGroup",
    }
)

_GENERIC_GROUP_CLASSES = frozenset(
    {
        "android.widget.LinearLayout",
        "android.widget.FrameLayout",
        "android.widget.RelativeLayout",
        "android.view.ViewGroup",
        "androidx.constraintlayout.widget.ConstraintLayout",
    }
)

_HORIZONTAL_SCROLL_CLASSES = frozenset(
    {
        "android.widget.HorizontalScrollView",
    }
)

_PACKAGE_PREFIX_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*:id/")

_DESCRIPTIVE_REF_MAX_LENGTH = 128

_ROLE_PREFIXES: dict[str, str] = {
    "button": "btn",
    "textbox": "input",
    "checkbox": "chk",
    "switch": "sw",
    "radio": "radio",
    "text": "txt",
    "image": "img",
    "tab": "tab",
    "select": "sel",
    "row": "row",
    "toolbar": "bar",
    "list": "list",
    "overlay": "ovl",
    "tabs": "tabs",
    "selection": "sel",
    "container": "grp",
}


# ============================================================
# Internal mutable node types
# ============================================================


@dataclass
class _RawNode:
    """Faithful copy of one Appium UI XML node."""

    class_name: str = ""
    package: str = ""
    text: str = ""
    resource_id: str = ""
    content_desc: str = ""
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    clickable: bool = False
    long_clickable: bool = False
    checkable: bool = False
    checked: bool = False
    enabled: bool = True
    focusable: bool = False
    focused: bool = False
    selected: bool = False
    scrollable: bool = False
    password: bool = False
    children: list["_RawNode"] = field(default_factory=list)


@dataclass
class _SemanticNode:
    """Mutable working node used between passes 2 and 5."""

    raw: _RawNode
    role: str = "container"
    name: str = ""
    value: str | None = None
    state: list[str] = field(default_factory=list)
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    class_name: str = ""
    resource_id: str = ""
    content_desc: str = ""
    text: str = ""
    scrollable: bool = False
    scroll_direction: str = ""
    is_actionable: bool = False
    is_editable: bool = False
    is_text_leaf: bool = False
    children: list["_SemanticNode"] = field(default_factory=list)
    parent: "_SemanticNode | None" = None


# ============================================================
# Generator
# ============================================================


class NativeSnapshotGenerator:
    """Tree-first generator: Appium page source XML to ``NativeSnapshot``.

    The generator runs seven passes; each pass is a small, well-named method so
    that downstream phases can compose or mock individual stages.
    """

    def __init__(self, *, max_nodes: int | None = None) -> None:
        self.max_nodes = max_nodes
        self._ref_counters: dict[str, int] = {}

    # ----------------------------------------------------------
    # Public entry point
    # ----------------------------------------------------------

    def generate(
        self,
        xml_source: str,
        *,
        app_info: str = "",
        nav: dict[str, Any] | None = None,
        alerts: list[dict[str, Any]] | None = None,
        context: str = "NATIVE_APP",
    ) -> NativeSnapshot:
        """Run the 7-pass pipeline and return a populated ``NativeSnapshot``."""
        self._ref_counters = {}

        raw_root = self._parse_xml(xml_source)
        inferred = self._infer_semantics(raw_root)
        pruned, truncated = self._prune_and_collapse(inferred)
        self._detect_containers(pruned)
        self._assign_refs_and_action_targets(pruned)
        self._build_locator_strategies(pruned)
        return NativeSnapshot.from_root(
            root=pruned,
            app_info=app_info,
            nav=nav,
            alerts=alerts,
            truncated=truncated,
            context=context,
        )

    # ----------------------------------------------------------
    # Pass 1: parse XML to _RawNode tree
    # ----------------------------------------------------------

    def _parse_xml(self, xml_source: str) -> _RawNode:
        """Parse Appium page source XML into an internal ``_RawNode`` tree.

        The outer ``<hierarchy>`` element is discarded; parsing starts at its
        first child node. Raises ``ValueError`` if the XML cannot be parsed or
        contains no usable root.
        """
        try:
            root = ET.fromstring(xml_source)
        except ET.ParseError as exc:
            raise ValueError("Failed to parse XML page source") from exc

        # Skip <hierarchy> and start at its first child.
        if root.tag.lower() == "hierarchy":
            inner = list(root)
            if not inner:
                raise ValueError("Failed to parse XML page source")
            start = inner[0]
        else:
            start = root

        return self._build_raw(start)

    def _build_raw(self, node: ET.Element) -> _RawNode:
        cls = node.get("class") or (node.tag if "." in node.tag else "")
        bounds = parse_bounds(node.get("bounds")) or (0, 0, 0, 0)
        raw = _RawNode(
            class_name=cls,
            package=node.get("package", ""),
            text=(node.get("text") or "").strip(),
            resource_id=(node.get("resource-id") or "").strip(),
            content_desc=(node.get("content-desc") or "").strip(),
            bounds=bounds,
            clickable=node.get("clickable", "false") == "true",
            long_clickable=node.get("long-clickable", "false") == "true",
            checkable=node.get("checkable", "false") == "true",
            checked=node.get("checked", "false") == "true",
            enabled=node.get("enabled", "true") != "false",
            focusable=node.get("focusable", "false") == "true",
            focused=node.get("focused", "false") == "true",
            selected=node.get("selected", "false") == "true",
            scrollable=node.get("scrollable", "false") == "true",
            password=node.get("password", "false") == "true",
        )
        for child in node:
            raw.children.append(self._build_raw(child))
        return raw

    # ----------------------------------------------------------
    # Pass 2: semantic inference
    # ----------------------------------------------------------

    def _infer_semantics(self, raw_root: _RawNode) -> _SemanticNode:
        """Walk raw tree, building ``_SemanticNode`` with role/name/value/state."""
        return self._build_semantic(raw_root, parent=None)

    def _build_semantic(
        self, raw: _RawNode, parent: _SemanticNode | None
    ) -> _SemanticNode:
        children_sem = [self._build_semantic(c, None) for c in raw.children]

        role = self._infer_role(raw, children_sem)
        name = self._infer_name(raw)
        value = self._infer_value(raw, role)
        state = self._infer_state(raw)

        is_editable = role == "textbox"
        is_actionable = (
            raw.clickable
            or raw.long_clickable
            or raw.checkable
            or is_editable
        )
        is_text_leaf = (
            not is_actionable
            and not raw.scrollable
            and bool(name)
            and not children_sem
        )

        scroll_direction = self._infer_scroll_direction(raw) if raw.scrollable else ""

        node = _SemanticNode(
            raw=raw,
            role=role,
            name=name,
            value=value,
            state=state,
            bounds=raw.bounds,
            class_name=raw.class_name,
            resource_id=raw.resource_id,
            content_desc=raw.content_desc,
            text=raw.text,
            scrollable=raw.scrollable,
            scroll_direction=scroll_direction,
            is_actionable=is_actionable,
            is_editable=is_editable,
            is_text_leaf=is_text_leaf,
            children=children_sem,
            parent=parent,
        )
        for child in children_sem:
            child.parent = node
        return node

    @staticmethod
    def _infer_role(raw: _RawNode, children: list[_SemanticNode]) -> str:
        cls = raw.class_name
        if cls in _TOOLBAR_CLASSES:
            return "toolbar"
        if cls in _OVERLAY_CLASSES:
            return "overlay"
        if cls in _TAB_CLASSES:
            return "tabs"
        if cls in _SELECTION_CONTAINER_CLASSES:
            return "selection"
        if cls in _LIST_CLASSES:
            return "list"

        if cls in _CLASS_TO_ROLE:
            role = _CLASS_TO_ROLE[cls]
            if role == "image" and raw.clickable:
                return "button"
            return role

        if "Tab" in cls and (raw.clickable or raw.checkable):
            return "tab"

        if raw.clickable and cls in _GENERIC_GROUP_CLASSES:
            for child in children:
                if child.role in ("text", "image") or child.text or child.content_desc:
                    return "row"
            return "button"

        if raw.clickable:
            return "button"

        if raw.text or raw.content_desc:
            return "text"

        return "container"

    @staticmethod
    def _infer_name(raw: _RawNode) -> str:
        candidate = raw.text or raw.content_desc
        if not candidate:
            return ""
        return unicodedata.normalize("NFKC", candidate).strip()

    @staticmethod
    def _infer_value(raw: _RawNode, role: str) -> str | None:
        if raw.password:
            return "***"
        if role == "textbox":
            return raw.text
        if raw.checkable:
            return "true" if raw.checked else "false"
        if role in ("switch", "radio"):
            return "on" if raw.checked else "off"
        return None

    @staticmethod
    def _infer_state(raw: _RawNode) -> list[str]:
        state: list[str] = []
        if raw.selected:
            state.append("selected")
        if raw.checked:
            state.append("checked")
        if not raw.enabled:
            state.append("disabled")
        if raw.focused:
            state.append("focused")
        return state

    @staticmethod
    def _infer_scroll_direction(raw: _RawNode) -> str:
        cls = raw.class_name
        if cls in _HORIZONTAL_SCROLL_CLASSES:
            return "horizontal"
        if "Horizontal" in cls:
            return "horizontal"
        return "vertical"

    # ----------------------------------------------------------
    # Pass 3: prune and collapse
    # ----------------------------------------------------------

    def _prune_and_collapse(
        self, root: _SemanticNode
    ) -> tuple[NativeSnapshotNode, bool]:
        """Drop noise nodes, collapse transparent wrappers, enforce ``max_nodes``.

        Returns the freshly built ``NativeSnapshotNode`` tree and a ``truncated``
        flag indicating whether ``max_nodes`` triggered any omissions.
        """
        pruned_sem = self._prune_subtree(root)
        if pruned_sem is None:
            # Always keep at least the root, even if it was prunable.
            pruned_sem = root
            pruned_sem.children = []

        snap_root = self._to_snapshot_node(pruned_sem)
        truncated = False
        if self.max_nodes is not None:
            truncated = self._enforce_max_nodes(snap_root, self.max_nodes)
        return snap_root, truncated

    def _prune_subtree(self, node: _SemanticNode) -> _SemanticNode | None:
        # Recurse first (bottom-up).
        new_children: list[_SemanticNode] = []
        for child in node.children:
            kept = self._prune_subtree(child)
            if kept is None:
                continue
            # Collapse transparent wrappers: replace with their children.
            if self._is_transparent_wrapper(kept):
                new_children.extend(kept.children)
            else:
                new_children.append(kept)
        node.children = new_children
        for child in node.children:
            child.parent = node

        if self._should_prune(node):
            return None
        return node

    @staticmethod
    def _is_transparent_wrapper(node: _SemanticNode) -> bool:
        if node.role != "container":
            return False
        if node.name or node.state:
            return False
        if node.is_actionable or node.scrollable:
            return False
        return bool(node.children)

    @staticmethod
    def _should_prune(node: _SemanticNode) -> bool:
        x1, y1, x2, y2 = node.bounds
        zero_sized = x1 == x2 or y1 == y2
        offscreen = x1 >= 10000 or y1 >= 10000 or x2 <= 0 or y2 <= 0
        if (zero_sized or offscreen) and not node.children:
            return True

        if (
            not node.is_actionable
            and not node.is_editable
            and not node.scrollable
            and not node.name
            and not node.state
            and not node.children
        ):
            return True
        return False

    def _to_snapshot_node(self, sem: _SemanticNode) -> NativeSnapshotNode:
        # Single-child promotion: a generic wrapper with exactly one surviving
        # child becomes that child.
        if (
            sem.role == "container"
            and not sem.name
            and not sem.state
            and not sem.is_actionable
            and not sem.scrollable
            and len(sem.children) == 1
        ):
            return self._to_snapshot_node(sem.children[0])

        node = NativeSnapshotNode(
            role=sem.role,
            name=sem.name,
            class_name=sem.class_name,
            resource_id=sem.resource_id,
            content_desc=sem.content_desc,
            text=sem.text,
            value=sem.value,
            state=list(sem.state),
            bounds=sem.bounds,
            scrollable=sem.scrollable,
            scroll_direction=sem.scroll_direction,
        )
        for child in sem.children:
            node.children.append(self._to_snapshot_node(child))
        return node

    def _enforce_max_nodes(self, root: NativeSnapshotNode, budget: int) -> bool:
        def total() -> int:
            return sum(1 for _ in root.iter_nodes())

        if total() <= budget:
            return False

        # Repeatedly mark the deepest non-actionable subtree as omitted until
        # the budget is satisfied.
        truncated = False
        guard = 1000
        while total() > budget and guard > 0:
            guard -= 1
            target = self._deepest_omittable(root)
            if target is None:
                break
            target.omitted = True
            target.children = []
            truncated = True
        return truncated

    @staticmethod
    def _deepest_omittable(root: NativeSnapshotNode) -> NativeSnapshotNode | None:
        best: tuple[int, NativeSnapshotNode] | None = None

        def walk(node: NativeSnapshotNode, depth: int) -> None:
            nonlocal best
            if node is not root and not node.omitted:
                actionable = (
                    node.role in {
                        "button", "row", "tab", "checkbox", "radio",
                        "switch", "link", "menuitem", "textbox",
                    }
                    or node.scrollable
                )
                if not actionable:
                    if best is None or depth > best[0]:
                        best = (depth, node)
            for child in node.children:
                walk(child, depth + 1)

        walk(root, 0)
        return best[1] if best else None

    # ----------------------------------------------------------
    # Pass 4: container detection
    # ----------------------------------------------------------

    def _detect_containers(self, root: NativeSnapshotNode) -> None:
        """Annotate group nodes with ``container_kind`` (topbar, list, ...)."""
        toolbar_marked = {"value": False}

        def walk(node: NativeSnapshotNode) -> None:
            cls = node.class_name
            if not node.container_kind:
                if cls in _TOOLBAR_CLASSES and not toolbar_marked["value"]:
                    node.container_kind = "topbar"
                    toolbar_marked["value"] = True
                elif cls in _OVERLAY_CLASSES:
                    node.container_kind = "dialog"
                elif cls in _TAB_CLASSES:
                    node.container_kind = "tabs"
                elif cls in _SELECTION_CONTAINER_CLASSES:
                    node.container_kind = "selection"
                elif cls in _LIST_CLASSES and node.scrollable:
                    node.container_kind = "list"
                elif (
                    sum(1 for c in node.children if c.role == "row") >= 2
                ):
                    node.container_kind = "list"
                elif "BottomNavigation" in cls:
                    node.container_kind = "tabs"
            if node.container_kind == "tabs":
                for child in node.children:
                    if child.role in ("row", "button"):
                        child.role = "tab"
            for child in node.children:
                walk(child)

        walk(root)

    # ----------------------------------------------------------
    # Pass 5: ref assignment + action_target_ref propagation
    # ----------------------------------------------------------

    def _assign_refs_and_action_targets(self, root: NativeSnapshotNode) -> None:
        """Assign attribute-derived refs, then back-link text leaves to actionables."""
        self._ref_counters = {}

        def needs_ref(node: NativeSnapshotNode) -> bool:
            if node.scrollable:
                return True
            if node.container_kind:
                return True
            if node.role == "textbox":
                return True
            return node.role in {
                "button", "row", "tab", "checkbox", "radio",
                "switch", "link", "menuitem",
            }

        def assign(node: NativeSnapshotNode) -> None:
            if needs_ref(node):
                node.ref = self._derive_ref(node)
            for child in node.children:
                assign(child)

        assign(root)

        def link(node: NativeSnapshotNode, nearest_ref: str | None) -> None:
            current_ref = node.ref or nearest_ref
            if node.ref is None and node.role == "text" and node.name:
                if nearest_ref is not None:
                    node.action_target_ref = nearest_ref
            for child in node.children:
                link(child, current_ref)

        link(root, None)

    def _derive_ref(self, node: NativeSnapshotNode) -> str:
        if node.resource_id:
            base = _PACKAGE_PREFIX_RE.sub("", node.resource_id)
            base = self._to_snake_case(base)
            return self._unique_ref(base)

        if node.content_desc:
            base = self._to_snake_case(node.content_desc)[:_DESCRIPTIVE_REF_MAX_LENGTH]
            return self._unique_ref(base)

        if node.name:
            prefix = _ROLE_PREFIXES.get(node.role, node.role)
            name_part = self._to_snake_case(node.name)[:_DESCRIPTIVE_REF_MAX_LENGTH]
            base = f"{prefix}_{name_part}" if name_part else prefix
            return self._unique_ref(base)

        prefix = _ROLE_PREFIXES.get(node.role, node.role) or "elem"
        return self._unique_ref(prefix)

    def _unique_ref(self, base: str) -> str:
        if not base:
            base = "elem"
        count = self._ref_counters.get(base, 0) + 1
        self._ref_counters[base] = count
        if count == 1:
            return base
        return f"{base}_{count}"

    @staticmethod
    def _to_snake_case(text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        text = re.sub(r"[^\w]", "_", text, flags=re.UNICODE)
        text = re.sub(r"_+", "_", text)
        text = text.strip("_")
        return text.lower()

    # ----------------------------------------------------------
    # Pass 6: locator strategies
    # ----------------------------------------------------------

    def _build_locator_strategies(self, root: NativeSnapshotNode) -> None:
        """Populate ``strategies`` for every ref-bearing node."""
        for node in root.iter_nodes():
            if not node.ref:
                continue
            strategies: list[LocatorStrategy] = []
            if node.resource_id:
                strategies.append(LocatorStrategy(by="id", value=node.resource_id))
            if node.content_desc:
                strategies.append(
                    LocatorStrategy(by="accessibility_id", value=node.content_desc)
                )
            if node.name:
                if node.class_name:
                    xpath = (
                        f'//{node.class_name}[@text="{node.name}"]'
                        if node.text
                        else f'//*[@content-desc="{node.name}"]'
                    )
                else:
                    xpath = f'//*[@text="{node.name}"]'
                strategies.append(LocatorStrategy(by="xpath", value=xpath))
            x1, y1, x2, y2 = node.bounds
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            strategies.append(
                LocatorStrategy(by="coordinates", value=f"{cx},{cy}")
            )
            node.strategies = strategies
