"""Observation tools."""

from __future__ import annotations

import json
import logging
from typing import Any

from appium_cli.core.snapshot import compress_xml
from appium_cli.core.web_snapshot import WebSnapshot
from appium_cli.core.web_snapshot_generator import DOM_EXTRACTION_SCRIPT, WebSnapshotGenerator
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

logger = logging.getLogger(__name__)

# Singleton web snapshot generator (stateless, safe to share)
_web_snapshot_generator = WebSnapshotGenerator()


def _require_driver():
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    return state.driver


def _register_snapshot(
    context: str, snapshot_obj: Any, ref_map: dict[str, Any] | None = None
) -> None:
    """Store snapshot as current and in per-context maps."""
    if ref_map is None and isinstance(snapshot_obj, WebSnapshot):
        ref_map = snapshot_obj.to_ref_map()
    if ref_map is None:
        ref_map = {}
    state.current_snapshot = snapshot_obj
    state.current_ref_map = ref_map
    state.snapshots_by_context[context] = snapshot_obj
    state.ref_maps_by_context[context] = ref_map
    state.ref_resolver.register_all(ref_map)


def _refresh_native_snapshot(driver: Any, scope: str) -> str:
    """Generate a native accessibility snapshot (original path)."""
    xml_source = driver.page_source

    app_info = ""
    try:
        pkg = driver.current_package
        act = driver.current_activity
        if pkg:
            app_info = f"{pkg}/{act}" if act else pkg
    except Exception:
        pass

    try:
        window_size = driver.get_window_size()
        state.snapshot_generator.screen_width = int(window_size["width"])
        state.snapshot_generator.screen_height = int(window_size["height"])
    except Exception:
        pass

    snapshot_obj, ref_map = state.snapshot_generator.generate(
        xml_source, app_info=app_info, scope=scope
    )
    _register_snapshot(NATIVE_CONTEXT, snapshot_obj, ref_map)
    return snapshot_obj.to_text(scope=scope if scope != "full" else None)


def _refresh_web_snapshot(
    driver: Any,
    context: str,
    scope: str,
    depth: int | None = None,
    max_nodes: int | None = None,
    boxes: bool = False,
) -> str:
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
        raw = driver.execute_script(DOM_EXTRACTION_SCRIPT, depth or 15, max_nodes or 300)
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
    if isinstance(snapshot_obj, WebSnapshot):
        return snapshot_obj.to_text(scope=scope if scope != "full" else None, boxes=boxes)
    return snapshot_obj.to_text(scope=scope if scope != "full" else None)


def refresh_snapshot(
    scope: str = "full",
    context: str = "native",
    restore_context: bool = True,
    depth: int | None = None,
    max_nodes: int | None = None,
    boxes: bool = False,
    filename: str = "",
) -> str:
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
    target = resolve_context(context, driver)

    if is_web_context(target):
        with using_context(target, driver, restore=restore_context):
            result = _refresh_web_snapshot(driver, target, scope, depth, max_nodes, boxes)
    else:
        with using_context(target, driver, restore=restore_context):
            result = _refresh_native_snapshot(driver, scope)

    if filename:
        from pathlib import Path
        Path(filename).write_text(result, encoding="utf-8")

    return result


def snapshot(
    scope: str = "full",
    context: str = "native",
    depth: int | None = None,
    max_nodes: int | None = None,
    boxes: bool = False,
    filename: str = "",
) -> str:
    """Public snapshot entry point."""
    return refresh_snapshot(
        scope, context=context, depth=depth, max_nodes=max_nodes, boxes=boxes, filename=filename,
    )


def web_snapshot(
    scope: str = "full",
    depth: int | None = None,
    max_nodes: int | None = None,
    boxes: bool = False,
    filename: str = "",
) -> str:
    """Convenience alias for ``snapshot --context=webview``."""
    return snapshot(
        scope,
        context="webview",
        depth=depth,
        max_nodes=max_nodes,
        boxes=boxes,
        filename=filename,
    )


def _normalize_ref(ref: str) -> str:
    return ref.strip().strip("[]").removeprefix("ref:")


