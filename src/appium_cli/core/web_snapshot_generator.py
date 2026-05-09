"""WebSnapshotGenerator: build a tree-first WebSnapshot from WebView DOM."""

from __future__ import annotations

import html.parser
import re
from typing import Any

from .snapshot import LocatorStrategy
from .web_snapshot import WebSnapshot, WebSnapshotNode

WEB_DEFAULT_MAX_DEPTH = 999
WEB_DEFAULT_MAX_NODES = 999999
WEB_REF_TEXT_LIMIT = 128
WEB_LOCATOR_TEXT_LIMIT = 128
WEB_DOM_TEXT_LIMIT = 1000
_WEB_PREFIX = "web_"

_TAG_TO_ROLE: dict[str, str] = {
    "a": "link",
    "button": "button",
    "input": "textbox",
    "textarea": "textbox",
    "select": "combobox",
    "option": "option",
    "img": "image",
    "video": "video",
    "audio": "audio",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
    "h4": "heading",
    "h5": "heading",
    "h6": "heading",
    "table": "table",
    "tr": "row",
    "td": "cell",
    "th": "columnheader",
    "form": "form",
    "nav": "navigation",
    "dialog": "dialog",
    "main": "main",
    "header": "banner",
    "footer": "contentinfo",
    "aside": "complementary",
    "article": "article",
    "section": "group",
    "fieldset": "group",
    "legend": "legend",
    "ul": "list",
    "ol": "list",
    "menu": "list",
    "li": "listitem",
    "p": "paragraph",
    "hr": "separator",
    "details": "group",
    "summary": "button",
}

_INPUT_TYPE_ROLE: dict[str, str] = {
    "checkbox": "checkbox",
    "radio": "radio",
    "submit": "button",
    "button": "button",
    "image": "button",
    "reset": "button",
    "range": "slider",
    "number": "spinbutton",
    "search": "searchbox",
    "file": "button",
}

_ROLE_PREFIX: dict[str, str] = {
    "link": "link",
    "button": "btn",
    "textbox": "input",
    "combobox": "select",
    "searchbox": "search",
    "spinbutton": "input",
    "checkbox": "chk",
    "radio": "radio",
    "image": "img",
    "heading": "heading",
    "slider": "slider",
    "tab": "tab",
    "menuitem": "menuitem",
    "generic": "el",
}

_ACTIONABLE_ROLES = {
    "button",
    "checkbox",
    "combobox",
    "link",
    "menuitem",
    "option",
    "radio",
    "searchbox",
    "slider",
    "spinbutton",
    "switch",
    "tab",
    "textbox",
}

_ACTIONABLE_TAGS = {"a", "button", "input", "textarea", "select", "option"}

