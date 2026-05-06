"""WebSnapshotGenerator: build a tree-first WebSnapshot from WebView DOM."""

from __future__ import annotations

import html.parser
import re
from typing import Any

from .snapshot import LocatorStrategy
from .web_snapshot import WebSnapshot, WebSnapshotNode

_DEFAULT_MAX_DEPTH = 15
_DEFAULT_MAX_NODES = 300
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
    "main": "main",
    "section": "group",
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
    "tab": "tab",
    "menuitem": "menuitem",
}

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

_ACTIONABLE_TAGS = {"a", "button", "input", "textarea", "select", "option"}

DOM_EXTRACTION_SCRIPT = """
return (function(maxDepth, maxNodes) {
    maxDepth = maxDepth || 15;
    maxNodes = maxNodes || 300;
    var seen = 0;
    var truncated = false;

    function clean(text, limit) {
        if (!text) return '';
        return String(text).replace(/\\s+/g, ' ').trim().substring(0, limit || 120);
    }

    function directText(el) {
        var parts = [];
        for (var i = 0; i < el.childNodes.length; i++) {
            var child = el.childNodes[i];
            if (child.nodeType === Node.TEXT_NODE) {
                var text = clean(child.nodeValue, 120);
                if (text) parts.push(text);
            }
        }
        return clean(parts.join(' '), 120);
    }

    function isHidden(el) {
        if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
        if (el.getAttribute('aria-hidden') === 'true') return true;
        var style = window.getComputedStyle(el);
        if (!style || style.display === 'none' || style.visibility === 'hidden') return true;
        var rect = el.getBoundingClientRect();
        var tag = el.tagName.toLowerCase();
        if (rect.width === 0 && rect.height === 0 && !['html', 'body', 'script', 'style'].includes(tag)) {
            return true;
        }
        return false;
    }

    function roleOf(el) {
        var explicit = (el.getAttribute('role') || '').toLowerCase();
        if (explicit) return explicit;
        var tag = el.tagName.toLowerCase();
        if (tag === 'a') return 'link';
        if (tag === 'button') return 'button';
        if (tag === 'textarea') return 'textbox';
        if (tag === 'select') return 'select';
        if (tag === 'option') return 'option';
        if (tag === 'img') return 'image';
        if (tag === 'label') return 'label';
        if (/^h[1-6]$/.test(tag)) return 'heading';
        if (tag === 'nav') return 'navigation';
        if (tag === 'main') return 'main';
        if (tag === 'form') return 'form';
        if (tag === 'dialog') return 'dialog';
        if (tag === 'input') {
            var type = (el.type || 'text').toLowerCase();
            if (type === 'checkbox') return 'checkbox';
            if (type === 'radio') return 'radio';
            if (['submit', 'button', 'image', 'reset'].includes(type)) return 'button';
            if (type === 'range') return 'slider';
            if (type === 'file') return 'file';
            return 'textbox';
        }
        return 'element';
    }

    function nameOf(el, role) {
        var tag = el.tagName.toLowerCase();
        return clean(
            el.getAttribute('aria-label') ||
            el.getAttribute('alt') ||
            el.getAttribute('title') ||
            el.getAttribute('placeholder') ||
            (tag === 'input' ? el.value : '') ||
            (['link', 'button', 'heading', 'label', 'option', 'tab', 'menuitem'].includes(role) ? el.innerText : '') ||
            directText(el),
            120
        );
    }

    function cssFor(el) {
        var tag = el.tagName.toLowerCase();
        if (el.id) return '#' + CSS.escape(el.id);
        var testId = el.getAttribute('data-testid') || '';
        if (testId) return '[data-testid=\"' + testId.replace(/\"/g, '\\\\\"') + '\"]';
        if (el.name) return tag + '[name=\"' + String(el.name).replace(/\"/g, '\\\\\"') + '\"]';
        if (tag === 'a' && el.getAttribute('href')) {
            return 'a[href=\"' + el.getAttribute('href').replace(/\"/g, '\\\\\"') + '\"]';
        }
        return '';
    }

    function walk(el, depth) {
        if (!el || el.nodeType !== Node.ELEMENT_NODE || isHidden(el)) return null;
        if (seen >= maxNodes) {
            truncated = true;
            return {tag: '', role: 'text', name: '...', children: [], omitted: true};
        }
        if (depth > maxDepth) {
            truncated = true;
            return {tag: '', role: 'text', name: '...', children: [], omitted: true};
        }

        seen += 1;
        var tag = el.tagName.toLowerCase();
        var role = roleOf(el);
        var rect = el.getBoundingClientRect();
        var node = {
            tag: tag,
            id: el.id || '',
            test_id: el.getAttribute('data-testid') || '',
            aria_label: el.getAttribute('aria-label') || '',
            role: role,
            name: nameOf(el, role),
            value: el.value || '',
            type: el.type || '',
            href: el.href || '',
            placeholder: el.placeholder || '',
            css: cssFor(el),
            bounds: {
                x1: Math.round(rect.left + window.scrollX),
                y1: Math.round(rect.top + window.scrollY),
                x2: Math.round(rect.right + window.scrollX),
                y2: Math.round(rect.bottom + window.scrollY)
            },
            disabled: el.disabled || el.getAttribute('aria-disabled') === 'true' || false,
            checked: el.checked || el.getAttribute('aria-checked') === 'true' || false,
            selected: el.selected || el.getAttribute('aria-selected') === 'true' || false,
            readonly: el.readOnly || false,
            clickable: !!el.onclick || el.getAttribute('tabindex') !== null || el.isContentEditable || false,
            children: [],
            omitted: false
        };

        for (var i = 0; i < el.children.length; i++) {
            var child = walk(el.children[i], depth + 1);
            if (child) node.children.push(child);
            if (seen >= maxNodes) {
                truncated = true;
                break;
            }
        }
        return node;
    }

    var root = walk(document.body || document.documentElement, 0) ||
        {tag: 'body', role: 'document', name: document.title || '', children: []};
    root.role = 'document';
    root.name = document.title || root.name || '';
    root.truncated = truncated;
    return JSON.stringify(root);
})(arguments[0], arguments[1]);
"""