def _find_element(ref: str):
    normalized = _normalize_ref(ref)
    snapshot_obj = state.current_snapshot
    if not snapshot_obj:
        return None
    if isinstance(snapshot_obj, WebSnapshot):
        return snapshot_obj.find_ref(normalized)
    return next((element for element in snapshot_obj.elements if element.ref == normalized), None)


def describe(ref: str) -> str:
    if state.current_snapshot is None:
        return "ERROR: No snapshot available. Run snapshot() first."
    if isinstance(state.current_snapshot, WebSnapshot):
        return state.current_snapshot.describe_ref(ref)
    target = _find_element(ref)
    if not target:
        normalized = _normalize_ref(ref)
        return f"ERROR: ref '{normalized}' not found. Run snapshot() to refresh."

    lines = [
        f"element: {target.to_text()}",
        f"role: {target.role}",
        f"name: {target.name}",
    ]
    if target.value is not None:
        lines.append(f"value: {target.value}")
    lines.append(f"state: {', '.join(target.state) if target.state else 'none'}")
    lines.append(f"bounds: {target.bounds}")

    snapshot_obj = state.current_snapshot
    if target.container_ref:
        container = next((item for item in snapshot_obj.containers if item.ref == target.container_ref), None)
        if container:
            lines.append(f"container: {container.region} ({container.ref})")
            if container.title:
                lines.append(f"container_title: {container.title}")
            siblings = [item for item in snapshot_obj.elements if item.container_ref == target.container_ref and item.ref != target.ref]
            if siblings:
                lines.append("nearby elements:")
                for sibling in siblings[:5]:
                    lines.append(f"  {sibling.to_text()}")
    return "\n".join(lines)


def find_by_text(text: str, scope: str = "full") -> str:
    if state.current_snapshot is None:
        return "ERROR: No snapshot available. Run snapshot() first."

    snapshot_obj = state.current_snapshot
    if isinstance(snapshot_obj, WebSnapshot):
        matches = snapshot_obj.find_text(text, inputs_only=scope == "inputs")
        if not matches:
            return f"No elements matching '{text}' found."
        lines = [f"Search results for '{text}' ({len(matches)} matches):"]
        for match in matches[:10]:
            target_ref = match.target.ref if match.target and match.target.ref else ""
            ref_part = f"[ref:{target_ref}] " if target_ref else ""
            action_part = "" if target_ref == match.node.ref else f" -> action target [ref:{target_ref}]" if target_ref else ""
            lines.append(
                f"  {ref_part}{match.node.role} \"{match.node.name}\" "
                f"(score={match.score}){action_part}"
            )
        return "\n".join(lines)

    search_lower = text.lower()
    candidates: list[dict] = []
    target_elements = snapshot_obj.elements
    if scope == "inputs":
        target_elements = [element for element in snapshot_obj.elements if element.role == "textbox"]
    elif scope not in ("", "full", None):
        allowed_refs = {ref for container in snapshot_obj._filter_containers(scope) for ref in container.children_refs}
        if allowed_refs:
            target_elements = [element for element in snapshot_obj.elements if element.ref in allowed_refs]

    for element in target_elements:
        name_lower = element.name.lower()
        value_lower = (element.value or "").lower()
        if name_lower == search_lower or value_lower == search_lower:
            score = 100
        elif name_lower.startswith(search_lower) or value_lower.startswith(search_lower):
            score = 80
        elif search_lower in name_lower or search_lower in value_lower:
            score = 60
        else:
            continue
        candidates.append({"ref": element.ref, "role": element.role, "name": element.name, "score": score})

    candidates.sort(key=lambda item: item["score"], reverse=True)
    if not candidates:
        return f"No elements matching '{text}' found."
    lines = [f"Search results for '{text}' ({len(candidates)} matches):"]
    for candidate in candidates[:10]:
        lines.append(f"  [ref:{candidate['ref']}] {candidate['role']} \"{candidate['name']}\" (score={candidate['score']})")
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


def get_page_source(context: str = "native") -> str:
    """Return page source: compressed XML for native, raw HTML for web."""
    driver = _require_driver()
    target = resolve_context(context, driver)

    if is_web_context(target):
        with using_context(target, driver, restore=True):
            return driver.page_source or ""
    else:
        with using_context(target, driver, restore=True):
            return compress_xml(driver.page_source)


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
