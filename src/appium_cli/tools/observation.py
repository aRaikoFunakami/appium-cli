"""Observation tools."""

from __future__ import annotations

import json
import logging
from typing import Any

from appium_cli.core.native_snapshot import NativeSnapshot
from appium_cli.core.native_snapshot_generator import NativeSnapshotGenerator
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
_native_snapshot_generator = NativeSnapshotGenerator()


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
) -> str:
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
    return snapshot_obj.to_text(scope=scope if scope != "full" else None, boxes=boxes)


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
            result = _refresh_native_snapshot(driver, scope, max_nodes=max_nodes, boxes=boxes)

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
    return snapshot_obj.find_ref(normalized)


def describe(ref: str) -> str:
    if state.current_snapshot is None:
        return "ERROR: No snapshot available. Run snapshot() first."
    return state.current_snapshot.describe_ref(ref)


def find_by_text(text: str, scope: str = "full") -> str:
    if state.current_snapshot is None:
        return "ERROR: No snapshot available. Run snapshot() first."
    snapshot_obj = state.current_snapshot
    inputs_only = scope == "inputs"
    matches = snapshot_obj.find_text(text, inputs_only=inputs_only)
    if not matches:
        return f"No elements matching '{text}' found."
    lines = [f"Search results for '{text}' ({len(matches)} matches):"]
    for match in matches[:10]:
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
