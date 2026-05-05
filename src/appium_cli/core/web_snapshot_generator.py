"""WebSnapshotGenerator: build an AccessibilitySnapshot from WebView DOM.

Two paths:
1. ``generate_from_dom()`` — takes structured element dicts extracted via
   JavaScript ``document.querySelectorAll()``.
2. ``generate()`` — takes raw HTML and parses actionable elements with
   Python's ``html.parser`` as a fallback when JS execution fails.

All generated refs carry a ``web_`` prefix and use CSS/XPath locator
strategies instead of Appium-native ``resource-id`` / ``accessibility_id``.
"""

from __future__ import annotations

import hashlib
import html.parser
import re
from typing import Any

from .snapshot import (
    AccessibilitySnapshot,
    LocatorStrategy,
    RefEntry,
    SnapshotContainer,
    SnapshotElement,
    compute_screen_id,
)

# ============================================================
# Constants
# ============================================================

_MAX_ELEMENTS = 250
_WEB_PREFIX = "web_"

_TAG_TO_ROLE: dict[str, str] = {
    "a": "link",
    "button": "button",
    "input": "textbox",
    "textarea": "textbox",
    "select": "select",
    "option": "option",
    "img": "image",
    "video": "video",
    "audio": "audio",
    "label": "label",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
    "h4": "heading",
    "h5": "heading",
    "h6": "heading",
    "table": "table",
    "form": "form",
    "nav": "navigation",
    "dialog": "dialog",
}

_INPUT_TYPE_ROLE: dict[str, str] = {
    "checkbox": "checkbox",
    "radio": "radio",
    "submit": "button",
    "button": "button",
    "image": "button",
    "reset": "button",
    "range": "slider",
    "file": "file",
}

_ROLE_PREFIX: dict[str, str] = {
    "link": "link",
    "button": "btn",
    "textbox": "input",
    "select": "select",
    "checkbox": "chk",
    "radio": "radio",
    "image": "img",
    "heading": "heading",
    "slider": "slider",
}

# Selector for the JS DOM extraction script
ACTIONABLE_SELECTOR = (
    "a, button, input, textarea, select, "
    "[role], [aria-label], [data-testid], "
    "img[alt], label[for], "
    "[onclick], [tabindex]"
)

# JS script embedded in observation.py to extract actionable elements
DOM_EXTRACTION_SCRIPT = """
(function() {
    var sel = arguments[0] || '""" + ACTIONABLE_SELECTOR + """';
    var max = arguments[1] || 250;
    var els = document.querySelectorAll(sel);
    var results = [];
    var seen = 0;
    for (var i = 0; i < els.length && seen < max; i++) {
        var el = els[i];
        var tag = el.tagName.toLowerCase();
        var rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) continue;
        var item = {
            tag: tag,
            id: el.id || '',
            test_id: el.getAttribute('data-testid') || '',
            aria_label: el.getAttribute('aria-label') || '',
            role: el.getAttribute('role') || '',
            name: el.textContent ? el.textContent.trim().substring(0, 100) : '',
            value: el.value || '',
            type: el.type || '',
            href: el.href || '',
            placeholder: el.placeholder || '',
            css: '',
            xpath: '',
            bounds: {
                x1: Math.round(rect.left + window.scrollX),
                y1: Math.round(rect.top + window.scrollY),
                x2: Math.round(rect.right + window.scrollX),
                y2: Math.round(rect.bottom + window.scrollY)
            },
            disabled: el.disabled || false,
            checked: el.checked || false,
            selected: el.selected || false,
            readonly: el.readOnly || false
        };
        // Build stable CSS selector
        if (el.id) {
            item.css = '#' + CSS.escape(el.id);
        } else if (item.test_id) {
            item.css = '[data-testid="' + item.test_id + '"]';
        } else if (el.name) {
            item.css = tag + '[name="' + el.name + '"]';
        } else if (tag === 'a' && el.href) {
            item.css = 'a[href="' + el.getAttribute('href') + '"]';
        }
        results.push(item);
        seen++;
    }
    return JSON.stringify(results);
})();
"""