_SAFE_CHARS_RE = re.compile(r"[^a-z0-9_]")
_MULTI_UNDERSCORE_RE = re.compile(r"_{2,}")


def _to_snake(text: str) -> str:
    """Convert a string to a safe snake_case identifier."""
    lower = text.lower().strip()
    safe = _SAFE_CHARS_RE.sub("_", lower)
    safe = _MULTI_UNDERSCORE_RE.sub("_", safe).strip("_")
    return safe[:40] if safe else ""


def _derive_ref(elem: dict[str, Any], role: str) -> str:
    """Derive a web ref base name from element attributes."""
    if elem.get("id"):
        return _WEB_PREFIX + _to_snake(str(elem["id"]))
    if elem.get("test_id"):
        return _WEB_PREFIX + _to_snake(str(elem["test_id"]))
    if elem.get("aria_label"):
        return _WEB_PREFIX + _to_snake(str(elem["aria_label"]))

    prefix = _ROLE_PREFIX.get(role, role)
    name = str(elem.get("name") or "").strip()
    if name:
        return _WEB_PREFIX + prefix + "_" + _to_snake(name)[:25]
    placeholder = str(elem.get("placeholder") or "").strip()
    if placeholder:
        return _WEB_PREFIX + prefix + "_" + _to_snake(placeholder)[:25]
    return _WEB_PREFIX + prefix


def _make_unique(base: str, existing: set[str]) -> str:
    """Ensure ref is unique by appending _2, _3, ... suffixes."""
    if base not in existing:
        return base
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


def _determine_role(elem: dict[str, Any]) -> str:
    """Determine the element role from tag/type/role attributes."""
    aria_role = str(elem.get("role") or "").lower()
    if aria_role and aria_role != "element":
        return aria_role

    tag = str(elem.get("tag") or "").lower()
    if tag == "input":
        input_type = str(elem.get("type") or "text").lower()
        return _INPUT_TYPE_ROLE.get(input_type, "textbox")

    return _TAG_TO_ROLE.get(tag, "element")


def _is_actionable(elem: dict[str, Any], role: str) -> bool:
    tag = str(elem.get("tag") or "").lower()
    return (
        role in _ACTIONABLE_ROLES
        or tag in _ACTIONABLE_TAGS
        or bool(elem.get("clickable"))
    )


