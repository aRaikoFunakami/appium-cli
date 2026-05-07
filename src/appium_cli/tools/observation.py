"""Observation tools."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from appium_cli.core.ref_resolver import ElementNotFoundError, parse_ref
from appium_cli.core.native_snapshot import NativeSnapshot
from appium_cli.core.native_snapshot_generator import NativeSnapshotGenerator
from appium_cli.core.snapshot import compress_xml
from appium_cli.core.snapshot_artifacts import SnapshotBundlePayload, create_snapshot_bundle_payload
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
_FIND_BY_TEXT_MAX_RESULTS = 100

# Singleton web snapshot generator (stateless, safe to share)
_web_snapshot_generator = WebSnapshotGenerator()
_native_snapshot_generator = NativeSnapshotGenerator()
_SNAPSHOT_SHOW_ARTIFACTS = frozenset({"compact", "full", "refs", "index", "meta"})
_WEB_QUERY_DEFAULT_LIMIT = 20
_WEB_QUERY_MAX_LIMIT = 200

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
        if (el.id) return '#' + esc(el.id);
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
        attrs.forEach(function(attr) {
            if (attr) extra[attr] = el.getAttribute(attr) || '';
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
    state.ref_resolver.register_all(ref_map)


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


def _load_index(snapshot_id_or_latest: str) -> dict[str, Any]:
    _text, index_payload = _read_artifact(snapshot_id_or_latest, "index")
    return index_payload if isinstance(index_payload, dict) else {}


def _find_compact_line_for_ref(compact_text: str, ref: str) -> str:
    marker = f"[ref:{ref}]"
    for line in compact_text.splitlines():
        if marker in line:
            return line.strip()
    return ""


def _matching_compact_lines(compact_text: str, needle: str, limit: int = 20) -> list[tuple[int, str]]:
    if not needle:
        return []
    matches: list[tuple[int, str]] = []
    for line_number, line in enumerate(compact_text.splitlines(), start=1):
        if needle in line.lower():
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
        suffix_fields = " ".join(field for field in fields if field)
        if suffix_fields:
            line = f"{line} {suffix_fields}"
    return line


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
            payload = {"ref": normalized_ref, **item}
            return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) if raw else _ref_detail(normalized_ref, item)

        text, data = _read_artifact(snapshot_id, artifact)
        if raw or artifact in {"compact", "full"}:
            return text
        return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return f"ERROR: {exc}"


def snapshot_search(
    text: str,
    snapshot_id: str = "latest",
    role: str = "",
    raw: bool = False,
) -> str:
    """Search persisted snapshot index/ref artifacts without refreshing device state."""
    needle = text.lower()
    try:
        index = _load_index(snapshot_id)
        refs_by_id = _load_refs(snapshot_id)
        compact_text, _compact_data = _read_artifact(snapshot_id, "compact")
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        return f"ERROR: {exc}"

    matches: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    index_items: dict[str, dict[str, Any]] = {}
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
        if needle not in " ".join(haystack_parts).lower():
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
        for key in ("value", "action_target_ref"):
            if key in merged:
                match[key] = merged[key]
        matches.append(match)
        seen_refs.add(ref)

    if not role:
        for line_number, line in _matching_compact_lines(compact_text, needle):
            if any(f"[ref:{ref}]" in line for ref in seen_refs):
                continue
            matches.append(
                {
                    "line": line_number,
                    "snippet": line.strip(),
                }
            )

    if raw:
        return json.dumps(matches, ensure_ascii=False, indent=2, sort_keys=True)
    if not matches:
        return f"No snapshot refs matching '{text}' found."
    lines = [f"Snapshot search results for '{text}' (total={len(matches)}):"]
    for rank, match in enumerate(matches, start=1):
        prefix = f"{rank}. "
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
    return "\n".join(lines)


def snapshot_refs(
    snapshot_id: str = "latest",
    ref: str = "",
    role: str = "",
    raw: bool = False,
) -> str:
    """List refs or show one ref from a persisted snapshot artifact."""
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

    items = _filter_ref_items(refs, role=role, index_items=index_items)
    if raw:
        payload = [{"ref": ref_name, **item} for ref_name, item in items]
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if not items:
        suffix = f" with role '{role}'" if role else ""
        return f"No refs found in snapshot '{snapshot_id}'{suffix}."
    lines = [f"Snapshot refs for '{snapshot_id}' (total={len(items)}):"]
    lines.extend(_compact_ref_line(ref_name, item, rich=True) for ref_name, item in items)
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
    text = str(value)
    if text == "":
        return ""
    if any(ch.isspace() for ch in text) or any(ch in text for ch in "\"'[]=<>"):
        text = json.dumps(text, ensure_ascii=False)
    return f"{key}={text}"


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
            row["attrs"] = {str(key): str(value) for key, value in extra_attrs.items()}
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


def find_by_text(text: str, scope: str = "full") -> str:
    if state.current_snapshot is None:
        return "ERROR: No snapshot available. Run snapshot() first."
    snapshot_obj = state.current_snapshot
    inputs_only = scope == "inputs"
    matches = snapshot_obj.find_text(text, inputs_only=inputs_only)
    if not matches:
        return f"No elements matching '{text}' found."
    shown_matches = matches[:_FIND_BY_TEXT_MAX_RESULTS]
    lines = [
        f"Search results for '{text}' (total={len(matches)}, shown={len(shown_matches)}):"
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