# ============================================================
# Ref naming
# ============================================================

_SAFE_CHARS_RE = re.compile(r"[^a-z0-9_]")
_MULTI_UNDERSCORE_RE = re.compile(r"_{2,}")


def _to_snake(text: str) -> str:
    """Convert a string to a safe snake_case identifier."""
    lower = text.lower().strip()
    safe = _SAFE_CHARS_RE.sub("_", lower)
    safe = _MULTI_UNDERSCORE_RE.sub("_", safe).strip("_")
    return safe[:40] if safe else ""


def _derive_ref(elem: dict[str, str], role: str) -> str:
    """Derive a ref base name from element attributes."""
    # 1. id
    if elem.get("id"):
        return _WEB_PREFIX + _to_snake(elem["id"])
    # 2. data-testid
    if elem.get("test_id"):
        return _WEB_PREFIX + _to_snake(elem["test_id"])
    # 3. aria-label
    if elem.get("aria_label"):
        return _WEB_PREFIX + _to_snake(elem["aria_label"])
    # 4. role_prefix + name fallback
    prefix = _ROLE_PREFIX.get(role, role)
    name = elem.get("name", "").strip()
    if name:
        slug = _to_snake(name)[:25]
        return _WEB_PREFIX + prefix + "_" + slug
    # 5. role_prefix + placeholder
    placeholder = elem.get("placeholder", "").strip()
    if placeholder:
        slug = _to_snake(placeholder)[:25]
        return _WEB_PREFIX + prefix + "_" + slug
    # 6. generic
    return _WEB_PREFIX + prefix


def _make_unique(base: str, existing: set[str]) -> str:
    """Ensure ref is unique by appending _2, _3, ... suffixes."""
    if base not in existing:
        return base
    n = 2
    while f"{base}_{n}" in existing:
        n += 1
    return f"{base}_{n}"


def _determine_role(elem: dict[str, str]) -> str:
    """Determine the element role from tag/type/role attributes."""
    # Explicit ARIA role
    aria_role = elem.get("role", "").lower()
    if aria_role in _TAG_TO_ROLE.values() or aria_role in (
        "menuitem", "tab", "switch", "progressbar",
    ):
        return aria_role

    tag = elem.get("tag", "").lower()
    if tag == "input":
        input_type = elem.get("type", "text").lower()
        return _INPUT_TYPE_ROLE.get(input_type, "textbox")

    return _TAG_TO_ROLE.get(tag, "element")


def _build_strategies(elem: dict[str, Any]) -> list[LocatorStrategy]:
    """Build ordered locator strategies for a web element."""
    strategies: list[LocatorStrategy] = []

    css = elem.get("css", "")
    if css:
        strategies.append(LocatorStrategy(by="css selector", value=css))

    # XPath fallback via text for links/buttons
    tag = elem.get("tag", "").lower()
    name = (elem.get("name") or "").strip()
    if name and tag in ("a", "button"):
        short = name[:50]
        if len(name) <= 50:
            strategies.append(
                LocatorStrategy(by="link text" if tag == "a" else "xpath",
                                value=short if tag == "a" else f"//{tag}[normalize-space()='{short}']")
            )
        else:
            strategies.append(
                LocatorStrategy(by="partial link text" if tag == "a" else "xpath",
                                value=short if tag == "a" else f"//{tag}[contains(normalize-space(),'{short}')]")
            )

    # Coordinate fallback
    bounds = elem.get("bounds", {})
    if isinstance(bounds, dict):
        x1 = bounds.get("x1", 0)
        y1 = bounds.get("y1", 0)
        x2 = bounds.get("x2", 0)
        y2 = bounds.get("y2", 0)
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        if cx > 0 or cy > 0:
            strategies.append(LocatorStrategy(by="coordinates", value=f"{cx},{cy}"))

    return strategies


