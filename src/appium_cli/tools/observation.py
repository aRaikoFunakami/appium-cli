"""Observation tools."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from appium_cli.core.ref_resolver import ElementNotFoundError, parse_ref, _CoordinateElement
from appium_cli.core.native_snapshot import NativeSnapshot, NativeSnapshotNode
from appium_cli.core.native_snapshot_generator import NativeSnapshotGenerator
from appium_cli.core.snapshot import compress_xml
from appium_cli.core.snapshot_artifacts import (
    SnapshotBundlePayload,
    compute_snapshot_stats,
    create_snapshot_bundle_payload,
)
from appium_cli.core.web_snapshot import WebSnapshot
from appium_cli.core.web_snapshot_generator import (
    DOM_EXTRACTION_SCRIPT,
    WEB_DEFAULT_MAX_DEPTH,
    WEB_DEFAULT_MAX_NODES,
    WebSnapshotGenerator,
)
from appium_cli.daemon import state
from appium_cli.tools.contexts import (
    NATIVE_CONTEXT,
    current_context,
    is_web_context,
    resolve_context,
    using_context,
)
from appium_cli.utils.errors import AppiumCliError
from appium_cli.utils.exit_codes import FEATURE_NOT_ENABLED
from appium_cli.utils.paths import (
    latest_snapshot_path,
    snapshot_artifact_path,
    write_json_artifact,
    write_latest_snapshot_pointer,
    write_text_artifact,
)

logger = logging.getLogger(__name__)


def _normalize_search_terms(text: str, any_text: list[str] | tuple[str, ...] | None = None) -> list[str]:
    """Build a deduplicated list of lowered search needles from *text* + *any_text*."""
    seen: set[str] = set()
    terms: list[str] = []
    for raw in [text, *(any_text or [])]:
        low = raw.strip().lower()
        if low and low not in seen:
            seen.add(low)
            terms.append(low)
    return terms


def _format_or_query(text: str, any_text: list[str] | tuple[str, ...] | None = None) -> str:
    """Format a human-readable query label, adding OR when multiple terms exist."""
    parts = [text]
    for t in (any_text or []):
        stripped = t.strip()
        if stripped and stripped.lower() != text.strip().lower():
            parts.append(stripped)
    if len(parts) == 1:
        return parts[0]
    return " OR ".join(f'"{p}"' for p in parts)


def _any_needle_in(needles: list[str], haystack: str) -> str | None:
    """Return the first needle found in *haystack*, or None."""
    for n in needles:
        if n in haystack:
            return n
    return None
_FIND_BY_TEXT_MAX_RESULTS = 100

# Singleton web snapshot generator (stateless, safe to share)
_web_snapshot_generator = WebSnapshotGenerator()
_native_snapshot_generator = NativeSnapshotGenerator()
_SNAPSHOT_SHOW_ARTIFACTS = frozenset({"compact", "full", "refs", "index", "meta"})
_WEB_QUERY_DEFAULT_LIMIT = 20
_WEB_QUERY_MAX_LIMIT = 200
_WEB_TEXT_DEFAULT_LIMIT = 6000
_WEB_TEXT_MAX_LIMIT = 12000

WEB_QUERY_SCRIPT = r"""
return (function(selector, attrs, limit) {
    attrs = Array.isArray(attrs) ? attrs : [];
    limit = Math.max(0, Math.min(Number(limit) || 20, 200));

    function clean(text, max) {
        if (!text) return '';
        return String(text).replace(/\s+/g, ' ').trim().substring(0, max || 160);
    }
    function esc(value) {
        if (window.CSS && CSS.escape) return CSS.escape(String(value));
        return String(value).replace(/[^a-zA-Z0-9_-]/g, function(ch) {
            return '\\' + ch.charCodeAt(0).toString(16) + ' ';
        });
    }
    function quoteAttr(value) {
        return String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
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
        if (/^h[1-6]$/.test(tag)) return 'heading';
        if (tag === 'input') {
            var type = (el.type || 'text').toLowerCase();
            if (type === 'checkbox') return 'checkbox';
            if (type === 'radio') return 'radio';
            if (['submit', 'button', 'image', 'reset'].includes(type)) return 'button';
            if (type === 'range') return 'slider';
            if (type === 'file') return 'file';
            return 'textbox';
        }
        return '';
    }
    function directText(el) {
        var parts = [];
        for (var i = 0; i < el.childNodes.length; i++) {
            var child = el.childNodes[i];
            if (child.nodeType === Node.TEXT_NODE) {
                var text = clean(child.nodeValue, 160);
                if (text) parts.push(text);
            }
        }
        return clean(parts.join(' '), 160);
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
            160
        );
    }
    function generatedSelector(el) {
        var tag = el.tagName.toLowerCase();
        if (el.id) {
            var sameId = document.querySelectorAll('#' + esc(el.id));
            if (sameId.length === 1) return '#' + esc(el.id);
            // Duplicate id: try form-scoped or name-based selector
            var elName = el.getAttribute('name') || '';
            if (elName) {
                var form = el.closest('form');
                if (form) {
                    var formSel = form.id ? 'form#' + esc(form.id)
                        : form.getAttribute('name') ? 'form[name="' + quoteAttr(form.getAttribute('name')) + '"]'
                        : 'form';
                    return formSel + ' ' + tag + '[name="' + quoteAttr(elName) + '"]';
                }
                return tag + '[name="' + quoteAttr(elName) + '"]';
            }
            // No name: use nth-of-type within parent
            var parent = el.parentElement;
            if (parent) {
                var siblings = parent.querySelectorAll('#' + esc(el.id));
                for (var idx = 0; idx < siblings.length; idx++) {
                    if (siblings[idx] === el) return '#' + esc(el.id) + ':nth-of-type(' + (idx + 1) + ')';
                }
            }
            return '#' + esc(el.id);
        }
        var testId = el.getAttribute('data-testid') || '';
        if (testId) return '[data-testid="' + quoteAttr(testId) + '"]';
        if (el.getAttribute('name')) return tag + '[name="' + quoteAttr(el.getAttribute('name')) + '"]';
        if (tag === 'a' && el.getAttribute('href')) return 'a[href="' + quoteAttr(el.getAttribute('href')) + '"]';
        return tag;
    }

    var nodes;
    try {
        nodes = Array.prototype.slice.call(document.querySelectorAll(selector), 0, limit);
    } catch (err) {
        return {error: String(err && err.message ? err.message : err)};
    }
    return nodes.map(function(el) {
        var role = roleOf(el);
        var extra = {};
        var domProps = {checked:1, selected:1, disabled:1, value:1, indeterminate:1};
        attrs.forEach(function(attr) {
            if (!attr) return;
            if (attr in domProps) {
                extra[attr] = el[attr];
            } else {
                extra[attr] = el.getAttribute(attr) || '';
            }
        });
        return {
            tag: el.tagName.toLowerCase(),
            role: role,
            accessible_name: nameOf(el, role),
            id: el.id || '',
            name: el.getAttribute('name') || '',
            type: el.getAttribute('type') || '',
            placeholder: el.getAttribute('placeholder') || '',
            aria_label: el.getAttribute('aria-label') || '',
            data_testid: el.getAttribute('data-testid') || '',
            value: clean(el.value || '', 160),
            text: clean(el.innerText || el.textContent || '', 160),
            href: el.getAttribute('href') || '',
            selector: generatedSelector(el),
            attrs: extra
        };
    });
})(arguments[0], arguments[1], arguments[2]);
"""


WEB_TEXT_SCRIPT = r"""
return (function(selector, offset, limit) {
    function clean(text) {
        if (!text) return '';
        return String(text).replace(/\r\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
    }
    function pickElement() {
        if (selector) {
            return {
                selector: selector,
                element: document.querySelector(selector),
                explicit: true
            };
        }
        var candidates = ['article', 'main', '[role="main"]', 'body'];
        for (var i = 0; i < candidates.length; i++) {
            var el = document.querySelector(candidates[i]);
            if (el && clean(el.innerText || el.textContent || '')) {
                return {selector: candidates[i], element: el, explicit: false};
            }
        }
        return {selector: 'body', element: document.body, explicit: false};
    }

    offset = Math.max(0, Number(offset) || 0);
    limit = Math.max(0, Number(limit) || 0);

    var picked;
    try {
        picked = pickElement();
    } catch (err) {
        return {error: String(err && err.message ? err.message : err)};
    }
    if (!picked.element) {
        return {error: 'No element matching selector: ' + (selector || 'auto')};
    }

    var text = clean(picked.element.innerText || picked.element.textContent || '');
    var total = text.length;
    var slice = text.substring(offset, offset + limit);
    return {
        title: document.title || '',
        url: window.location ? String(window.location.href || '') : '',
        selector: picked.selector,
        explicit_selector: picked.explicit,
        chars: total,
        offset: offset,
        limit: limit,
        returned: slice.length,
        truncated: offset + slice.length < total,
        text: slice
    };
})(arguments[0], arguments[1], arguments[2]);
"""


@dataclass(frozen=True)
class SnapshotResult:
    """Rendered snapshot result plus its persisted artifact bundle."""

    text: str
    data: dict[str, Any]
    raw_text: str
    bundle: SnapshotBundlePayload


def _require_driver():
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    return state.driver


def _register_snapshot(
    context: str, snapshot_obj: Any, ref_map: dict[str, Any] | None = None
) -> None:
    """Store snapshot as current and in per-context maps."""
    if ref_map is None and isinstance(snapshot_obj, (WebSnapshot, NativeSnapshot)):
        ref_map = snapshot_obj.to_ref_map()
    if ref_map is None:
        ref_map = {}
    state.current_snapshot = snapshot_obj
    state.current_ref_map = ref_map
    state.snapshots_by_context[context] = snapshot_obj
    state.ref_maps_by_context[context] = ref_map
    state.ref_resolver.register_all(ref_map, clear_stale=False)
    state.ref_resolver.clear_stale(context)


def _refresh_native_snapshot(
    driver: Any,
    scope: str,
    max_nodes: int | None = None,
    boxes: bool = False,
) -> NativeSnapshot:
    """Generate a native accessibility snapshot (tree-first)."""
    xml_source = driver.page_source

    app_info = ""
    try:
        pkg = driver.current_package
        act = driver.current_activity
        if pkg:
            app_info = f"{pkg}/{act}" if act else pkg
    except Exception:
        pass

    generator = (
        _native_snapshot_generator
        if max_nodes is None
        else NativeSnapshotGenerator(max_nodes=max_nodes)
    )
    snapshot_obj = generator.generate(xml_source, app_info=app_info, context=NATIVE_CONTEXT)
    ref_map = snapshot_obj.to_ref_map()
    _register_snapshot(NATIVE_CONTEXT, snapshot_obj, ref_map)
    return snapshot_obj


def _refresh_web_snapshot(
    driver: Any,
    context: str,
    scope: str,
    depth: int | None = None,
    max_nodes: int | None = None,
    boxes: bool = False,
) -> WebSnapshot:
    """Generate a web DOM snapshot."""
    url = ""
    title = ""
    try:
        url = driver.current_url or ""
    except Exception:
        pass
    try:
        title = driver.title or ""
    except Exception:
        pass

    # Try JS DOM extraction first
    dom_tree: dict[str, Any] | list[dict[str, Any]] | None = None
    try:
        raw = driver.execute_script(
            DOM_EXTRACTION_SCRIPT,
            depth if depth is not None else WEB_DEFAULT_MAX_DEPTH,
            max_nodes if max_nodes is not None else WEB_DEFAULT_MAX_NODES,
        )
        if isinstance(raw, str):
            dom_tree = json.loads(raw)
        elif isinstance(raw, (dict, list)):
            dom_tree = raw
    except Exception as exc:
        logger.debug("JS DOM extraction failed, falling back to HTML parse: %s", exc)

    if dom_tree is not None:
        snapshot_obj, ref_map = _web_snapshot_generator.generate_from_dom(
            dom_tree, context, url, title, scope,
            depth=depth, max_nodes=max_nodes, boxes=boxes,
        )
    else:
        # Fallback to HTML parsing
        html_source = driver.page_source or ""
        snapshot_obj, ref_map = _web_snapshot_generator.generate(
            html_source, context, url, title, scope,
            depth=depth, max_nodes=max_nodes, boxes=boxes,
        )

    _register_snapshot(context, snapshot_obj, ref_map)
    return snapshot_obj


def _snapshot_text(snapshot_obj: NativeSnapshot | WebSnapshot, scope: str, *, boxes: bool) -> str:
    text = snapshot_obj.to_text(scope=scope if scope != "full" else None, boxes=boxes)
    return text if text.endswith("\n") else text + "\n"


def _normalize_ref(ref: str) -> str:
    return parse_ref(ref).ref


def _render_scope(
    snapshot_obj: NativeSnapshot | WebSnapshot,
    *,
    scope: str,
    target: str,
    depth: int | None,
) -> str:
    """Resolve the effective text/artifact scope for a snapshot request."""
    if target:
        clean_ref = _normalize_ref(target)
        if snapshot_obj.find_ref(clean_ref) is None:
            raise ValueError(f"ref '{clean_ref}' not found in snapshot")
        scope = f"ref:{clean_ref}"
    if depth is not None and scope not in ("", "full", "inputs") and not scope.startswith("depth:"):
        scope = f"{scope},depth:{depth}"
    return scope or "full"


def _write_snapshot_bundle(bundle: SnapshotBundlePayload) -> None:
    write_json_artifact(bundle.paths["meta"], bundle.meta_json)
    write_text_artifact(bundle.paths["compact"], bundle.compact_yml)
    write_text_artifact(bundle.paths["full"], bundle.full_yml)
    write_json_artifact(bundle.paths["refs"], bundle.refs_json)
    write_json_artifact(bundle.paths["index"], bundle.index_json)
    write_latest_snapshot_pointer(
        bundle.meta_json,
        source=str(bundle.meta_json.get("source", "")) or None,
        context=str(bundle.meta_json.get("context", "")) or None,
    )


def _format_artifact_metadata(bundle: SnapshotBundlePayload) -> str:
    metadata = bundle.meta_json
    lines = [
        f"snapshot_id: {metadata['snapshot_id']}",
        f"source: {metadata['source']}",
        f"screen_id: {metadata['screen_id']}",
    ]
    for key in ("context", "title", "url"):
        if key in metadata:
            lines.append(f"{key}: {metadata[key]}")
    stats = compute_snapshot_stats(bundle.index_json)
    stats_parts = [
        f"{value} {name}"
        for name, value in stats.items()
        if value or name in {"nodes", "refs"}
    ]
    if stats_parts:
        lines.append(f"stats: {', '.join(stats_parts)}")
    if metadata.get("truncated"):
        lines.append("truncated: true")
    lines.append("artifacts:")
    for name in ("compact", "full", "refs", "index", "meta"):
        lines.append(f"  {name}: {metadata['artifacts'][name]}")
    return "\n".join(lines)


def _read_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_path(snapshot_id_or_latest: str, artifact: str) -> Path:
    if artifact not in _SNAPSHOT_SHOW_ARTIFACTS:
        valid = ", ".join(sorted(_SNAPSHOT_SHOW_ARTIFACTS))
        raise ValueError(f"Unknown snapshot artifact '{artifact}'. Expected one of: {valid}")
    if snapshot_id_or_latest == "latest":
        metadata_path = latest_snapshot_path()
        metadata = _read_json_file(metadata_path)
        artifacts = metadata.get("artifacts", {})
        if isinstance(artifacts, dict) and artifacts.get(artifact):
            return Path(str(artifacts[artifact]))
        snapshot_id = str(metadata.get("snapshot_id", ""))
        if not snapshot_id:
            raise ValueError("Latest snapshot metadata does not include snapshot_id")
        return snapshot_artifact_path(snapshot_id, artifact)
    return snapshot_artifact_path(snapshot_id_or_latest, artifact)


def _read_artifact(snapshot_id_or_latest: str, artifact: str) -> tuple[str, Any]:
    path = _artifact_path(snapshot_id_or_latest, artifact)
    if not path.exists():
        raise FileNotFoundError(f"Snapshot artifact not found: {path}")
    text = path.read_text(encoding="utf-8")
    if artifact in {"meta", "refs", "index"}:
        return text, json.loads(text)
    return text, None


def _load_refs(snapshot_id_or_latest: str) -> dict[str, Any]:
    _text, refs_payload = _read_artifact(snapshot_id_or_latest, "refs")
    if not isinstance(refs_payload, dict):
        return {}
    refs = refs_payload.get("refs", {})
    return refs if isinstance(refs, dict) else {}


def _stale_snapshot_warning(context: str) -> str:
    if not state.ref_resolver.is_stale(context):
        return ""
    reason = state.ref_resolver.stale_reason(context) or "a previous action"
    return (
        f"WARNING: snapshot is stale after {reason}; "
        "call snapshot() before using refs from this output."
    )


def _load_index(snapshot_id_or_latest: str) -> dict[str, Any]:
    _text, index_payload = _read_artifact(snapshot_id_or_latest, "index")
    return index_payload if isinstance(index_payload, dict) else {}


def _find_compact_line_for_ref(compact_text: str, ref: str) -> str:
    marker = f"[ref:{ref}]"
    for line in compact_text.splitlines():
        if marker in line:
            return line.strip()
    return ""


def _matching_compact_lines(compact_text: str, needle: str | list[str], limit: int = 20) -> list[tuple[int, str]]:
    needles = needle if isinstance(needle, list) else [needle]
    needles = [n for n in needles if n]
    if not needles:
        return []
    matches: list[tuple[int, str]] = []
    for line_number, line in enumerate(compact_text.splitlines(), start=1):
        low = line.lower()
        if any(n in low for n in needles):
            matches.append((line_number, line.strip()))
            if len(matches) >= limit:
                break
    return matches


def _search_snippet(item: dict[str, Any]) -> str:
    for key in ("name", "value", "text", "action_target_ref"):
        value = str(item.get(key) or "")
        if value:
            return value
    locator = _locator_hint(item)
    return locator


def _format_compact_field(key: str, value: Any) -> str:
    text = str(value)
    if text == "":
        return ""
    if any(ch.isspace() for ch in text) or any(ch in text for ch in "\"'[]=<>"):
        text = json.dumps(text, ensure_ascii=False)
    return f"{key}={text}"


def _format_compact_bounds_field(key: str, value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return f"{key}=[{','.join(str(part) for part in value)}]"
    return _format_compact_field(key, value)


def _locator_hint(item: dict[str, Any]) -> str:
    strategy = item.get("primary_strategy")
    if not isinstance(strategy, dict):
        strategy = _best_locator_strategy(item)
    if not isinstance(strategy, dict):
        return ""
    by = str(strategy.get("by") or "")
    value = str(strategy.get("value") or "")
    if not by or not value:
        return ""
    return f"{by}: {value}"


def _merge_ref_item(
    ref: str,
    ref_item: dict[str, Any],
    index_items: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    index_item = index_items.get(ref, {}) if index_items else {}
    if isinstance(index_item, dict):
        merged.update(index_item)
    merged.update(ref_item)
    role = str(merged.get("role") or "")
    if "actionable" not in merged:
        # Refs are action targets or stable anchors; preserve explicit false from index.
        merged["actionable"] = True
    if "editable" not in merged:
        merged["editable"] = role == "textbox"
    if "primary_strategy" not in merged:
        strategy = _best_locator_strategy(merged)
        if strategy is not None:
            merged["primary_strategy"] = strategy
    return merged


def _is_native_index(index: dict[str, Any]) -> bool:
    source = str(index.get("source") or "").lower()
    context = str(index.get("context") or "").upper()
    return source == "native" or context == "NATIVE_APP"


def _load_index_ref_items(snapshot_id_or_latest: str) -> dict[str, dict[str, Any]]:
    try:
        index = _load_index(snapshot_id_or_latest)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in index.get("refs", []):
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref") or "")
        if ref:
            result[ref] = item
    return result


def _compact_ref_line(ref: str, item: dict[str, Any], *, rich: bool = False) -> str:
    role = item.get("role", "")
    name = item.get("name", "")
    value = item.get("value")
    suffix = f' "{name}"' if name else ""
    if value not in (None, ""):
        suffix += f' value="{value}"'
    line = f"[ref:{ref}] {role}{suffix}".rstrip()
    if rich:
        fields = [
            _format_compact_field("actionable", str(bool(item.get("actionable"))).lower()),
            _format_compact_field("editable", str(bool(item.get("editable"))).lower()),
            _format_compact_field("locator", _locator_hint(item)),
        ]
        action_target_ref = item.get("action_target_ref")
        if action_target_ref:
            fields.append(_format_compact_field("target", action_target_ref))
        if item.get("path"):
            fields.append(_format_compact_field("path", item.get("path")))
        suffix_fields = " ".join(field for field in fields if field)
        if suffix_fields:
            line = f"{line} {suffix_fields}"
    return line


def _compact_text_target_line(item: dict[str, Any]) -> str:
    text = str(item.get("text") or "")
    line = f"text {json.dumps(text, ensure_ascii=False)}"
    fields = [
        _format_compact_bounds_field("bounds", item.get("bounds", "")),
        f"tap_target=[ref:{item.get('tap_target_ref') or item.get('action_target_ref')}]"
        if item.get("tap_target_ref") or item.get("action_target_ref")
        else "",
        _format_compact_field("target_role", item.get("target_role", "")),
        _format_compact_bounds_field("target_bounds", item.get("target_bounds", "")),
        _format_compact_field(
            "target_actionable",
            str(bool(item.get("target_actionable"))).lower(),
        ),
        _format_compact_field("requested_role", item.get("requested_role", "")),
        _format_compact_field("path", item.get("path", "")),
        _format_compact_field(
            "role_mismatch",
            str(bool(item.get("role_mismatch"))).lower()
            if item.get("role_mismatch")
            else "",
        ),
    ]
    suffix = " ".join(field for field in fields if field)
    return f"{line} {suffix}".rstrip()


def _ref_detail(ref: str, item: dict[str, Any]) -> str:
    lines = [_compact_ref_line(ref, item, rich=True)]
    for key in (
        "context",
        "source_type",
        "expected_bounds",
        "bounds",
        "actionable",
        "editable",
        "action_target_ref",
    ):
        if key in item:
            lines.append(f"{key}: {item[key]}")
    locator = _locator_hint(item)
    if locator:
        lines.append(f"best_locator: {locator}")
    strategies = item.get("strategies")
    if strategies:
        lines.append("strategies:")
        for strategy in strategies:
            if isinstance(strategy, dict):
                lines.append(f"  - {strategy.get('by')}: {strategy.get('value')}")
    return "\n".join(lines)


def _filter_ref_items(
    refs: dict[str, Any],
    role: str = "",
    index_items: dict[str, dict[str, Any]] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    items: list[tuple[str, dict[str, Any]]] = []
    for ref, value in sorted(refs.items(), key=lambda item: item[0]):
        if not isinstance(value, dict):
            continue
        merged = _merge_ref_item(str(ref), value, index_items)
        if role and str(merged.get("role", "")) != role:
            continue
        items.append((ref, merged))
    return items


def _serialize_current_ref_entry(entry: Any) -> dict[str, Any]:
    return {
        "role": getattr(entry, "role", ""),
        "name": getattr(entry, "name", ""),
        "context": getattr(entry, "context", ""),
        "source_type": getattr(entry, "source_type", ""),
        "expected_bounds": list(getattr(entry, "expected_bounds", (0, 0, 0, 0))),
        "strategies": [
            {"by": getattr(strategy, "by", ""), "value": getattr(strategy, "value", "")}
            for strategy in getattr(entry, "strategies", [])
        ],
        **(
            {"action_target_ref": getattr(entry, "action_target_ref")}
            if getattr(entry, "action_target_ref", None)
            else {}
        ),
    }


def _native_ref_paths(snapshot_obj: NativeSnapshot) -> dict[str, str]:
    paths: dict[str, str] = {}

    def node_segment(node: NativeSnapshotNode) -> str:
        segment = node.role
        if node.ref:
            segment += f"[{node.ref}]"
        return segment

    def walk(node: NativeSnapshotNode, ancestors: list[str]) -> None:
        current = [*ancestors, node_segment(node)]
        if node.ref:
            paths[node.ref] = " > ".join(current)
        for child in node.children:
            walk(child, current)

    walk(snapshot_obj.root, [])
    return paths


def _current_native_ref_paths(snapshot_id: str) -> dict[str, str]:
    snapshot_obj = state.current_snapshot
    if not isinstance(snapshot_obj, NativeSnapshot):
        return {}
    if snapshot_id not in ("", "latest") and snapshot_id != state.current_snapshot_id:
        return {}
    return _native_ref_paths(snapshot_obj)


def _is_operable_node(node: NativeSnapshotNode) -> bool:
    return node.actionable or node.scrollable


_CONTEXT_LABEL_KINDS = frozenset({"dialog", "overlay", "sheet", "topbar", "tabs", "selection"})
_MAX_DUPLICATE_LABEL_GROUPS = 5
_MAX_DUPLICATE_REFS_PER_LABEL = 4
_MAX_SELECTED_TARGETS = 8


@dataclass(frozen=True)
class _ActionableTreeRecord:
    ref: str
    role: str
    label: str
    path: str
    state: tuple[str, ...]


def _own_text_label(node: NativeSnapshotNode) -> str:
    value = node.name or node.text
    return str(value).strip() if value is not None else ""


def _own_context_label(node: NativeSnapshotNode) -> str:
    value = node.name or node.text or node.value
    return str(value).strip() if value is not None else ""


def _dedupe_labels(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for label in labels:
        clean = str(label).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        unique.append(clean)
    return unique


def _direct_child_text_labels(node: NativeSnapshotNode) -> list[str]:
    labels: list[str] = []
    for child in node.children:
        if child.role != "text":
            continue
        value = child.name or child.value or child.text
        if value:
            labels.append(str(value))
    return _dedupe_labels(labels)


def _is_context_label_node(node: NativeSnapshotNode) -> bool:
    return bool(node.container_kind in _CONTEXT_LABEL_KINDS and _own_context_label(node))


def _direct_text_label(node: NativeSnapshotNode) -> str:
    own_label = _own_text_label(node)
    if own_label:
        return own_label
    if not node.actionable:
        return ""
    labels = _direct_child_text_labels(node)
    if not labels:
        labels = _collect_descendant_text(node, max_depth=5)
    return " / ".join(_dedupe_labels(labels))


def _actionable_tree_label(node: NativeSnapshotNode) -> str:
    if node.actionable:
        return _direct_text_label(node)
    if _is_context_label_node(node):
        return _own_context_label(node)
    return ""


def _collect_descendant_text(node: NativeSnapshotNode, max_depth: int) -> list[str]:
    """Collect descendant labels through non-operable wrapper branches."""
    if max_depth <= 0:
        return []
    labels: list[str] = []
    for child in node.children:
        if _is_operable_node(child):
            continue
        if child.role == "text":
            value = child.name or child.value or child.text
            if value:
                labels.append(str(value))
        else:
            labels.extend(_collect_descendant_text(child, max_depth - 1))
    return _dedupe_labels(labels)


def _has_operable_descendant(node: NativeSnapshotNode) -> bool:
    return any(
        _is_operable_node(child) or _has_operable_descendant(child)
        for child in node.children
    )


def _actionable_tree_line(node: NativeSnapshotNode) -> str:
    parts = [node.role]
    if node.ref:
        parts.append(f"[ref:{node.ref}]")
    label = _actionable_tree_label(node)
    if label:
        parts.append(json.dumps(label, ensure_ascii=False))
    visible_states = [item for item in node.state if item != "enabled"]
    if visible_states:
        parts.append(f"[{','.join(visible_states)}]")
    metadata: list[str] = []
    if node.container_kind:
        metadata.append(f"kind:{node.container_kind}")
    if node.scrollable:
        direction = node.scroll_direction or "any"
        metadata.append(f"scrollable:{direction}")
    if metadata:
        parts.append(f"[{','.join(metadata)}]")
    if node.value is not None and node.value != label:
        parts.append(f"value={json.dumps(str(node.value), ensure_ascii=False)}")
    return " ".join(parts)


def _note_path_segment(node: NativeSnapshotNode) -> str:
    segment = node.role
    if node.ref:
        segment += f"[{node.ref}]"
    label = _actionable_tree_label(node)
    if label:
        segment += f" {json.dumps(label, ensure_ascii=False)}"
    return segment


def _collect_actionable_tree_records(root: NativeSnapshotNode) -> list[_ActionableTreeRecord]:
    records: list[_ActionableTreeRecord] = []

    def walk(node: NativeSnapshotNode, ancestors: list[str]) -> None:
        current = [*ancestors, _note_path_segment(node)]
        label = _actionable_tree_label(node)
        if node.actionable and node.ref:
            records.append(
                _ActionableTreeRecord(
                    ref=node.ref,
                    role=node.role,
                    label=label,
                    path=" > ".join(current),
                    state=tuple(node.state),
                )
            )
        for child in node.children:
            walk(child, current)

    walk(root, [])
    return records


def _normalize_note_label(label: str) -> str:
    return " ".join(label.split())


def _trim_note_text(text: str, limit: int = 180) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 12].rstrip() + "...[trimmed]"


def _format_record_ref_path(record: _ActionableTreeRecord) -> str:
    return f"[ref:{record.ref}] path={_trim_note_text(record.path)}"


def _duplicate_label_notes(records: list[_ActionableTreeRecord]) -> list[str]:
    grouped: dict[str, list[_ActionableTreeRecord]] = {}
    for record in records:
        label = _normalize_note_label(record.label)
        if not label:
            continue
        grouped.setdefault(label, []).append(record)

    duplicates = [(label, items) for label, items in grouped.items() if len(items) > 1]
    if not duplicates:
        return []

    lines = ["- Duplicate actionable labels detected; choose carefully by ref and parent context before tapping."]
    shown_groups = duplicates[:_MAX_DUPLICATE_LABEL_GROUPS]
    for label, items in shown_groups:
        shown_items = items[:_MAX_DUPLICATE_REFS_PER_LABEL]
        refs = "; ".join(_format_record_ref_path(item) for item in shown_items)
        if len(items) > len(shown_items):
            refs += f"; ... +{len(items) - len(shown_items)} more"
        lines.append(f"  - {json.dumps(label, ensure_ascii=False)}: {refs}")
    if len(duplicates) > len(shown_groups):
        lines.append(f"  - ... {len(duplicates) - len(shown_groups)} more duplicate labels not shown.")
    return lines


def _selected_target_notes(records: list[_ActionableTreeRecord]) -> list[str]:
    selected = [record for record in records if "selected" in record.state]
    if not selected:
        return []

    shown = selected[:_MAX_SELECTED_TARGETS]
    targets: list[str] = []
    for record in shown:
        label = f" {json.dumps(record.label, ensure_ascii=False)}" if record.label else ""
        targets.append(f"[ref:{record.ref}]{label} path={_trim_note_text(record.path)}")
    if len(selected) > len(shown):
        targets.append(f"... +{len(selected) - len(shown)} more")
    return ["- Selected targets: " + "; ".join(targets)]


def _actionable_tree_notes(snapshot_obj: NativeSnapshot) -> list[str]:
    records = _collect_actionable_tree_records(snapshot_obj.root)
    notes = [*_duplicate_label_notes(records), *_selected_target_notes(records)]
    if not notes:
        return []
    return ["Notes:", *notes]


def _render_actionable_tree_node(
    node: NativeSnapshotNode,
    lines: list[str],
    *,
    indent: int,
) -> None:
    if not _is_operable_node(node) and not _has_operable_descendant(node):
        return
    lines.append("  " * indent + _actionable_tree_line(node))
    for child in node.children:
        _render_actionable_tree_node(child, lines, indent=indent + 1)


def _lookup_ref_item(ref: str) -> tuple[str, dict[str, Any]] | None:
    parsed = parse_ref(ref)
    if parsed.snapshot_id:
        try:
            item = _load_refs(parsed.snapshot_id).get(parsed.ref)
            if isinstance(item, dict):
                return parsed.ref, item
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            pass
    else:
        try:
            item = _load_refs("latest").get(parsed.ref)
            if isinstance(item, dict):
                return parsed.ref, item
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            pass
        current_item = state.current_ref_map.get(parsed.ref)
        if current_item is not None:
            return parsed.ref, _serialize_current_ref_entry(current_item)

    try:
        resolved, entry = state.ref_resolver.require_registered(ref)
        return resolved.ref, _serialize_current_ref_entry(entry)
    except ElementNotFoundError:
        return None


def _strategy_rank(source_type: str, strategy: dict[str, Any]) -> int:
    by = str(strategy.get("by", "")).lower()
    value = str(strategy.get("value", ""))
    is_web = source_type.lower() == "web"
    if is_web:
        if by == "css selector":
            return 0
        if by == "xpath" and ("@role=" in value or "@aria-label=" in value):
            return 1
        if by in {"link text", "partial link text"}:
            return 2
        if by == "xpath":
            return 3
        if by == "tag name":
            return 4
        if by == "coordinates":
            return 99
        return 10
    if by == "accessibility_id":
        return 0
    if by == "id":
        return 1
    if by == "xpath":
        return 2
    if by == "coordinates":
        return 99
    return 10


def _best_locator_strategy(item: dict[str, Any]) -> dict[str, Any] | None:
    strategies = [
        strategy for strategy in item.get("strategies", [])
        if isinstance(strategy, dict) and strategy.get("value")
    ]
    if not strategies:
        return None
    source_type = str(item.get("source_type") or item.get("source") or "")
    return min(strategies, key=lambda strategy: _strategy_rank(source_type, strategy))


def _load_ref_items_for_mapping() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    try:
        refs = _load_refs("latest")
        if refs:
            result.update(
                {str(ref): item for ref, item in refs.items() if isinstance(item, dict)}
            )
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        pass
    for ref, entry in state.current_ref_map.items():
        result[str(ref)] = _serialize_current_ref_entry(entry)
    return result


def _map_web_query_ref(item: dict[str, Any], refs: dict[str, dict[str, Any]]) -> str:
    selector = str(item.get("selector") or "")
    role = str(item.get("role") or "")
    accessible_name = str(item.get("accessible_name") or "")
    css_matches: list[str] = []
    role_name_matches: list[str] = []
    for ref, ref_item in refs.items():
        if str(ref_item.get("source_type") or ref_item.get("source") or "").lower() != "web":
            continue
        for strategy in ref_item.get("strategies", []):
            if (
                isinstance(strategy, dict)
                and strategy.get("by") == "css selector"
                and strategy.get("value") == selector
            ):
                css_matches.append(ref)
                break
        if (
            role
            and accessible_name
            and str(ref_item.get("role") or "") == role
            and str(ref_item.get("name") or "") == accessible_name
        ):
            role_name_matches.append(ref)
    if len(css_matches) == 1:
        return css_matches[0]
    if len(role_name_matches) == 1:
        return role_name_matches[0]
    return ""


def _snapshot_result(
    snapshot_obj: NativeSnapshot | WebSnapshot,
    *,
    scope: str,
    target: str = "",
    depth: int | None = None,
    boxes: bool,
    filename: str,
    raw: bool,
) -> SnapshotResult:
    render_scope = _render_scope(snapshot_obj, scope=scope, target=target, depth=depth)
    bundle = create_snapshot_bundle_payload(snapshot_obj, scope=render_scope if render_scope != "full" else None)
    _write_snapshot_bundle(bundle)
    state.current_snapshot_id = bundle.snapshot_id
    state.current_snapshot_metadata = dict(bundle.meta_json)
    state.ref_resolver.mark_current_snapshot(bundle.snapshot_id, bundle.meta_json)
    raw_text = _snapshot_text(snapshot_obj, render_scope, boxes=boxes)
    if filename:
        Path(filename).write_text(raw_text, encoding="utf-8")
    text = raw_text if raw else _format_artifact_metadata(bundle)
    return SnapshotResult(text=text, data=bundle.meta_json, raw_text=raw_text, bundle=bundle)


def refresh_snapshot(
    scope: str = "full",
    target: str = "",
    context: str = "native",
    restore_context: bool = True,
    depth: int | None = None,
    max_nodes: int | None = None,
    boxes: bool = False,
    filename: str = "",
    raw: bool = False,
) -> SnapshotResult:
    """Take a snapshot in the requested context.

    Args:
        scope: snapshot scope filter
        context: "native", "current", "webview", "auto", or exact context name
        restore_context: switch back to original context after snapshot
        depth: max tree depth for web snapshots
        max_nodes: max nodes for web snapshots
        boxes: include bounding boxes (web snapshots)
        filename: save output to file
    """
    driver = _require_driver()
    resolved_context = resolve_context(context, driver)

    if is_web_context(resolved_context):
        with using_context(resolved_context, driver, restore=restore_context):
            snapshot_obj = _refresh_web_snapshot(driver, resolved_context, scope, depth, max_nodes, boxes)
    else:
        with using_context(resolved_context, driver, restore=restore_context):
            snapshot_obj = _refresh_native_snapshot(driver, scope, max_nodes=max_nodes, boxes=boxes)

    return _snapshot_result(
        snapshot_obj,
        scope=scope,
        target=target,
        depth=depth,
        boxes=boxes,
        filename=filename,
        raw=raw,
    )


def snapshot(
    scope: str = "full",
    target: str = "",
    context: str = "native",
    depth: int | None = None,
    max_nodes: int | None = None,
    boxes: bool = False,
    filename: str = "",
    raw: bool = False,
) -> str:
    """Public snapshot entry point."""
    result = refresh_snapshot(
        scope,
        target=target,
        context=context,
        depth=depth,
        max_nodes=max_nodes,
        boxes=boxes,
        filename=filename,
        raw=raw,
    )
    return result.text


def snapshot_show(
    snapshot_id: str = "latest",
    artifact: str = "compact",
    ref: str = "",
    raw: bool = False,
) -> str:
    """Show a persisted snapshot artifact without refreshing device state."""
    try:
        normalized_ref = _normalize_ref(ref) if ref else ""
        if normalized_ref:
            refs = _load_refs(snapshot_id)
            item = refs.get(normalized_ref)
            if not isinstance(item, dict):
                return f"ERROR: ref '{normalized_ref}' not found in snapshot '{snapshot_id}'."
            context = str(item.get("context") or getattr(state.current_snapshot, "context", state.current_context))
            warning = _stale_snapshot_warning(context)
            payload = {"ref": normalized_ref, **item}
            if raw:
                if warning:
                    payload["warning"] = warning
                return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            detail = _ref_detail(normalized_ref, item)
            return "\n".join(part for part in [warning, detail] if part)

        text, data = _read_artifact(snapshot_id, artifact)
        if raw or artifact in {"compact", "full"}:
            return text
        return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return f"ERROR: {exc}"


def snapshot_actionable_tree() -> str:
    """Render the current native snapshot as an operable-only hierarchy."""
    snapshot_obj = state.current_snapshot
    if snapshot_obj is None:
        # Auto-refresh: take a native snapshot so the caller doesn't need
        # to invoke snapshot() separately before snapshot_actionable_tree().
        try:
            refresh_snapshot(scope="full", context="native")
        except Exception as exc:
            return f"ERROR: Failed to auto-refresh snapshot: {exc}"
        snapshot_obj = state.current_snapshot
    if snapshot_obj is None:
        return "ERROR: No snapshot available. Run snapshot() first."
    if isinstance(snapshot_obj, WebSnapshot):
        return (
            "WebView snapshots use the DOM tree as structure; use web_snapshot, "
            "web_refs, or web_query for WebView refs."
        )
    if not isinstance(snapshot_obj, NativeSnapshot):
        return "ERROR: Current snapshot is not a native snapshot."

    lines: list[str] = []
    # If a positional gesture (scroll/swipe/fling/drag) ran since the last
    # snapshot, surface a warning so the agent knows the rendered refs may no
    # longer match on-screen positions. This tool only renders cached state;
    # it does not refresh the device snapshot.
    snapshot_context = getattr(snapshot_obj, "context", state.current_context)
    warning = _stale_snapshot_warning(snapshot_context)
    if warning:
        lines.append(warning)
    _render_actionable_tree_node(snapshot_obj.root, lines, indent=0)
    if not lines or (len(lines) == 1 and lines[0].startswith("WARNING:")):
        if lines:
            return lines[0] + "\nNo operable elements found in current snapshot."
        return "No operable elements found in current snapshot."
    notes = _actionable_tree_notes(snapshot_obj)
    if notes:
        lines.extend(["", *notes])
    return "\n".join(lines)


def snapshot_search(
    text: str,
    snapshot_id: str = "latest",
    role: str = "",
    any_text: list[str] | tuple[str, ...] | None = None,
    raw: bool = False,
) -> str:
    """Search persisted snapshot index/ref artifacts without refreshing device state."""
    needles = _normalize_search_terms(text, any_text)
    multi_term = len(needles) > 1
    query_label = _format_or_query(text, any_text)
    try:
        index = _load_index(snapshot_id)
        refs_by_id = _load_refs(snapshot_id)
        compact_text, _compact_data = _read_artifact(snapshot_id, "compact")
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return f"ERROR: {exc}"

    matches: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    index_items: dict[str, dict[str, Any]] = {}
    native_index = _is_native_index(index)
    effective_snapshot_id = str(index.get("snapshot_id") or snapshot_id)
    ref_paths = _current_native_ref_paths(effective_snapshot_id) if native_index else {}
    for item in index.get("refs", []):
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref", ""))
        if not ref:
            continue
        index_items[ref] = item
        ref_role = str(item.get("role", ""))
        if role and ref_role != role:
            continue
        haystack_parts = [
            ref,
            ref_role,
            str(item.get("name", "")),
            str(item.get("value", "")),
        ]
        ref_detail = refs_by_id.get(ref)
        if isinstance(ref_detail, dict):
            haystack_parts.extend(
                str(ref_detail.get(key, "")) for key in ("name", "role", "source_type")
            )
            for strategy in ref_detail.get("strategies", []):
                if isinstance(strategy, dict):
                    haystack_parts.extend(
                        str(strategy.get(key, "")) for key in ("by", "value")
                    )
        haystack = " ".join(haystack_parts).lower()
        matched_needle = _any_needle_in(needles, haystack)
        if matched_needle is None:
            continue
        merged = _merge_ref_item(ref, ref_detail if isinstance(ref_detail, dict) else {}, {ref: item})
        compact_line = _find_compact_line_for_ref(compact_text, ref)
        match: dict[str, Any] = {
            "ref": ref,
            "role": merged.get("role", ref_role),
            "name": merged.get("name", item.get("name", "")),
            "bounds": merged.get("bounds"),
            "actionable": bool(merged.get("actionable")),
            "editable": bool(merged.get("editable")),
            "locator": _locator_hint(merged),
            "snippet": compact_line or _search_snippet(merged),
        }
        if multi_term:
            match["matched_text"] = matched_needle
        if ref in ref_paths:
            match["path"] = ref_paths[ref]
        for key in ("value", "action_target_ref"):
            if key in merged:
                match[key] = merged[key]
        matches.append(match)
        seen_refs.add(ref)

    for item in index.get("text_targets", []):
        if not isinstance(item, dict):
            continue
        text_value = str(item.get("text") or "")
        if not text_value:
            continue
        target_ref = str(item.get("tap_target_ref") or item.get("action_target_ref") or "")
        if target_ref in seen_refs:
            continue
        target_role = str(item.get("target_role") or "")
        text_role = str(item.get("role") or "")
        role_matches = not role or role in {target_role, text_role}
        if role and not role_matches and not native_index:
            continue
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ("text", "target_name", "target_role", "action_target_ref")
        ).lower()
        matched_needle = _any_needle_in(needles, haystack)
        if matched_needle is None:
            continue

        match = dict(item)
        match["match_type"] = "text_target"
        if target_ref:
            match["ref"] = target_ref
            match["tap_target_ref"] = target_ref
            match["action_target_ref"] = target_ref
            if target_ref in ref_paths:
                match["path"] = ref_paths[target_ref]
        if role and not role_matches:
            match["role_mismatch"] = True
            match["requested_role"] = role
        if multi_term:
            match["matched_text"] = matched_needle
        matches.append(match)

    compact_fallback_allowed = not role or (native_index and not index.get("text_targets"))
    if compact_fallback_allowed and not matches:
        for line_number, line in _matching_compact_lines(compact_text, needles):
            if any(f"[ref:{ref}]" in line for ref in seen_refs):
                continue
            match = {
                "match_type": "compact_line",
                "line": line_number,
                "snippet": line.strip(),
            }
            if role:
                match["requested_role"] = role
                match["role_mismatch"] = True
            matches.append(match)

    if raw:
        return json.dumps(matches, ensure_ascii=False, indent=2, sort_keys=True)
    if not matches:
        return f"No snapshot refs matching '{query_label}' found."
    lines = [f"Snapshot search results for '{query_label}' (total={len(matches)}):"]
    for rank, match in enumerate(matches, start=1):
        prefix = f"{rank}. "
        if match.get("match_type") == "text_target":
            lines.append(prefix + _compact_text_target_line(match))
            continue
        ref = match.get("ref")
        if ref:
            line = prefix + _compact_ref_line(str(ref), match, rich=True)
            snippet = str(match.get("snippet") or "")
            if snippet:
                line += " " + _format_compact_field("snippet", snippet)
            lines.append(line)
        else:
            fields = [
                _format_compact_field("line", match.get("line", "")),
                _format_compact_field("snippet", match.get("snippet", "")),
            ]
            lines.append(prefix + " ".join(field for field in fields if field))
    if role and any(match.get("role_mismatch") for match in matches):
        lines.append(
            f"Note: No direct refs with role '{role}' matched. "
            "Native text targets may be tappable rows/tabs/containers; "
            "use the shown tap_target_ref."
        )
    matched_refs = {
        str(match.get("ref") or match.get("tap_target_ref") or match.get("action_target_ref"))
        for match in matches
        if match.get("ref") or match.get("tap_target_ref") or match.get("action_target_ref")
    }
    if native_index and len(matched_refs) > 1:
        lines.append(
            "Ambiguous native label: multiple operable targets matched. "
            "Inspect snapshot_actionable_tree() and choose by parent region before tapping."
        )
    return "\n".join(lines)


def web_refs(
    snapshot_id: str = "latest",
    ref: str = "",
    role: str = "",
    limit: int = 50,
    offset: int = 0,
    raw: bool = False,
) -> str:
    """List refs or show one ref from a persisted WebView snapshot artifact.

    This tool is Web-only. For native snapshots, use snapshot_actionable_tree.
    """
    try:
        index = _load_index(snapshot_id)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        index = {}
    if _is_native_index(index):
        return (
            "ERROR: web_refs is for WebView snapshots only. "
            "Use snapshot_actionable_tree for native ref enumeration."
        )
    try:
        refs = _load_refs(snapshot_id)
        index_items = _load_index_ref_items(snapshot_id)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return f"ERROR: {exc}"

    normalized_ref = _normalize_ref(ref) if ref else ""
    if normalized_ref:
        item = refs.get(normalized_ref)
        if not isinstance(item, dict):
            return f"ERROR: ref '{normalized_ref}' not found in snapshot '{snapshot_id}'."
        merged = _merge_ref_item(normalized_ref, item, index_items)
        payload = {"ref": normalized_ref, **merged}
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) if raw else _ref_detail(normalized_ref, merged)

    if limit <= 0:
        return "ERROR: limit must be greater than 0."
    if offset < 0:
        return "ERROR: offset must be greater than or equal to 0."

    items = _filter_ref_items(refs, role=role, index_items=index_items)
    total = len(items)
    page = items[offset : offset + limit]
    next_offset = offset + limit if offset + limit < total else None
    has_more = next_offset is not None
    if raw:
        payload = {
            "snapshot_id": snapshot_id,
            "role": role,
            "offset": offset,
            "limit": limit,
            "total": total,
            "returned": len(page),
            "has_more": has_more,
            "next_offset": next_offset,
            "refs": [{"ref": ref_name, **item} for ref_name, item in page],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if not page:
        suffix = f" with role '{role}'" if role else ""
        if total and offset >= total:
            return (
                f"No refs found in snapshot '{snapshot_id}'{suffix} at offset {offset}. "
                f"total={total}."
            )
        return f"No refs found in snapshot '{snapshot_id}'{suffix}."
    lines = [
        f"Web refs for '{snapshot_id}' (total={total}, returned={len(page)}, offset={offset}, limit={limit}):"
    ]
    lines.extend(_compact_ref_line(ref_name, item, rich=True) for ref_name, item in page)
    if has_more:
        lines.append(f"More refs available: next_offset={next_offset}.")
    return "\n".join(lines)


def generate_locator(ref: str, raw: bool = False) -> str:
    """Return the best stored durable locator/selector for a snapshot ref."""
    found = _lookup_ref_item(ref)
    if found is None:
        clean = _normalize_ref(ref)
        return f"ERROR: ref '{clean}' not found in latest refs artifact or current snapshot."
    ref_name, item = found
    best = _best_locator_strategy(item)
    if best is None:
        return "" if raw else f"ERROR: ref '{ref_name}' has no stored locator strategies."
    value = str(best.get("value", ""))
    if raw:
        return value

    lines = [
        f"ref: {ref_name}",
        f"role: {item.get('role', '')}",
        f"name: {item.get('name', '')}",
        f"source_type: {item.get('source_type', '')}",
        f"best: {best.get('by')}: {value}",
        f"locator: {value}",
    ]
    strategies = item.get("strategies")
    if strategies:
        lines.append("strategies:")
        for strategy in strategies:
            if isinstance(strategy, dict):
                marker = " *" if strategy is best else ""
                lines.append(f"  - {strategy.get('by')}: {strategy.get('value')}{marker}")
    return "\n".join(lines)


def _parse_attrs(attrs: str | list[str] | None) -> list[str]:
    if attrs is None:
        return []
    if isinstance(attrs, str):
        raw_items = attrs.split(",")
    else:
        raw_items = []
        for item in attrs:
            raw_items.extend(str(item).split(","))
    parsed: list[str] = []
    for item in raw_items:
        clean = item.strip()
        if clean and clean not in parsed:
            parsed.append(clean)
    return parsed


def _format_web_query_field(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return f"{key}={'true' if value else 'false'}"
    text = str(value)
    if text == "":
        return ""
    if any(ch.isspace() for ch in text) or any(ch in text for ch in "\"'[]=<>"):
        text = json.dumps(text, ensure_ascii=False)
    return f"{key}={text}"


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def web_text(
    selector: str = "",
    offset: int = 0,
    limit: int = _WEB_TEXT_DEFAULT_LIMIT,
    raw: bool = False,
) -> str:
    """Extract readable text from the current WebView/Chrome DOM."""
    driver = _require_driver()
    context = current_context(driver)
    if not is_web_context(context):
        raise AppiumCliError(
            "web_text requires a WebView/Chrome context. Use webview_switch or snapshot --context=webview first.",
            exit_code=FEATURE_NOT_ENABLED,
        )

    safe_offset = max(0, _safe_int(offset, 0))
    requested_limit = _safe_int(limit, _WEB_TEXT_DEFAULT_LIMIT)
    safe_limit = max(0, min(requested_limit, _WEB_TEXT_MAX_LIMIT))
    result = driver.execute_script(WEB_TEXT_SCRIPT, selector or "", safe_offset, safe_limit)
    if isinstance(result, str):
        result = json.loads(result)
    if isinstance(result, dict) and result.get("error"):
        return f"ERROR: {result['error']}"
    if not isinstance(result, dict):
        return "{}" if raw else "No page text found."

    payload = {
        "title": str(result.get("title") or ""),
        "url": str(result.get("url") or ""),
        "selector": str(result.get("selector") or ""),
        "explicit_selector": bool(result.get("explicit_selector")),
        "chars": int(result.get("chars") or 0),
        "offset": int(result.get("offset") or safe_offset),
        "limit": int(result.get("limit") or safe_limit),
        "returned": int(result.get("returned") or 0),
        "truncated": bool(result.get("truncated")),
        "text": str(result.get("text") or ""),
    }
    if raw:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)

    lines = [
        f"title: {payload['title']}",
        f"url: {payload['url']}",
        f"selector: {payload['selector']}",
        f"chars: {payload['chars']}",
        f"offset: {payload['offset']}",
        f"limit: {payload['limit']}",
        f"returned: {payload['returned']}",
        f"truncated: {'true' if payload['truncated'] else 'false'}",
        "text:",
        payload["text"],
    ]
    return "\n".join(lines).rstrip()


def web_query(
    selector: str,
    attrs: str | list[str] | None = None,
    limit: int = _WEB_QUERY_DEFAULT_LIMIT,
    raw: bool = False,
) -> str:
    """Query the current WebView/Chrome DOM with a CSS selector."""
    driver = _require_driver()
    context = current_context(driver)
    if not is_web_context(context):
        raise AppiumCliError(
            "web_query requires a WebView/Chrome context. Use webview_switch or snapshot --context=webview first.",
            exit_code=FEATURE_NOT_ENABLED,
        )

    parsed_attrs = _parse_attrs(attrs)
    try:
        requested_limit = int(limit)
    except (TypeError, ValueError):
        requested_limit = _WEB_QUERY_DEFAULT_LIMIT
    safe_limit = max(0, min(requested_limit, _WEB_QUERY_MAX_LIMIT))
    result = driver.execute_script(WEB_QUERY_SCRIPT, selector, parsed_attrs, safe_limit)
    if isinstance(result, str):
        result = json.loads(result)
    if isinstance(result, dict) and result.get("error"):
        return f"ERROR: {result['error']}"
    if not isinstance(result, list):
        return "[]" if raw else "No matching elements."

    refs = _load_ref_items_for_mapping()
    rows: list[dict[str, Any]] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        row = {
            "tag": str(item.get("tag") or ""),
            "role": str(item.get("role") or ""),
            "accessible_name": str(item.get("accessible_name") or ""),
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "type": str(item.get("type") or ""),
            "placeholder": str(item.get("placeholder") or ""),
            "aria_label": str(item.get("aria_label") or ""),
            "data_testid": str(item.get("data_testid") or ""),
            "value": str(item.get("value") or ""),
            "text": str(item.get("text") or ""),
            "href": str(item.get("href") or ""),
            "selector": str(item.get("selector") or ""),
        }
        extra_attrs = item.get("attrs")
        if isinstance(extra_attrs, dict) and extra_attrs:
            row["attrs"] = {
                str(key): value if isinstance(value, bool) else str(value)
                for key, value in extra_attrs.items()
            }
        mapped_ref = _map_web_query_ref(row, refs)
        if mapped_ref:
            row["ref"] = mapped_ref
        rows.append(row)

    if raw:
        return json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True)
    if not rows:
        return f"No elements matching selector '{selector}'."

    lines = [f"Web query results for '{selector}' (total={len(rows)}):"]
    for index, row in enumerate(rows, start=1):
        fields = [
            _format_web_query_field("ref", row.get("ref", "")),
            _format_web_query_field("tag", row["tag"]),
            _format_web_query_field("role", row["role"] or "-"),
            _format_web_query_field("accessible_name", row["accessible_name"]),
            _format_web_query_field("text", row["text"]),
            _format_web_query_field("selector", row["selector"]),
            _format_web_query_field("id", row["id"]),
            _format_web_query_field("name", row["name"]),
            _format_web_query_field("type", row["type"]),
            _format_web_query_field("placeholder", row["placeholder"]),
            _format_web_query_field("aria-label", row["aria_label"]),
            _format_web_query_field("data-testid", row["data_testid"]),
            _format_web_query_field("href", row["href"]),
            _format_web_query_field("value", row["value"]),
        ]
        if row.get("attrs"):
            for key, value in row["attrs"].items():
                if key == "data-testid" and row.get("data_testid") == value:
                    continue
                formatted = _format_web_query_field(key, value)
                if formatted:
                    fields.append(formatted)
        lines.append(f"{index}. " + " ".join(field for field in fields if field))
    return "\n".join(lines)


_WEB_FORM_URL_DEFAULT_MAX_FIELDS = 50
_WEB_FORM_URL_MAX_FIELDS_CAP = 500
_WEB_FORM_URL_DEFAULT_MAX_VALUE_LENGTH = 200
_WEB_FORM_URL_REDACTED = "[REDACTED]"

_WEB_FORM_URL_BYPASS_WARNING = (
    "Do not use this as frontend E2E validation; no form interaction occurred."
)
_WEB_FORM_URL_GET_PRIVACY_WARNING = (
    "GET submit URLs may expose data in browser history, logs, and referrers."
)

_WEB_FORM_URL_SENSITIVE_NAME_PATTERNS = (
    "password", "passwd", "pwd",
    "token", "csrf", "xsrf", "nonce",
    "secret", "auth", "session", "cookie",
    "credential", "api_key", "apikey", "access_key", "private",
    "otp", "mfa", "2fa", "verification_code", "verificationcode",
)
_WEB_FORM_URL_PIN_CODE_NAME_PATTERNS = ("pin", "code")
_WEB_FORM_URL_AUTOCOMPLETE_SENSITIVE = frozenset({
    "current-password", "new-password",
    "one-time-code",
    "cc-number", "cc-csc",
})

WEB_FORM_URL_SCRIPT = r"""
return (function(targetArg, maxFields) {
    var target = null;
    if (targetArg && typeof targetArg === 'object' && targetArg.nodeType === 1) {
        target = targetArg;
    } else if (typeof targetArg === 'string' && targetArg.length > 0) {
        try {
            target = document.querySelector(targetArg);
        } catch (selectorErr) {
            return {error: 'invalid_selector', message: String(selectorErr)};
        }
    } else {
        return {error: 'no_target', message: 'target argument is required'};
    }
    if (!target) {
        return {error: 'not_found', message: 'target element not found'};
    }
    var form = (target.tagName && target.tagName.toLowerCase() === 'form')
        ? target
        : (target.closest ? target.closest('form') : null);
    if (!form) {
        return {error: 'no_form', message: 'target has no enclosing <form>'};
    }
    var rawAction = form.getAttribute('action');
    if (rawAction === null || rawAction === undefined) rawAction = '';
    var resolvedAction;
    try {
        resolvedAction = new URL(rawAction || '', document.location.href).href;
    } catch (urlErr) {
        resolvedAction = rawAction || document.location.href;
    }
    var fields = [];
    var truncated = false;
    var elements = form.elements ? Array.prototype.slice.call(form.elements) : [];
    var SKIP_TYPES = {'submit': 1, 'button': 1, 'reset': 1, 'image': 1, 'file': 1};

    function labelText(el) {
        var text = '';
        try {
            if (el.labels && el.labels.length) {
                for (var i = 0; i < el.labels.length; i++) {
                    text += ' ' + (el.labels[i].textContent || '');
                }
            }
            if (!text && el.id) {
                var lbl = document.querySelector('label[for="' + el.id.replace(/"/g, '\\"') + '"]');
                if (lbl) text = lbl.textContent || '';
            }
            if (!text) {
                var parent = el.parentElement;
                while (parent) {
                    if (parent.tagName && parent.tagName.toLowerCase() === 'label') {
                        text = parent.textContent || '';
                        break;
                    }
                    parent = parent.parentElement;
                }
            }
        } catch (lblErr) {
            text = '';
        }
        return String(text).replace(/\s+/g, ' ').trim();
    }

    function pushField(el, value) {
        if (fields.length >= maxFields) {
            truncated = true;
            return;
        }
        fields.push({
            name: el.name,
            value: String(value == null ? '' : value),
            tag: el.tagName ? el.tagName.toLowerCase() : '',
            type: (el.type || '').toLowerCase(),
            hidden: ((el.type || '').toLowerCase() === 'hidden'),
            autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
            inputmode: (el.getAttribute('inputmode') || '').toLowerCase(),
            placeholder: el.getAttribute ? (el.getAttribute('placeholder') || '') : '',
            aria_label: el.getAttribute ? (el.getAttribute('aria-label') || '') : '',
            id: el.id || '',
            label: labelText(el)
        });
    }

    var omitted = 0;
    for (var i = 0; i < elements.length; i++) {
        var el = elements[i];
        if (!el || !el.name) { continue; }
        if (el.disabled) { continue; }
        var tag = el.tagName ? el.tagName.toLowerCase() : '';
        var type = (el.type || '').toLowerCase();
        if (tag === 'button') { continue; }
        if (tag === 'input' && SKIP_TYPES[type]) { continue; }
        if (tag === 'select') {
            var options = el.options ? Array.prototype.slice.call(el.options) : [];
            var anySelected = false;
            for (var oi = 0; oi < options.length; oi++) {
                if (options[oi].selected) {
                    anySelected = true;
                    pushField(el, options[oi].value);
                }
            }
            if (!anySelected && options.length && !el.multiple) {
                pushField(el, options[0].value);
            }
            continue;
        }
        if (tag === 'input' && (type === 'checkbox' || type === 'radio')) {
            if (!el.checked) { continue; }
            pushField(el, el.value == null || el.value === '' ? 'on' : el.value);
            continue;
        }
        pushField(el, el.value);
    }
    if (fields.length >= maxFields) {
        // count remaining without enumerating values
        for (var k = i; k < elements.length; k++) {
            var rem = elements[k];
            if (rem && rem.name && !rem.disabled) {
                var rtag = rem.tagName ? rem.tagName.toLowerCase() : '';
                var rtype = (rem.type || '').toLowerCase();
                if (rtag === 'button') continue;
                if (rtag === 'input' && SKIP_TYPES[rtype]) continue;
                omitted++;
            }
        }
    }

    var origin = '';
    try { origin = document.location.origin || ''; } catch (e) { origin = ''; }

    return {
        found: true,
        method: ((form.getAttribute('method') || 'GET').toUpperCase()),
        enctype: (form.getAttribute('enctype') || 'application/x-www-form-urlencoded'),
        action_raw: rawAction,
        action_resolved: resolvedAction,
        page_url: document.location.href,
        page_origin: origin,
        form_selector_hint: (form.id ? '#' + form.id : (form.name ? 'form[name="' + form.name + '"]' : 'form')),
        fields: fields,
        omitted_fields_count: omitted,
        fields_truncated: truncated
    };
})(arguments[0], arguments[1]);
"""


def _wfu_name_matches(value: str, patterns: tuple[str, ...]) -> bool:
    value = (value or "").lower()
    if not value:
        return False
    return any(p in value for p in patterns)


def _wfu_classify_sensitivity(field: dict[str, Any]) -> str | None:
    """Return a reason string when the field is sensitive, else None."""
    if field.get("hidden"):
        return "hidden"
    ftype = (field.get("type") or "").lower()
    if ftype == "password":
        return "type_password"
    autocomplete = (field.get("autocomplete") or "").lower()
    if autocomplete:
        tokens = {tok.strip() for tok in autocomplete.replace(",", " ").split()}
        if tokens & _WEB_FORM_URL_AUTOCOMPLETE_SENSITIVE:
            return "autocomplete"
    name = field.get("name") or ""
    fid = field.get("id") or ""
    if _wfu_name_matches(name, _WEB_FORM_URL_SENSITIVE_NAME_PATTERNS) or _wfu_name_matches(
        fid, _WEB_FORM_URL_SENSITIVE_NAME_PATTERNS
    ):
        return "name_pattern"
    label = field.get("label") or ""
    if _wfu_name_matches(label, _WEB_FORM_URL_SENSITIVE_NAME_PATTERNS):
        return "label_pattern"
    aria = field.get("aria_label") or ""
    if _wfu_name_matches(aria, _WEB_FORM_URL_SENSITIVE_NAME_PATTERNS):
        return "aria_label_pattern"
    placeholder = field.get("placeholder") or ""
    if _wfu_name_matches(placeholder, _WEB_FORM_URL_SENSITIVE_NAME_PATTERNS):
        return "placeholder_pattern"
    inputmode = (field.get("inputmode") or "").lower()
    if inputmode == "numeric" and _wfu_name_matches(name, _WEB_FORM_URL_PIN_CODE_NAME_PATTERNS):
        return "name_pattern"
    return None


def _wfu_truncate(value: str, max_len: int) -> tuple[str, bool]:
    if max_len <= 0 or value is None:
        return value, False
    if len(value) <= max_len:
        return value, False
    return value[:max_len], True


def _wfu_build_url(action: str, fields: list[dict[str, Any]]) -> str:
    """Build URL by appending fields as query params."""
    from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

    pairs: list[tuple[str, str]] = []
    for f in fields:
        pairs.append((str(f["name"]), str(f["display_value"])))
    encoded = urlencode(pairs, doseq=True)
    parsed = urlparse(action)
    existing = parsed.query
    if existing:
        existing_pairs = parse_qsl(existing, keep_blank_values=True)
        merged_pairs = existing_pairs + pairs
        new_query = urlencode(merged_pairs, doseq=True)
    else:
        new_query = encoded
    return urlunparse(parsed._replace(query=new_query))


def web_form_url(
    target: str,
    max_fields: int = _WEB_FORM_URL_DEFAULT_MAX_FIELDS,
    max_value_length: int = _WEB_FORM_URL_DEFAULT_MAX_VALUE_LENGTH,
    names_only: bool = False,
    raw: bool = False,
) -> str:
    """Inspect an HTML form and report its submit target without interacting with the page.

    This is a read-only diagnostic. No navigation, click, submit, or DOM mutation occurs.
    Use ``goto`` or ``fill``/``click`` when you actually need to drive the frontend.
    """
    from urllib.parse import urlparse

    driver = _require_driver()
    context = current_context(driver)
    if not is_web_context(context):
        raise AppiumCliError(
            "web_form_url requires a WebView/Chrome context. "
            "Use webview_switch or snapshot --context=webview first.",
            exit_code=FEATURE_NOT_ENABLED,
        )

    if not isinstance(target, str) or not target.strip():
        raise AppiumCliError("web_form_url requires a CSS selector or web_* ref as target.")
    target = target.strip()

    try:
        capped_max_fields = max(1, min(int(max_fields), _WEB_FORM_URL_MAX_FIELDS_CAP))
    except (TypeError, ValueError):
        capped_max_fields = _WEB_FORM_URL_DEFAULT_MAX_FIELDS
    try:
        capped_max_value_length = max(0, int(max_value_length))
    except (TypeError, ValueError):
        capped_max_value_length = _WEB_FORM_URL_DEFAULT_MAX_VALUE_LENGTH

    # Resolve a snapshot ref to an element when applicable; otherwise pass the
    # selector string directly to the JS snippet so it can call querySelector.
    js_target: Any = target
    if state.ref_resolver.get_entry(target.strip("[]").removeprefix("ref:")) is not None:
        try:
            from appium_cli.tools.actions import _resolve_element  # local import to avoid cycle
            element = _resolve_element(target)
            if isinstance(element, _CoordinateElement):
                raise AppiumCliError("web_form_url ref must resolve to a real element, not coordinates.")
            js_target = element
        except ElementNotFoundError as exc:
            raise AppiumCliError(str(exc)) from exc

    try:
        result = driver.execute_script(WEB_FORM_URL_SCRIPT, js_target, capped_max_fields)
    except Exception as exc:  # noqa: BLE001 - convert to CLI error at boundary
        raise AppiumCliError(f"web_form_url failed to evaluate form: {exc}") from exc

    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError as exc:
            raise AppiumCliError(f"web_form_url returned non-JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise AppiumCliError("web_form_url returned unexpected payload.")

    if result.get("error"):
        err = result.get("error")
        message = result.get("message") or err
        if err in {"not_found", "no_target"}:
            raise AppiumCliError(
                f"web_form_url: target '{target}' not found in the current DOM. {message}"
            )
        if err == "no_form":
            raise AppiumCliError(
                f"web_form_url: target '{target}' has no enclosing <form>. "
                "Provide a selector that matches a form or an element inside one."
            )
        if err == "invalid_selector":
            raise AppiumCliError(f"web_form_url: invalid selector '{target}'. {message}")
        raise AppiumCliError(f"web_form_url: {message}")

    method = str(result.get("method") or "GET").upper()
    action_raw = str(result.get("action_raw") or "")
    action_resolved = str(result.get("action_resolved") or "")
    enctype = str(result.get("enctype") or "application/x-www-form-urlencoded")
    page_origin = str(result.get("page_origin") or "")
    raw_fields = result.get("fields") or []
    omitted_count = int(result.get("omitted_fields_count") or 0)

    warnings: list[str] = [_WEB_FORM_URL_BYPASS_WARNING]

    # Classify the action scheme
    action_scheme = ""
    try:
        action_scheme = (urlparse(action_resolved).scheme or "").lower()
    except Exception:  # noqa: BLE001
        action_scheme = ""

    is_http = action_scheme in {"http", "https"}
    non_http_action = bool(action_raw) and not is_http and action_scheme in {
        "javascript", "mailto", "data", "tel", "sms", "file", "blob",
    }

    # Cross-origin detection
    cross_origin = False
    if is_http and page_origin:
        try:
            action_parsed = urlparse(action_resolved)
            action_origin = f"{action_parsed.scheme}://{action_parsed.netloc}"
            if action_origin and action_origin != page_origin:
                cross_origin = True
        except Exception:  # noqa: BLE001
            cross_origin = False

    # Build redacted field list
    fields_out: list[dict[str, Any]] = []
    for raw_field in raw_fields:
        if not isinstance(raw_field, dict):
            continue
        name = str(raw_field.get("name") or "")
        if not name:
            continue
        value = str(raw_field.get("value") or "")
        reason = _wfu_classify_sensitivity(raw_field)
        redacted = bool(reason) or names_only
        if names_only and not reason:
            reason = "names_only"
        if redacted:
            display_value = _WEB_FORM_URL_REDACTED
            truncated = False
        else:
            display_value, truncated = _wfu_truncate(value, capped_max_value_length)
        item: dict[str, Any] = {
            "name": name,
            "type": raw_field.get("type") or "",
            "tag": raw_field.get("tag") or "",
            "source": raw_field.get("tag") or "input",
            "included": True,
            "redacted": redacted,
            "value": display_value,
            "display_value": display_value,
        }
        if truncated:
            item["truncated"] = True
        if reason:
            item["reason"] = reason
        fields_out.append(item)

    # Decide whether to emit a URL
    emit_url = is_http and method == "GET" and not names_only

    url_value = ""
    payload_summary: list[dict[str, Any]] = []
    if emit_url:
        url_value = _wfu_build_url(action_resolved, fields_out)
    else:
        for f in fields_out:
            payload_summary.append({
                "name": f["name"],
                "redacted": f["redacted"],
                "reason": f.get("reason"),
            })

    if method != "GET":
        warnings.append("post_no_replay_url: POST form; no submit URL is produced.")
    elif non_http_action:
        warnings.append("non_http_action: form action scheme is not http(s); no URL produced.")
    elif names_only:
        warnings.append("names_only: values and URL omitted by request.")
    elif emit_url:
        warnings.append(_WEB_FORM_URL_GET_PRIVACY_WARNING)
        if cross_origin:
            warnings.append("cross_origin_action: form action targets a different origin.")
    if result.get("fields_truncated") or omitted_count:
        warnings.append(
            f"max_fields_truncated: {omitted_count} additional field(s) were omitted; "
            "increase --max-fields to see them."
        )
    if not fields_out:
        warnings.append("empty_form: no submittable named fields found.")

    redacted_names = [f["name"] for f in fields_out if f["redacted"]]
    if redacted_names and not names_only:
        warnings.append("redacted_fields: sensitive field values were not included.")

    payload: dict[str, Any] = {
        "inspection_only": True,
        "frontend_interaction_skipped": True,
        "selector": target,
        "method": method,
        "action": action_resolved,
        "action_raw": action_raw,
        "enctype": enctype,
        "page_origin": page_origin,
        "cross_origin_action": cross_origin,
        "non_http_action": non_http_action,
        "fields": fields_out,
        "omitted_fields_count": omitted_count,
        "warnings": warnings,
    }
    if emit_url:
        payload["url"] = url_value
    else:
        payload["payload_summary"] = payload_summary

    if raw:
        # Do not expose internal display_value alias key in raw output.
        for f in payload["fields"]:
            f.pop("display_value", None)
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)

    # Compact human/LLM-readable text output
    lines: list[str] = []
    lines.append("Inspection only: no frontend interaction was performed.")
    lines.append("frontend_interaction_skipped: true")
    lines.append(f"method: {method}")
    lines.append(f"action: {action_resolved}")
    if emit_url:
        lines.append(f"url: {url_value}")
    elif method != "GET":
        lines.append("url: (none; POST form, payload summary below)")
    elif non_http_action:
        lines.append("url: (none; non-http action)")
    elif names_only:
        lines.append("url: (omitted; --names-only)")
    included = [f["name"] for f in fields_out if not f["redacted"]]
    if included:
        lines.append("included_fields: " + ", ".join(included))
    if redacted_names:
        lines.append("redacted_fields: " + ", ".join(redacted_names))
    if not emit_url and payload_summary:
        lines.append("payload_summary:")
        for f in payload_summary:
            tag = "[REDACTED]" if f["redacted"] else "[included]"
            reason = f" ({f['reason']})" if f.get("reason") else ""
            lines.append(f"  - {f['name']}: {tag}{reason}")
    if omitted_count:
        lines.append(f"omitted_fields_count: {omitted_count}")
    lines.append("warnings:")
    for w in warnings:
        lines.append(f"  - {w}")
    return "\n".join(lines)


def web_snapshot(
    scope: str = "full",
    target: str = "",
    depth: int | None = None,
    max_nodes: int | None = None,
    boxes: bool = False,
    filename: str = "",
    raw: bool = False,
) -> str:
    """Convenience alias for ``snapshot --context=webview``."""
    return snapshot(
        scope,
        target=target,
        context="webview",
        depth=depth,
        max_nodes=max_nodes,
        boxes=boxes,
        filename=filename,
        raw=raw,
    )


def _find_element(ref: str):
    normalized = _normalize_ref(ref)
    snapshot_obj = state.current_snapshot
    if not snapshot_obj:
        return None
    return snapshot_obj.find_ref(normalized)


def describe(ref: str) -> str:
    if state.current_snapshot is None:
        return "ERROR: No snapshot available. Run snapshot() first."
    try:
        parsed, _entry = state.ref_resolver.require_registered(ref)
    except ElementNotFoundError as exc:
        return f"ERROR: {exc}"
    if parsed.snapshot_id and parsed.snapshot_id != state.current_snapshot_id:
        return (
            f"ERROR: Snapshot '{parsed.snapshot_id}' is not loaded in memory. "
            "Run snapshot() in this session before describing that qualified ref."
        )
    return state.current_snapshot.describe_ref(parsed.ref)


def find_by_text(text: str, scope: str = "full", any_text: list[str] | tuple[str, ...] | None = None) -> str:
    if state.current_snapshot is None:
        return "ERROR: No snapshot available. Run snapshot() first."
    snapshot_obj = state.current_snapshot
    inputs_only = scope == "inputs"
    query_label = _format_or_query(text, any_text)
    terms = _normalize_search_terms(text, any_text)

    # Collect matches across all terms, dedup by node identity keeping best score.
    best_by_node: dict[int, Any] = {}  # id(node) -> match object
    for term in terms:
        for match in snapshot_obj.find_text(term, inputs_only=inputs_only):
            node_id = id(match.node)
            existing = best_by_node.get(node_id)
            if existing is None or match.score > existing.score:
                best_by_node[node_id] = match
    matches = sorted(best_by_node.values(), key=lambda m: (-m.score, m.node.name))

    if not matches:
        return f"No elements matching '{query_label}' found."
    shown_matches = matches[:_FIND_BY_TEXT_MAX_RESULTS]
    lines = [
        f"Search results for '{query_label}' (total={len(matches)}, shown={len(shown_matches)}):"
    ]
    for match in shown_matches:
        target_ref = match.target.ref if match.target and match.target.ref else ""
        if match.node.ref:
            lines.append(
                f"  [ref:{match.node.ref}] {match.node.role} \"{match.node.name}\" (score={match.score})"
            )
        elif target_ref:
            lines.append(
                f"  {match.node.role} \"{match.node.name}\" (score={match.score}) -> action target [ref:{target_ref}]"
            )
        else:
            lines.append(
                f"  {match.node.role} \"{match.node.name}\" (score={match.score})"
            )
    if len(matches) > len(shown_matches):
        lines.append(f"... {len(matches) - len(shown_matches)} more matches not shown.")
    return "\n".join(lines)


def screenshot(region: str = "full", filename: str = "") -> str:
    import base64

    from appium_cli.utils.paths import read_current_session, screenshot_path, session_artifact_dir

    driver = _require_driver()
    b64 = driver.get_screenshot_as_base64()

    result: dict = {
        "type": "screenshot",
        "image_base64": b64,
        "region": region,
    }

    # Named file output
    if filename:
        from pathlib import Path
        png_path = Path(filename)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_bytes(base64.b64decode(b64))
        result["path"] = str(png_path)
        result["size_bytes"] = png_path.stat().st_size
        result["mime_type"] = "image/png"
    else:
        sid = read_current_session()
        if sid:
            artifact_dir = session_artifact_dir(sid)
            artifact_dir.mkdir(parents=True, exist_ok=True)
            png_path = screenshot_path(sid)
            png_path.write_bytes(base64.b64decode(b64))
            result["path"] = str(png_path)
            result["size_bytes"] = png_path.stat().st_size
            result["mime_type"] = "image/png"

    return json.dumps(result)


def get_page_source(context: str = "native", raw: bool = False) -> str:
    """Return page source: compressed XML for native, raw HTML for web."""
    driver = _require_driver()
    target = resolve_context(context, driver)

    if is_web_context(target):
        with using_context(target, driver, restore=True):
            return driver.page_source or ""
    else:
        with using_context(target, driver, restore=True):
            page_source = driver.page_source or ""
            return page_source if raw else compress_xml(page_source)


def webview_url() -> str:
    """Return the current WebView URL."""
    driver = _require_driver()
    ctx = current_context(driver)
    if not is_web_context(ctx):
        raise AppiumCliError(
            "Not in a WebView context. Use switch_context or snapshot --context=webview first.",
            exit_code=FEATURE_NOT_ENABLED,
        )
    try:
        return driver.current_url or ""
    except Exception as exc:
        raise AppiumCliError(f"Failed to get WebView URL: {exc}") from exc


def webview_title() -> str:
    """Return the current WebView page title."""
    driver = _require_driver()
    ctx = current_context(driver)
    if not is_web_context(ctx):
        raise AppiumCliError(
            "Not in a WebView context. Use switch_context or snapshot --context=webview first.",
            exit_code=FEATURE_NOT_ENABLED,
        )
    try:
        return driver.title or ""
    except Exception as exc:
        raise AppiumCliError(f"Failed to get WebView title: {exc}") from exc


# ---------------------------------------------------------------------------
# Console messages
# ---------------------------------------------------------------------------

_LOG_LEVELS = {"error", "warning", "info", "debug", "all"}


def console_messages(level: str = "all") -> str:
    """Read browser console messages from the WebView/Chrome context.

    Uses ``driver.get_log('browser')`` when in a WebView context and
    falls back to ``driver.get_log('logcat')`` (filtered for chromium
    messages) in native context.

    Note: ``get_log`` is *consumptive* -- each call clears returned entries
    from the server. Subsequent calls return only *new* messages.
    """
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    driver = state.driver
    lvl = level.lower().strip()
    if lvl not in _LOG_LEVELS:
        raise AppiumCliError(
            f"Invalid level '{level}'. Use one of: {', '.join(sorted(_LOG_LEVELS))}",
        )

    ctx = state.current_context
    entries: list[dict] = []
    try:
        if is_web_context(ctx):
            # Try 'browser' first (ChromeDriver), fall back to logcat
            for log_type in ("browser", "logcat"):
                try:
                    raw = driver.get_log(log_type)
                    if log_type == "logcat":
                        entries = [e for e in raw if "chromium" in str(e.get("message", "")).lower()
                                   or "console" in str(e.get("message", "")).lower()]
                    else:
                        entries = raw
                    break
                except Exception:
                    continue
            else:
                raise AppiumCliError("Neither 'browser' nor 'logcat' log type is available.")
        else:
            raw = driver.get_log("logcat")
            entries = [e for e in raw if "chromium" in str(e.get("message", "")).lower()
                       or "console" in str(e.get("message", "")).lower()]
    except Exception as exc:
        raise AppiumCliError(f"Failed to get console logs: {exc}") from exc

    # Filter by level
    if lvl != "all":
        level_map = {"error": {"SEVERE"}, "warning": {"WARNING"}, "info": {"INFO"}, "debug": {"DEBUG", "FINE"}}
        allowed = level_map.get(lvl, set())
        entries = [e for e in entries if str(e.get("level", "")).upper() in allowed]

    if not entries:
        return "No console messages."

    lines: list[str] = []
    for e in entries:
        entry_level = str(e.get("level", "INFO")).upper()
        msg = str(e.get("message", ""))
        lines.append(f"[{entry_level}] {msg}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Network requests
# ---------------------------------------------------------------------------


def network_requests(filter: str = "", static: bool = False) -> str:
    """Read network requests from ChromeDriver performance log.

    Requires that the session was started with ``--enable-network-log`` so
    that ``goog:loggingPrefs: {"performance": "ALL"}`` was set in capabilities.

    Returns a numbered list of requests.  Use ``--filter`` to restrict by URL
    regexp.  Static resources (images, fonts, stylesheets, scripts) are
    excluded by default unless ``--static`` is passed.
    """
    if state.driver is None:
        raise ValueError("Driver is not initialized")

    if not state.session_metadata.get("network_log_enabled"):
        raise AppiumCliError(
            "Network logging is not enabled. "
            "Restart the session with: appium-cli session start --enable-network-log",
            exit_code=FEATURE_NOT_ENABLED,
        )

    driver = state.driver
    try:
        raw_logs = driver.get_log("performance")
    except Exception as exc:
        raise AppiumCliError(f"Failed to get performance logs: {exc}") from exc

    import re as _re

    filter_re = _re.compile(filter, _re.IGNORECASE) if filter else None

    _STATIC_TYPES = {"Image", "Font", "Stylesheet", "Script", "Media"}
    _STATIC_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
                    ".woff", ".woff2", ".ttf", ".eot", ".otf",
                    ".css", ".js", ".mjs"}

    requests_map: dict[str, dict] = {}
    for entry in raw_logs:
        try:
            outer = json.loads(entry.get("message", "{}"))
            msg = outer.get("message", {})
        except (json.JSONDecodeError, AttributeError):
            continue

        method = msg.get("method", "")
        params = msg.get("params", {})

        if method == "Network.requestWillBeSent":
            req = params.get("request", {})
            req_id = params.get("requestId", "")
            url = req.get("url", "")
            if not url or url.startswith("data:"):
                continue
            requests_map[req_id] = {
                "url": url,
                "method": req.get("method", "GET"),
                "type": params.get("type", ""),
                "status": None,
                "status_text": "",
                "mime": "",
            }
        elif method == "Network.responseReceived":
            req_id = params.get("requestId", "")
            resp = params.get("response", {})
            if req_id in requests_map:
                requests_map[req_id]["status"] = resp.get("status")
                requests_map[req_id]["status_text"] = resp.get("statusText", "")
                requests_map[req_id]["mime"] = resp.get("mimeType", "")
                if not requests_map[req_id]["type"]:
                    requests_map[req_id]["type"] = params.get("type", "")

    results: list[dict] = []
    for info in requests_map.values():
        url = info["url"]
        res_type = info.get("type", "")

        # Filter static resources
        if not static:
            if res_type in _STATIC_TYPES:
                continue
            from pathlib import PurePosixPath
            url_path = PurePosixPath(url.split("?")[0].split("#")[0])
            if url_path.suffix.lower() in _STATIC_EXTS:
                continue

        # Apply URL filter
        if filter_re and not filter_re.search(url):
            continue

        results.append(info)

    if not results:
        return "No network requests captured."

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        status = r["status"] if r["status"] is not None else "pending"
        line = f"{i}. {r['method']} {status} {r['url']}"
        if r.get("mime"):
            line += f" ({r['mime']})"
        lines.append(line)
    return "\n".join(lines)