DOM_EXTRACTION_SCRIPT = """
return (function(maxDepth, maxNodes) {
    maxDepth = maxDepth || __WEB_DEFAULT_MAX_DEPTH__;
    maxNodes = maxNodes || __WEB_DEFAULT_MAX_NODES__;
    var seen = 0;
    var truncated = false;

    var SEMANTIC_TAGS = {
        'article':1,'aside':1,'blockquote':1,'button':1,'caption':1,'code':1,
        'datalist':1,'dd':1,'del':1,'details':1,'dfn':1,'dialog':1,'dt':1,
        'em':1,'fieldset':1,'figure':1,'h1':1,'h2':1,'h3':1,'h4':1,'h5':1,'h6':1,
        'hr':1,'ins':1,'li':1,'main':1,'mark':1,'math':1,'menu':1,'meter':1,
        'nav':1,'ol':1,'ul':1,'optgroup':1,'option':1,'output':1,'p':1,
        'progress':1,'search':1,'strong':1,'sub':1,'sup':1,'svg':1,
        'table':1,'thead':1,'tbody':1,'tfoot':1,'tr':1,'th':1,'td':1,
        'textarea':1,'time':1,'select':1,'video':1,'audio':1,'canvas':1,
        'header':1,'footer':1,'legend':1,'summary':1
    };

    function clean(text, limit) {
        if (!text) return '';
        return String(text).replace(/\\s+/g, ' ').trim().substring(0, limit || __WEB_DOM_TEXT_LIMIT__);
    }

    function directText(el) {
        var parts = [];
        for (var i = 0; i < el.childNodes.length; i++) {
            var child = el.childNodes[i];
            if (child.nodeType === Node.TEXT_NODE) {
                var text = clean(child.nodeValue, __WEB_DOM_TEXT_LIMIT__);
                if (text) parts.push(text);
            }
        }
        return clean(parts.join(' '), __WEB_DOM_TEXT_LIMIT__);
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

    function isSemantic(el) {
        if (el.getAttribute('role')) return true;
        var tag = el.tagName.toLowerCase();
        if (SEMANTIC_TAGS[tag]) return true;
        if (tag === 'a' || tag === 'area') return el.hasAttribute('href');
        if (tag === 'form' || tag === 'section')
            return el.hasAttribute('aria-label') || el.hasAttribute('aria-labelledby');
        if (tag === 'img') return el.getAttribute('alt') !== '';
        if (tag === 'input') return (el.type || 'text').toLowerCase() !== 'hidden';
        if (el.hasAttribute('tabindex') || el.onclick || el.isContentEditable) return true;
        if (el.getAttribute('aria-label')) return true;
        return false;
    }

    function roleOf(el) {
        var explicit = (el.getAttribute('role') || '').toLowerCase();
        if (explicit) return explicit;
        var tag = el.tagName.toLowerCase();
        if (tag === 'a') return 'link';
        if (tag === 'button') return 'button';
        if (tag === 'textarea') return 'textbox';
        if (tag === 'select') return 'combobox';
        if (tag === 'option') return 'option';
        if (tag === 'img') return 'image';
        if (/^h[1-6]$/.test(tag)) return 'heading';
        if (tag === 'nav') return 'navigation';
        if (tag === 'main') return 'main';
        if (tag === 'header') return 'banner';
        if (tag === 'footer') return 'contentinfo';
        if (tag === 'aside') return 'complementary';
        if (tag === 'article') return 'article';
        if (tag === 'form') return 'form';
        if (tag === 'dialog') return 'dialog';
        if (tag === 'fieldset') return 'group';
        if (tag === 'legend') return 'legend';
        if (tag === 'ul' || tag === 'ol' || tag === 'menu') return 'list';
        if (tag === 'li') return 'listitem';
        if (tag === 'table') return 'table';
        if (tag === 'tr') return 'row';
        if (tag === 'td') return 'cell';
        if (tag === 'th') return 'columnheader';
        if (tag === 'p') return 'paragraph';
        if (tag === 'hr') return 'separator';
        if (tag === 'details') return 'group';
        if (tag === 'summary') return 'button';
        if (tag === 'input') {
            var type = (el.type || 'text').toLowerCase();
            if (type === 'checkbox') return 'checkbox';
            if (type === 'radio') return 'radio';
            if (['submit', 'button', 'image', 'reset'].includes(type)) return 'button';
            if (type === 'range') return 'slider';
            if (type === 'number') return 'spinbutton';
            if (type === 'file') return 'button';
            if (type === 'search') return 'searchbox';
            return 'textbox';
        }
        if (el.isContentEditable) return 'textbox';
        return 'generic';
    }

    function nameOf(el, role) {
        var tag = el.tagName.toLowerCase();
        return clean(
            el.getAttribute('aria-label') ||
            el.getAttribute('alt') ||
            el.getAttribute('title') ||
            el.getAttribute('placeholder') ||
            (tag === 'input' ? el.value : '') ||
            (['link', 'button', 'heading', 'option', 'tab', 'menuitem', 'listitem'].includes(role) ? el.innerText : '') ||
            directText(el),
            __WEB_DOM_TEXT_LIMIT__
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

    function labelTextFor(el) {
        if (el.id) {
            try {
                var lbl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                if (lbl) { var t = clean(lbl.innerText, 64); if (t) return t; }
            } catch(e) {}
        }
        var lblBy = el.getAttribute('aria-labelledby');
        if (lblBy) {
            var lblEl = document.getElementById(lblBy);
            if (lblEl) { var t = clean(lblEl.innerText, 64); if (t) return t; }
        }
        var parent = el.parentElement;
        if (parent && parent.tagName.toLowerCase() === 'label') {
            var t = clean(parent.innerText, 64);
            if (t) return t;
        }
        return '';
    }

    function buildNode(el) {
        var tag = el.tagName.toLowerCase();
        var role = roleOf(el);
        var rect = el.getBoundingClientRect();
        var inputType = (tag === 'input') ? (el.type || 'text').toLowerCase() : '';
        var lbl = '';
        if (inputType === 'checkbox' || inputType === 'radio') {
            lbl = labelTextFor(el);
        }
        return {
            tag: tag,
            id: el.id || '',
            test_id: el.getAttribute('data-testid') || '',
            aria_label: el.getAttribute('aria-label') || '',
            label_text: lbl,
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
    }

    function walkCollect(el, semanticDepth, results) {
        if (!el || el.nodeType !== Node.ELEMENT_NODE || isHidden(el)) return;
        if (seen >= maxNodes) { truncated = true; return; }
        if (semanticDepth > maxDepth) { truncated = true; return; }
        seen += 1;

        if (isSemantic(el)) {
            var node = buildNode(el);
            results.push(node);
            for (var i = 0; i < el.children.length; i++) {
                walkCollect(el.children[i], semanticDepth + 1, node.children);
                if (seen >= maxNodes) { truncated = true; break; }
            }
        } else {
            var text = directText(el);
            if (text) {
                results.push({tag: '', role: 'text', name: text, children: [], omitted: false});
            }
            for (var i = 0; i < el.children.length; i++) {
                walkCollect(el.children[i], semanticDepth, results);
                if (seen >= maxNodes) { truncated = true; break; }
            }
        }
    }

    var rootChildren = [];
    var startEl = document.body || document.documentElement;
    walkCollect(startEl, 0, rootChildren);
    var root = {
        tag: 'body',
        role: 'document',
        name: document.title || '',
        children: rootChildren,
        truncated: truncated,
        omitted: false
    };
    return JSON.stringify(root);
})(arguments[0], arguments[1]);
""".replace("__WEB_DEFAULT_MAX_DEPTH__", str(WEB_DEFAULT_MAX_DEPTH)).replace(
    "__WEB_DEFAULT_MAX_NODES__", str(WEB_DEFAULT_MAX_NODES)
).replace("__WEB_DOM_TEXT_LIMIT__", str(WEB_DOM_TEXT_LIMIT))