def _build_strategies(elem: dict[str, Any]) -> list[LocatorStrategy]:
    """Build ordered locator strategies for a web element."""
    strategies: list[LocatorStrategy] = []
    css = str(elem.get("css") or "")
    if css:
        strategies.append(LocatorStrategy(by="css selector", value=css))

    tag = str(elem.get("tag") or "").lower()
    name = str(elem.get("name") or "").strip()
    if name and tag in ("a", "button"):
        short = name[:50]
        if len(name) <= 50:
            strategies.append(
                LocatorStrategy(
                    by="link text" if tag == "a" else "xpath",
                    value=short if tag == "a" else f"//{tag}[normalize-space()='{short}']",
                )
            )
        else:
            strategies.append(
                LocatorStrategy(
                    by="partial link text" if tag == "a" else "xpath",
                    value=short if tag == "a" else f"//{tag}[contains(normalize-space(),'{short}')]",
                )
            )
    elif name:
        literal = _xpath_literal(name[:50])
        role = str(elem.get("role") or "").lower()
        if role and role != "element":
            strategies.append(
                LocatorStrategy(
                    by="xpath",
                    value=f"//*[@role={_xpath_literal(role)} and (@aria-label={literal} or normalize-space()={literal})]",
                )
            )
        else:
            strategies.append(
                LocatorStrategy(
                    by="xpath",
                    value=f"//*[@aria-label={literal} or normalize-space()={literal}]",
                )
            )

    bounds = _extract_bounds(elem)
    x1, y1, x2, y2 = bounds
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    if cx > 0 or cy > 0:
        strategies.append(LocatorStrategy(by="coordinates", value=f"{cx},{cy}"))
    return strategies


def _extract_bounds(elem: dict[str, Any]) -> tuple[int, int, int, int]:
    bounds = elem.get("bounds", {})
    if isinstance(bounds, dict):
        return (
            int(bounds.get("x1", 0) or 0),
            int(bounds.get("y1", 0) or 0),
            int(bounds.get("x2", 0) or 0),
            int(bounds.get("y2", 0) or 0),
        )
    return (0, 0, 0, 0)


def _xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"


class WebSnapshotGenerator:
    """Generate WebSnapshot from WebView DOM content."""

    def generate_from_dom(
        self,
        dom_tree: dict[str, Any] | list[dict[str, Any]],
        context: str,
        url: str = "",
        title: str = "",
        scope: str = "full",
        *,
        depth: int | None = None,
        max_nodes: int | None = None,
        boxes: bool = False,
    ) -> tuple[WebSnapshot, dict[str, Any]]:
        """Build a tree-first WebSnapshot from JS-extracted DOM data."""
        del scope, boxes
        used_refs: set[str] = set()
        counter = _NodeCounter(limit=max_nodes or _DEFAULT_MAX_NODES)
        max_depth = depth if depth is not None else _DEFAULT_MAX_DEPTH

        if isinstance(dom_tree, list):
            dom_tree = {
                "tag": "body",
                "role": "document",
                "name": title,
                "children": dom_tree,
                "truncated": False,
            }

        root = self._build_node(
            dom_tree,
            depth=0,
            max_depth=max_depth,
            used_refs=used_refs,
            counter=counter,
            force_document=True,
        )
        root.role = "document"
        if title and not root.name:
            root.name = title
        truncated = bool(dom_tree.get("truncated")) or counter.truncated
        snapshot = WebSnapshot.from_root(
            root=root,
            context=context,
            url=url,
            title=title,
            truncated=truncated,
        )
        return snapshot, snapshot.to_ref_map()

    def generate(
        self,
        html_source: str,
        context: str,
        url: str = "",
        title: str = "",
        scope: str = "full",
        *,
        depth: int | None = None,
        max_nodes: int | None = None,
        boxes: bool = False,
    ) -> tuple[WebSnapshot, dict[str, Any]]:
        """Fallback: parse raw HTML into the same WebSnapshot shape."""
        parser = _HTMLSnapshotParser(max_nodes=max_nodes or _DEFAULT_MAX_NODES)
        parser.feed(html_source)
        root = parser.root
        if title and not root.get("name"):
            root["name"] = title
        return self.generate_from_dom(
            root,
            context,
            url,
            title,
            scope,
            depth=depth,
            max_nodes=max_nodes,
            boxes=boxes,
        )

    def _build_node(
        self,
        elem: dict[str, Any],
        *,
        depth: int,
        max_depth: int,
        used_refs: set[str],
        counter: "_NodeCounter",
        force_document: bool = False,
    ) -> WebSnapshotNode:
        if not counter.consume():
            return WebSnapshotNode(role="text", name="...", omitted=True)
        if depth > max_depth:
            counter.truncated = True
            return WebSnapshotNode(role="text", name="...", omitted=True)

        role = "document" if force_document else _determine_role(elem)
        name = str(elem.get("aria_label") or elem.get("name") or elem.get("placeholder") or "")
        value = str(elem.get("value") or "") or None
        state_list: list[str] = []
        if elem.get("disabled"):
            state_list.append("disabled")
        elif role in _ACTIONABLE_ROLES:
            state_list.append("enabled")
        if elem.get("checked"):
            state_list.append("checked")
        if elem.get("selected"):
            state_list.append("selected")
        if elem.get("readonly"):
            state_list.append("readonly")

        ref: str | None = None
        strategies: list[LocatorStrategy] = []
        if not force_document and _is_actionable(elem, role):
            strategies = _build_strategies(elem)
            if strategies:
                ref = _make_unique(_derive_ref(elem, role), used_refs)
                used_refs.add(ref)

        children = [
            self._build_node(
                child,
                depth=depth + 1,
                max_depth=max_depth,
                used_refs=used_refs,
                counter=counter,
            )
            for child in elem.get("children", [])
            if isinstance(child, dict)
        ]
        if role == "element" and name and not ref:
            role = "group" if children else "text"

        return WebSnapshotNode(
            role=role,
            name=name,
            ref=ref,
            tag=str(elem.get("tag") or ""),
            value=value,
            state=state_list,
            bounds=_extract_bounds(elem),
            strategies=strategies,
            children=children,
            omitted=bool(elem.get("omitted")),
        )


