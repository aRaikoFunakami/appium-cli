"""CLI wrappers for daemon-backed tool commands."""

from __future__ import annotations

import json
from typing import Annotated, Any

import typer

from appium_cli.cli.runtime import get_raw_output
from appium_cli.daemon.client import request
from appium_cli.utils import exit_codes


def _daemon_request(tool: str, json_output: bool, args: dict | None = None) -> None:
    raw_output = get_raw_output()
    try:
        response = request(tool, args=args, raw=raw_output)
    except (FileNotFoundError, ConnectionError, OSError) as exc:
        if json_output and not raw_output:
            typer.echo(json.dumps({"ok": False, "error": "Session daemon is not running", "detail": str(exc)}))
        else:
            typer.echo("ERROR: Session daemon is not running", err=True)
        raise typer.Exit(exit_codes.STOPPED) from exc

    if json_output and not raw_output:
        typer.echo(json.dumps(response, indent=2))
    elif response.get("ok"):
        typer.echo(response.get("text", ""), nl=not str(response.get("text", "")).endswith("\n"))
        data = response.get("data") or {}
        warnings = data.get("warnings") if isinstance(data, dict) else None
        if isinstance(warnings, list):
            for warn in warnings:
                typer.echo(f"[warning] {warn}", err=True)
    else:
        typer.echo(f"ERROR: {response.get('error', 'tool failed')}", err=True)

    if not response.get("ok"):
        raise typer.Exit(response.get("exit_code", exit_codes.GENERAL_ERROR))


def get_device_info(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Wrap the smartestiroid-compatible result in JSON."),
    ] = False,
) -> None:
    """Get model, Android version, display, battery/session info, and foreground app."""

    _daemon_request("get_device_info", json_output)