def _extract_bounds(elem: dict[str, Any]) -> tuple[int, int, int, int]:
    bounds = elem.get("bounds", {})
    if isinstance(bounds, dict):
        return (
            int(bounds.get("x1", 0)),
            int(bounds.get("y1", 0)),
            int(bounds.get("x2", 0)),
            int(bounds.get("y2", 0)),
        )
    return (0, 0, 0, 0)


# ============================================================
# WebSnapshotGenerator
# ============================================================


class WebSnapshotGenerator:
    """Generate AccessibilitySnapshot from WebView DOM content."""

    def generate_from_dom(
        self,
        dom_elements: list[dict[str, Any]],
        context: str,
        url: str = "",
        title: str = "",
        scope: str = "full",
        *,
        depth: int | None = None,
        boxes: bool = False,
    ) -> tuple[AccessibilitySnapshot, dict[str, RefEntry]]:
        """Build snapshot from JS-extracted DOM element dicts."""
        elements: list[SnapshotElement] = []
        ref_map: dict[str, RefEntry] = {}
        used_refs: set[str] = set()

        container = SnapshotContainer(
            ref="web_document",
            region="content",
            title=title or "",
            scrollable=True,
            scroll_direction="vertical",
        )

        for i, elem in enumerate(dom_elements[:_MAX_ELEMENTS]):
            if depth is not None and i >= depth:
                break

            role = _determine_role(elem)
            base_ref = _derive_ref(elem, role)
            ref = _make_unique(base_ref, used_refs)
            used_refs.add(ref)

            name = (elem.get("aria_label") or elem.get("name") or
                    elem.get("placeholder") or "")
            value = elem.get("value") or None
            bounds = _extract_bounds(elem)

            state_list: list[str] = []
            if elem.get("disabled"):
                state_list.append("disabled")
            else:
                state_list.append("enabled")
            if elem.get("checked"):
                state_list.append("checked")
            if elem.get("selected"):
                state_list.append("selected")
            if elem.get("readonly"):
                state_list.append("readonly")

            snap_elem = SnapshotElement(
                ref=ref,
                role=role,
                name=name,
                value=value,
                state=state_list,
                bounds=bounds,
                container_ref="web_document",
            )
            elements.append(snap_elem)
            container.children_refs.append(ref)

            strategies = _build_strategies(elem)
            ref_entry = RefEntry(
                strategies=strategies,
                expected_bounds=bounds,
                role=role,
                name=name,
                context=context,
                source_type="web",
            )
            ref_map[ref] = ref_entry

        screen_id = compute_screen_id(elements)
        app_info = f"{context} {url}" if url else context

        nav: dict[str, Any] = {}
        # back=true is common for WebViews
        if url:
            nav["back"] = True

        snapshot_obj = AccessibilitySnapshot(
            screen_id=screen_id,
            app_info=app_info,
            containers=[container],
            elements=elements,
            nav=nav,
            context=context,
            source_type="web",
        )

        return snapshot_obj, ref_map

    def generate(
        self,
        html_source: str,
        context: str,
        url: str = "",
        title: str = "",
        scope: str = "full",
        *,
        depth: int | None = None,
        boxes: bool = False,
    ) -> tuple[AccessibilitySnapshot, dict[str, RefEntry]]:
        """Fallback: parse raw HTML and extract actionable elements."""
        parser = _HTMLSnapshotParser()
        parser.feed(html_source)
        return self.generate_from_dom(
            parser.elements, context, url, title, scope,
            depth=depth, boxes=boxes,
        )


# ============================================================
# HTML fallback parser
# ============================================================