class _NodeCounter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.count = 0
        self.truncated = False

    def consume(self) -> bool:
        if self.count >= self.limit:
            self.truncated = True
            return False
        self.count += 1
        return True


class _HTMLSnapshotParser(html.parser.HTMLParser):
    """Minimal stack-based HTML fallback that preserves hierarchy."""

    def __init__(self, max_nodes: int) -> None:
        super().__init__()
        self.max_nodes = max_nodes
        self.node_count = 0
        self.root: dict[str, Any] = {
            "tag": "body",
            "role": "document",
            "name": "",
            "children": [],
            "truncated": False,
        }
        self._stack: list[dict[str, Any]] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._push_node(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._push_node(tag, attrs, self_closing=True)

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        parent = self._stack[-1]
        if parent.get("name"):
            parent["name"] = f"{parent['name']} {text}"[:120]
        else:
            parent["name"] = text[:120]

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].get("tag") == tag_lower:
                del self._stack[index:]
                return

    def _push_node(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        self_closing: bool,
    ) -> None:
        if self.node_count >= self.max_nodes:
            self.root["truncated"] = True
            return
        attrs_dict = {key: (value or "") for key, value in attrs}
        tag_lower = tag.lower()
        if tag_lower in {"html", "body"}:
            return
        node = {
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
            "css": _css_from_attrs(tag_lower, attrs_dict),
            "bounds": {},
            "disabled": "disabled" in attrs_dict,
            "checked": "checked" in attrs_dict,
            "selected": "selected" in attrs_dict,
            "readonly": "readonly" in attrs_dict,
            "clickable": "onclick" in attrs_dict or "tabindex" in attrs_dict,
            "children": [],
        }
        self._stack[-1]["children"].append(node)
        self.node_count += 1
        if not self_closing and tag_lower not in {"br", "img", "input", "meta", "link"}:
            self._stack.append(node)


def _css_from_attrs(tag: str, attrs: dict[str, str]) -> str:
    if attrs.get("id"):
        return f"#{attrs['id']}"
    if attrs.get("data-testid"):
        return f'[data-testid="{attrs["data-testid"]}"]'
    if attrs.get("name"):
        return f'{tag}[name="{attrs["name"]}"]'
    if tag == "a" and attrs.get("href"):
        return f'a[href="{attrs["href"]}"]'
    return ""