def snapshot(
    target: Annotated[str, typer.Argument(help="Element ref to scope the snapshot around.")] = "",
    scope: Annotated[str, typer.Option("--scope", help="Snapshot scope.")] = "full",
    context: Annotated[str, typer.Option("--context", help="Context: native, webview, auto, current, or exact name.")] = "native",
    depth: Annotated[int | None, typer.Option("--depth", help="Limit web snapshot tree to N levels.")] = None,
    max_nodes: Annotated[int | None, typer.Option("--max-nodes", help="Limit snapshot tree to N nodes (applies to both native and web).")] = None,
    boxes: Annotated[bool, typer.Option("--boxes", help="Include element bounding boxes in output (native and web).")] = False,
    filename: Annotated[str, typer.Option("--filename", help="Save snapshot to file.")] = "",
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Get an accessibility snapshot with refs."""

    args: dict[str, Any] = {"scope": scope, "context": context}
    if target:
        args["target"] = target
    if depth is not None:
        args["depth"] = depth
    if max_nodes is not None:
        args["max_nodes"] = max_nodes
    if boxes:
        args["boxes"] = boxes
    if filename:
        args["filename"] = filename
    _daemon_request("snapshot", json_output, args)


def snapshot_show(
    snapshot_id: Annotated[str, typer.Argument(help="Snapshot id or 'latest'.")] = "latest",
    artifact: Annotated[str, typer.Option("--artifact", help="Artifact: compact, full, refs, index, or meta.")] = "compact",
    ref: Annotated[str, typer.Option("--ref", help="Show detail for one ref from the snapshot.")] = "",
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Show a persisted snapshot artifact without refreshing device state."""

    _daemon_request(
        "snapshot_show",
        json_output,
        {"snapshot_id": snapshot_id, "artifact": artifact, "ref": ref},
    )


def snapshot_search(
    text: Annotated[str, typer.Argument(help="Text to search in the latest snapshot artifacts.")],
    snapshot_id: Annotated[str, typer.Option("--snapshot", help="Snapshot id or 'latest'.")] = "latest",
    role: Annotated[str, typer.Option("--role", help="Filter results by role.")] = "",
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Search persisted snapshot index/ref artifacts without refreshing device state."""

    _daemon_request(
        "snapshot_search",
        json_output,
        {"text": text, "snapshot_id": snapshot_id, "role": role},
    )


def snapshot_refs(
    snapshot_id: Annotated[str, typer.Argument(help="Snapshot id or 'latest'.")] = "latest",
    ref: Annotated[str, typer.Argument(help="Optional ref to show in detail.")] = "",
    role: Annotated[str, typer.Option("--role", help="Filter listed refs by role.")] = "",
    limit: Annotated[int, typer.Option("--limit", help="Maximum refs to list per page.")] = 50,
    offset: Annotated[int, typer.Option("--offset", help="Zero-based offset for paginated ref listings.")] = 0,
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """List refs or show a single ref from a persisted snapshot artifact."""

    _daemon_request(
        "snapshot_refs",
        json_output,
        {"snapshot_id": snapshot_id, "ref": ref, "role": role, "limit": limit, "offset": offset},
    )


def generate_locator(
    ref: Annotated[str, typer.Argument(help="Element ref to generate a locator for.")],
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Generate the best stored durable locator for a ref."""

    _daemon_request("generate_locator", json_output, {"ref": ref})


def web_form_url(
    target: Annotated[str, typer.Argument(help="CSS selector or web_* ref pointing to a form or an element inside one.")],
    max_fields: Annotated[int, typer.Option("--max-fields", help="Maximum number of form fields to inspect.")] = 50,
    max_value_length: Annotated[int, typer.Option("--max-value-length", help="Truncate each field value to this many characters.")] = 200,
    names_only: Annotated[bool, typer.Option("--names-only", help="Emit field names only; omit values and URL.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Inspect a form's submit target without interacting with the page (read-only, redacts secrets)."""
    _daemon_request(
        "web_form_url",
        json_output,
        {
            "target": target,
            "max_fields": max_fields,
            "max_value_length": max_value_length,
            "names_only": names_only,
        },
    )


def web_query(
    selector: Annotated[str, typer.Argument(help="CSS selector to query in the current WebView/Chrome DOM.")],
    attrs: Annotated[str, typer.Option("--attrs", help="Comma-separated extra attributes to include.")] = "",
    limit: Annotated[int, typer.Option("--limit", help="Maximum number of matches to return.")] = 20,
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Query the current WebView/Chrome DOM by CSS selector."""

    _daemon_request("web_query", json_output, {"selector": selector, "attrs": attrs, "limit": limit})


def describe(
    ref: Annotated[str, typer.Argument(help="Element ref to describe.")],
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Describe a ref from the latest snapshot."""

    _daemon_request("describe", json_output, {"ref": ref})


def find_by_text(
    text: Annotated[str, typer.Argument(help="Text to search for.")],
    scope: Annotated[str, typer.Option("--scope", help="Search scope.")] = "full",
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Find elements by visible text."""

    _daemon_request("find_by_text", json_output, {"text": text, "scope": scope})


def screenshot(
    region: Annotated[str, typer.Option("--region", help="full or ref:<ref>.")] = "full",
    filename: Annotated[str, typer.Option("--filename", help="Save screenshot to file.")] = "",
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Take a screenshot and return the smartestiroid-compatible JSON string."""

    args: dict[str, Any] = {"region": region}
    if filename:
        args["filename"] = filename
    _daemon_request("screenshot", json_output, args)


def get_page_source(
    context: Annotated[str, typer.Option("--context", help="Context: native, webview, or exact name.")] = "native",
    raw: Annotated[bool, typer.Option("--raw", help="Return uncompressed native XML. Web page source is always raw.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Return page source: compressed XML for native, raw HTML for web."""

    _daemon_request("get_page_source", json_output, {"context": context, "raw": raw})


def tap(ref: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("tap", json_output, {"ref": ref})


def click(ref: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Web-friendly alias for tap."""
    _daemon_request("click", json_output, {"ref": ref})


def type_text(ref: str, text: str, submit: Annotated[bool, typer.Option("--submit")] = False, slowly: Annotated[bool, typer.Option("--slowly")] = False, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("type_text", json_output, {"ref": ref, "text": text, "submit": submit, "slowly": slowly})


def fill(ref: str, text: str, submit: Annotated[bool, typer.Option("--submit")] = False, slowly: Annotated[bool, typer.Option("--slowly")] = False, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Web-friendly alias for type_text."""
    _daemon_request("fill", json_output, {"ref": ref, "text": text, "submit": submit, "slowly": slowly})


def select(
    ref: Annotated[str, typer.Argument(help="Ref of the <select> element.")],
    value: Annotated[str, typer.Argument(help="Option value, label, or index.")],
    by: Annotated[str, typer.Option("--by", help="Selection method: value, label, or index.")] = "value",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Select an option in an HTML <select> element."""
    _daemon_request("select", json_output, {"ref": ref, "value": value, "by": by})


def select_option(
    ref: Annotated[str, typer.Argument(help="Ref or CSS selector of the dropdown trigger/input.")],
    text: Annotated[str, typer.Argument(help="Visible text of the option to select.")],
    timeout: Annotated[float, typer.Option("--timeout", help="Max seconds to wait for options.")] = 3.0,
    exact: Annotated[bool, typer.Option("--exact/--no-exact", help="Require exact text match.")] = True,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Select an option from a dropdown (custom or native) by visible text."""
    _daemon_request("select_option", json_output, {"ref": ref, "text": text, "timeout": timeout, "exact": exact})


def set_date(
    ref: Annotated[str, typer.Argument(help="Ref or CSS selector of the date input.")],
    date: Annotated[str, typer.Argument(help="Date string: '15 May 1990', '1990-05-15', '05/15/1990'.")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Set a date value on an input element."""
    _daemon_request("set_date", json_output, {"ref": ref, "date": date})


def file_upload(
    ref: Annotated[str, typer.Argument(help="Ref or CSS selector of the file input.")],
    path: Annotated[str, typer.Argument(help="Local file path or device path.")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Upload a file to an <input type='file'> element."""
    _daemon_request("file_upload", json_output, {"ref": ref, "path": path})


def wait_for(
    text: Annotated[str, typer.Option("--text", help="Text to wait for (appear).")] = "",
    gone: Annotated[str, typer.Option("--gone", help="Text to wait for (disappear).")] = "",
    ref: Annotated[str, typer.Option("--ref", help="Ref of element to wait for visibility.")] = "",
    timeout: Annotated[float, typer.Option("--timeout", help="Timeout in seconds.")] = 15.0,
    poll: Annotated[float, typer.Option("--poll", help="Poll interval in seconds.")] = 0.5,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Wait for text to appear/disappear or element to become visible."""
    _daemon_request("wait_for", json_output, {"text": text, "gone": gone, "ref": ref, "timeout": timeout, "poll": poll})


def console_messages(
    level: Annotated[str, typer.Option("--level", help="Log level: all, error, warning, info, debug.")] = "all",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Read browser console messages from WebView/Chrome."""
    _daemon_request("console_messages", json_output, {"level": level})


def tabs_cmd(
    action: Annotated[str, typer.Argument(help="Tab action: list, switch, close, new.")],
    index: Annotated[int | None, typer.Option("--index", help="Tab index for switch/close.")] = None,
    url: Annotated[str, typer.Option("--url", help="URL for new tab.")] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Manage WebView tabs/windows."""
    args: dict = {"action": action}
    if index is not None:
        args["index"] = index
    if url:
        args["url"] = url
    _daemon_request("tabs", json_output, args)


def network_requests_cmd(
    filter: Annotated[str, typer.Option("--filter", help="URL regexp filter.")] = "",
    static: Annotated[bool, typer.Option("--static/--no-static", help="Include static resources.")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List captured network requests (requires --enable-network-log on session start)."""
    _daemon_request("network_requests", json_output, {"filter": filter, "static": static})


def scroll(direction: str, ref: Annotated[str, typer.Option("--ref")] = "", percent: Annotated[float, typer.Option("--percent")] = 0.8, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("scroll", json_output, {"direction": direction, "ref": ref, "percent": percent})


def scroll_up(ref: Annotated[str, typer.Argument()] = "", percent: Annotated[float, typer.Option("--percent")] = 0.8, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("scroll", json_output, {"direction": "up", "ref": ref, "percent": percent})


def scroll_down(ref: Annotated[str, typer.Argument()] = "", percent: Annotated[float, typer.Option("--percent")] = 0.8, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("scroll", json_output, {"direction": "down", "ref": ref, "percent": percent})


def scroll_left(ref: Annotated[str, typer.Argument()] = "", percent: Annotated[float, typer.Option("--percent")] = 0.8, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("scroll", json_output, {"direction": "left", "ref": ref, "percent": percent})


def scroll_right(ref: Annotated[str, typer.Argument()] = "", percent: Annotated[float, typer.Option("--percent")] = 0.8, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("scroll", json_output, {"direction": "right", "ref": ref, "percent": percent})


def swipe(direction: str, ref: Annotated[str, typer.Option("--ref")] = "", percent: Annotated[float, typer.Option("--percent")] = 0.8, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("swipe", json_output, {"direction": direction, "ref": ref, "percent": percent})


def swipe_up(ref: Annotated[str, typer.Argument()] = "", percent: Annotated[float, typer.Option("--percent")] = 0.8, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("swipe", json_output, {"direction": "up", "ref": ref, "percent": percent})


def swipe_down(ref: Annotated[str, typer.Argument()] = "", percent: Annotated[float, typer.Option("--percent")] = 0.8, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("swipe", json_output, {"direction": "down", "ref": ref, "percent": percent})


def swipe_left(ref: Annotated[str, typer.Argument()] = "", percent: Annotated[float, typer.Option("--percent")] = 0.8, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("swipe", json_output, {"direction": "left", "ref": ref, "percent": percent})


def swipe_right(ref: Annotated[str, typer.Argument()] = "", percent: Annotated[float, typer.Option("--percent")] = 0.8, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("swipe", json_output, {"direction": "right", "ref": ref, "percent": percent})


def press_key(key: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("press_key", json_output, {"key": key})


def wait(seconds: Annotated[float, typer.Argument()] = 1.0, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("wait", json_output, {"seconds": seconds})


def long_press(ref: str, duration: Annotated[int, typer.Option("--duration")] = 500, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("long_press", json_output, {"ref": ref, "duration": duration})


def double_tap(ref: Annotated[str, typer.Argument()] = "", by: Annotated[str, typer.Option("--by")] = "", value: Annotated[str, typer.Option("--value")] = "", json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    if by or value:
        _daemon_request("double_tap", json_output, {"by": by, "value": value})
    else:
        _daemon_request("double_tap", json_output, {"ref": ref})


def drag(ref: str, end_x: int, end_y: int, speed: Annotated[int | None, typer.Option("--speed")] = None, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("drag", json_output, {"ref": ref, "end_x": end_x, "end_y": end_y, "speed": speed})


def fling(direction: str, ref: Annotated[str, typer.Option("--ref")] = "", speed: Annotated[int | None, typer.Option("--speed")] = None, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("fling", json_output, {"direction": direction, "ref": ref, "speed": speed})


def fling_up(ref: Annotated[str, typer.Argument()] = "", speed: Annotated[int | None, typer.Option("--speed")] = None, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("fling", json_output, {"direction": "up", "ref": ref, "speed": speed})


def fling_down(ref: Annotated[str, typer.Argument()] = "", speed: Annotated[int | None, typer.Option("--speed")] = None, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("fling", json_output, {"direction": "down", "ref": ref, "speed": speed})


def fling_left(ref: Annotated[str, typer.Argument()] = "", speed: Annotated[int | None, typer.Option("--speed")] = None, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("fling", json_output, {"direction": "left", "ref": ref, "speed": speed})


def fling_right(ref: Annotated[str, typer.Argument()] = "", speed: Annotated[int | None, typer.Option("--speed")] = None, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("fling", json_output, {"direction": "right", "ref": ref, "speed": speed})


def pinch_open(ref: str, percent: Annotated[float, typer.Option("--percent")] = 0.5, speed: Annotated[int | None, typer.Option("--speed")] = None, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("pinch_open", json_output, {"ref": ref, "percent": percent, "speed": speed})


def pinch_close(ref: str, percent: Annotated[float, typer.Option("--percent")] = 0.5, speed: Annotated[int | None, typer.Option("--speed")] = None, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("pinch_close", json_output, {"ref": ref, "percent": percent, "speed": speed})


def list_containers(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("list_containers", json_output)


def find_container(text: str, role_hint: Annotated[str, typer.Option("--role-hint")] = "", json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("find_container", json_output, {"text": text, "role_hint": role_hint})


def within_container(container_ref: str, role: Annotated[str, typer.Option("--role")] = "", position: Annotated[str, typer.Option("--position")] = "first", json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("within_container", json_output, {"container_ref": container_ref, "role": role, "position": position})


def assert_visible(text: Annotated[str, typer.Option("--text")] = "", ref: Annotated[str, typer.Option("--ref")] = "", json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("assert_visible", json_output, {"text": text, "ref": ref})


def get_current_app(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("get_current_app", json_output)


def activate_app(app_id: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("activate_app", json_output, {"app_id": app_id})


def terminate_app(app_id: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("terminate_app", json_output, {"app_id": app_id})


def list_apps(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("list_apps", json_output)


def restart_app(app_id: str, wait_seconds: Annotated[int, typer.Option("--wait-seconds")] = 3, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("restart_app", json_output, {"app_id": app_id, "wait_seconds": wait_seconds})


def is_locked(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("is_locked", json_output)


def get_orientation(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("get_orientation", json_output)


def set_orientation(orientation: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("set_orientation", json_output, {"orientation": orientation})


def find_element(by: str, value: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("find_element", json_output, {"by": by, "value": value})


def click_element(by: str, value: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("click_element", json_output, {"by": by, "value": value})


def get_text(by: str, value: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("get_text", json_output, {"by": by, "value": value})


def press_keycode(keycode: int, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("press_keycode", json_output, {"keycode": keycode})


def send_keys(by: str, value: str, text: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("send_keys", json_output, {"by": by, "value": value, "text": text})


def wait_short_loading(seconds: Annotated[str, typer.Argument()] = "5", json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("wait_short_loading", json_output, {"seconds": seconds})


def scroll_element(by: str, value: str, direction: Annotated[str, typer.Option("--direction")] = "up", json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("scroll_element", json_output, {"by": by, "value": value, "direction": direction})


def scroll_to_element(by: str, value: str, scrollable_by: Annotated[str, typer.Option("--scrollable-by")] = "xpath", scrollable_value: Annotated[str, typer.Option("--scrollable-value")] = "//*[@scrollable='true']", json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("scroll_to_element", json_output, {"by": by, "value": value, "scrollable_by": scrollable_by, "scrollable_value": scrollable_value})


# ============================================================
# Context commands
# ============================================================


def list_contexts(
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Show available Appium contexts (NATIVE_APP, WEBVIEW_*, CHROMIUM)."""
    _daemon_request("list_contexts", json_output)


def get_context(
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Return the current Appium context name."""
    _daemon_request("get_context", json_output)


def switch_context(
    context: Annotated[str, typer.Argument(help="Context selector: native, webview, auto, current, or exact name.")],
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Switch to an Appium context."""
    _daemon_request("switch_context", json_output, {"context": context})


def native_switch(
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Switch to NATIVE_APP context."""
    _daemon_request("native_switch", json_output)


def webview_switch(
    context: Annotated[str, typer.Argument(help="WebView context name (optional).")] = "",
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Switch to a WebView/CHROMIUM context."""
    _daemon_request("webview_switch", json_output, {"context": context})


def webview_status(
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Show WebView availability, URL/title, and prerequisites."""
    _daemon_request("webview_status", json_output)


def web_snapshot(
    target: Annotated[str, typer.Argument(help="Element ref to scope the WebView snapshot around.")] = "",
    scope: Annotated[str, typer.Option("--scope", help="Snapshot scope.")] = "full",
    depth: Annotated[int | None, typer.Option("--depth", help="Limit tree to N levels.")] = None,
    max_nodes: Annotated[int | None, typer.Option("--max-nodes", help="Limit web snapshot tree to N nodes.")] = None,
    boxes: Annotated[bool, typer.Option("--boxes", help="Include element bounding boxes in web snapshot.")] = False,
    filename: Annotated[str, typer.Option("--filename", help="Save snapshot to file.")] = "",
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Take a WebView DOM snapshot (alias for snapshot --context=webview)."""
    args: dict[str, Any] = {"scope": scope}
    if target:
        args["target"] = target
    if depth is not None:
        args["depth"] = depth
    if max_nodes is not None:
        args["max_nodes"] = max_nodes
    if boxes:
        args["boxes"] = boxes
    if filename:
        args["filename"] = filename
    _daemon_request("web_snapshot", json_output, args)


def webview_url(
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Return the current WebView URL."""
    _daemon_request("webview_url", json_output)


def webview_title(
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Return the current WebView page title."""
    _daemon_request("webview_title", json_output)


# ============================================================
# Web navigation commands
# ============================================================


def goto(
    url: Annotated[str, typer.Argument(help="URL to navigate to.")],
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Navigate WebView to a URL."""
    _daemon_request("goto", json_output, {"url": url})


def go_back(
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Go back in WebView history."""
    _daemon_request("go_back", json_output)


def go_forward(
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Go forward in WebView history."""
    _daemon_request("go_forward", json_output)


def reload_page(
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Reload the current WebView page."""
    _daemon_request("reload", json_output)


def web_eval(
    script: Annotated[str, typer.Argument(help="JavaScript code to execute.")],
    ref: Annotated[str, typer.Option("--ref", help="Optional ref to pass as argument.")] = "",
    no_lint: Annotated[bool, typer.Option("--no-lint", help="Disable runtime warnings about navigation/value-injection patterns.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Evaluate JavaScript in WebView context."""
    _daemon_request("web_eval", json_output, {"script": script, "ref": ref, "no_lint": no_lint})


# ============================================================
# Dialog commands
# ============================================================


def dialog_accept(
    prompt_text: Annotated[str, typer.Argument(help="Text for prompt dialog (optional).")] = "",
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Accept the current alert/confirm/prompt dialog."""
    _daemon_request("dialog_accept", json_output, {"prompt_text": prompt_text})


def dialog_dismiss(
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Dismiss the current alert/confirm/prompt dialog."""
    _daemon_request("dialog_dismiss", json_output)


def dialog_text(
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Read the text of the current alert/confirm/prompt dialog."""
    _daemon_request("dialog_text", json_output)