_SAFE_CHARS_RE = re.compile(r"[^a-z0-9_]")
_MULTI_UNDERSCORE_RE = re.compile(r"_{2,}")


def _to_snake(text: str) -> str:
    """Convert a string to a safe snake_case identifier."""
    lower = text.lower().strip()
    safe = _SAFE_CHARS_RE.sub("_", lower)
    safe = _MULTI_UNDERSCORE_RE.sub("_", safe).strip("_")
    return safe[:WEB_REF_TEXT_LIMIT] if safe else ""


def _derive_ref(elem: dict[str, Any], role: str) -> str:
    """Derive a web ref base name from element attributes."""
    # For checkbox/radio, prefer label text over id for meaningful ref names
    if role in ("checkbox", "radio") and elem.get("label_text"):
        prefix = _ROLE_PREFIX.get(role, role)
        return _WEB_PREFIX + prefix + "_" + _to_snake(str(elem["label_text"]))[:WEB_REF_TEXT_LIMIT]

    if elem.get("id"):
        return _WEB_PREFIX + _to_snake(str(elem["id"]))
    if elem.get("test_id"):
        return _WEB_PREFIX + _to_snake(str(elem["test_id"]))
    if elem.get("aria_label"):
        return _WEB_PREFIX + _to_snake(str(elem["aria_label"]))

    prefix = _ROLE_PREFIX.get(role, role)
    name = str(elem.get("name") or "").strip()
    if name:
        return _WEB_PREFIX + prefix + "_" + _to_snake(name)[:WEB_REF_TEXT_LIMIT]
    placeholder = str(elem.get("placeholder") or "").strip()
    if placeholder:
        return _WEB_PREFIX + prefix + "_" + _to_snake(placeholder)[:WEB_REF_TEXT_LIMIT]
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
    if aria_role and aria_role not in ("element", "generic"):
        return aria_role

    tag = str(elem.get("tag") or "").lower()
    if tag == "input":
        input_type = str(elem.get("type") or "text").lower()
        return _INPUT_TYPE_ROLE.get(input_type, "textbox")

    return _TAG_TO_ROLE.get(tag, "generic")


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
        short = name[:WEB_LOCATOR_TEXT_LIMIT]
        if len(name) <= WEB_LOCATOR_TEXT_LIMIT:
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
        literal = _xpath_literal(name[:WEB_LOCATOR_TEXT_LIMIT])
        role = str(elem.get("role") or "").lower()
        if role and role not in ("element", "generic"):
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
        counter = _NodeCounter(limit=max_nodes or WEB_DEFAULT_MAX_NODES)
        max_depth = depth if depth is not None else WEB_DEFAULT_MAX_DEPTH

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
        parser = _HTMLSnapshotParser(max_nodes=max_nodes or WEB_DEFAULT_MAX_NODES)
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
        label_text = str(elem.get("label_text") or "")
        # For checkbox/radio, prefer label_text for the display name
        if role in ("checkbox", "radio") and label_text:
            name = label_text
        else:
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
        if role == "generic" and name and not ref:
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
            parent["name"] = f"{parent['name']} {text}"[:WEB_DOM_TEXT_LIMIT]
        else:
            parent["name"] = text[:WEB_DOM_TEXT_LIMIT]

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