class _HTMLSnapshotParser(html.parser.HTMLParser):
    """Lightweight HTML parser that extracts actionable elements."""

    _ACTIONABLE_TAGS = frozenset({
        "a", "button", "input", "textarea", "select",
        "img", "label", "h1", "h2", "h3", "h4", "h5", "h6",
    })

    def __init__(self) -> None:
        super().__init__()
        self.elements: list[dict[str, str]] = []
        self._current_tag: str = ""
        self._current_attrs: dict[str, str] = {}
        self._text_buf: list[str] = []
        self._capturing = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k: (v or "") for k, v in attrs}
        tag_lower = tag.lower()

        is_actionable = (
            tag_lower in self._ACTIONABLE_TAGS
            or attrs_dict.get("role")
            or attrs_dict.get("aria-label")
            or attrs_dict.get("data-testid")
            or attrs_dict.get("onclick")
            or attrs_dict.get("tabindex")
        )

        if is_actionable and len(self.elements) < _MAX_ELEMENTS:
            self._capturing = True
            self._current_tag = tag_lower
            self._current_attrs = {
                "tag": tag_lower,
                "id": attrs_dict.get("id", ""),
                "test_id": attrs_dict.get("data-testid", ""),
                "aria_label": attrs_dict.get("aria-label", ""),
                "role": attrs_dict.get("role", ""),
                "type": attrs_dict.get("type", ""),
                "href": attrs_dict.get("href", ""),
                "value": attrs_dict.get("value", ""),
                "placeholder": attrs_dict.get("placeholder", ""),
                "name": "",  # will be set from text content
                "css": "",
                "bounds": {},
                "disabled": "true" if "disabled" in attrs_dict else "",
                "checked": "true" if "checked" in attrs_dict else "",
                "readonly": "true" if "readonly" in attrs_dict else "",
            }
            # Build CSS selector
            if attrs_dict.get("id"):
                self._current_attrs["css"] = f"#{attrs_dict['id']}"
            elif attrs_dict.get("data-testid"):
                self._current_attrs["css"] = f'[data-testid="{attrs_dict["data-testid"]}"]'
            elif attrs_dict.get("name"):
                self._current_attrs["css"] = f'{tag_lower}[name="{attrs_dict["name"]}"]'

            self._text_buf = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._text_buf.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if self._capturing and tag.lower() == self._current_tag:
            text = " ".join(t for t in self._text_buf if t)[:100]
            self._current_attrs["name"] = text
            self.elements.append(self._current_attrs)
            self._capturing = False
            self._current_tag = ""
            self._current_attrs = {}
            self._text_buf = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing tags like <input />, <img />
        attrs_dict = {k: (v or "") for k, v in attrs}
        tag_lower = tag.lower()

        is_actionable = (
            tag_lower in self._ACTIONABLE_TAGS
            or attrs_dict.get("role")
            or attrs_dict.get("aria-label")
            or attrs_dict.get("data-testid")
        )

        if is_actionable and len(self.elements) < _MAX_ELEMENTS:
            elem = {
                "tag": tag_lower,
                "id": attrs_dict.get("id", ""),
                "test_id": attrs_dict.get("data-testid", ""),
                "aria_label": attrs_dict.get("aria-label", ""),
                "role": attrs_dict.get("role", ""),
                "type": attrs_dict.get("type", ""),
                "href": attrs_dict.get("href", ""),
                "value": attrs_dict.get("value", ""),
                "placeholder": attrs_dict.get("placeholder", ""),
                "name": attrs_dict.get("alt", "") or attrs_dict.get("aria-label", ""),
                "css": "",
                "bounds": {},
                "disabled": "true" if "disabled" in attrs_dict else "",
                "checked": "true" if "checked" in attrs_dict else "",
                "readonly": "true" if "readonly" in attrs_dict else "",
            }
            if attrs_dict.get("id"):
                elem["css"] = f"#{attrs_dict['id']}"
            elif attrs_dict.get("data-testid"):
                elem["css"] = f'[data-testid="{attrs_dict["data-testid"]}"]'
            elif attrs_dict.get("name"):
                elem["css"] = f'{tag_lower}[name="{attrs_dict["name"]}"]'
            self.elements.append(elem)
