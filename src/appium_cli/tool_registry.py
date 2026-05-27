"""Shared tool registry for daemon-backed Appium tool commands.

This registry is the single source of truth for:
- Canonical tool names exposed to OpenAI and CLI
- Daemon tool routing names
- JSON Schema parameters for each tool
- Directional alias argument transforms

It does NOT depend on OpenAI SDK or any external LLM library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolDef:
    """Metadata for a single tool."""

    name: str
    description: str
    daemon_tool: str
    parameters: dict[str, Any] = field(default_factory=dict)
    inject_args: dict[str, Any] = field(default_factory=dict)


# JSON Schema helpers

def _str_param(description: str, default: str | None = None, enum: list[str] | None = None) -> dict[str, Any]:
    p: dict[str, Any] = {"type": "string", "description": description}
    if default is not None:
        p["default"] = default
    if enum is not None:
        p["enum"] = enum
    return p


def _int_param(description: str, default: int | None = None) -> dict[str, Any]:
    p: dict[str, Any] = {"type": "integer", "description": description}
    if default is not None:
        p["default"] = default
    return p


def _float_param(description: str, default: float | None = None) -> dict[str, Any]:
    p: dict[str, Any] = {"type": "number", "description": description}
    if default is not None:
        p["default"] = default
    return p


def _bool_param(description: str, default: bool = False) -> dict[str, Any]:
    return {"type": "boolean", "description": description, "default": default}


def _str_array_param(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    s: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        s["required"] = required
    return s


# --- Tool definitions ---

_TOOLS: list[ToolDef] = []


def _add(name: str, description: str, daemon_tool: str | None = None,
         parameters: dict[str, Any] | None = None, inject_args: dict[str, Any] | None = None) -> None:
    _TOOLS.append(ToolDef(
        name=name,
        description=description,
        daemon_tool=daemon_tool or name,
        parameters=parameters or _schema({}),
        inject_args=inject_args or {},
    ))


# ============================================================
# Observation
# ============================================================

_add("snapshot", "Get an accessibility snapshot with stable element refs. Returns metadata and artifact paths, not the full tree; use snapshot_search, snapshot_refs, or snapshot_show(ref=...) to inspect it.",
     parameters=_schema({
         "scope": _str_param("Snapshot scope filter.", default="full"),
         "context": _str_param("Context: native, webview, auto, current, or exact name.", default="native",
                               enum=["native", "webview", "auto", "current"]),
         "depth": _int_param("Limit the depth of the snapshot tree."),
         "boxes": _bool_param("Include element bounding boxes in output."),
         "filename": _str_param("Save snapshot to file."),
     }))

_add("web_snapshot", "Take a WebView DOM snapshot (alias for snapshot --context=webview). Returns metadata and artifact paths, not the full tree. Use snapshot_search/snapshot_refs for navigation targets, web_text for page/article text, or snapshot_show(ref=...) for one element.",
     parameters=_schema({
         "scope": _str_param("Snapshot scope filter.", default="full"),
         "depth": _int_param("Limit the depth of the snapshot tree."),
         "boxes": _bool_param("Include element bounding boxes."),
         "filename": _str_param("Save snapshot to file."),
     }))

_add("snapshot_show",
     "Show a persisted snapshot artifact. "
     "PREFER snapshot_search(text=...) or snapshot_refs(role=...) for finding elements - "
     "they return compact targeted results. "
     "Use snapshot_show only with ref=<specific_ref> for one element's detail. "
     "artifact=compact returns the FULL tree (large) and wastes tokens in agent loops.",
     parameters=_schema({
         "snapshot_id": _str_param("Snapshot id or latest.", default="latest"),
         "artifact": _str_param("Artifact to show.", default="compact",
                                enum=["compact", "full", "refs", "index", "meta"]),
         "ref": _str_param("Optional ref to show in detail."),
     }))

_add("snapshot_search",
     "Search persisted snapshot for elements by text. Fast, compact output. "
     "Use this instead of snapshot_show(artifact=compact) to find elements.",
     parameters=_schema({
         "text": _str_param("Text to search for."),
         "snapshot_id": _str_param("Snapshot id or latest.", default="latest"),
         "role": _str_param("Optional role filter."),
         "any_text": _str_array_param("Additional text variants to match (OR). Literal, case-insensitive. No regex."),
     }, required=["text"]))

_add("snapshot_refs",
     "List actionable refs from the latest snapshot with pagination. Fast, compact output. "
     "Defaults to limit=50; use next_offset when has_more=true. "
     "Use this to discover available refs instead of reading the full tree. "
     "Not the right tool for launching apps: launcher app icons are often text-only "
     "and will not appear here. To start a known app, use activate_app <package> instead.",
     parameters=_schema({
         "snapshot_id": _str_param("Snapshot id or latest.", default="latest"),
         "ref": _str_param("Optional ref to show in detail."),
         "role": _str_param("Optional role filter for listing refs."),
         "limit": _int_param("Maximum refs to list per page.", default=50),
         "offset": _int_param("Zero-based offset for paginated listings.", default=0),
      }))

_add("generate_locator", "Generate the best stored durable locator for a ref.",
     parameters=_schema({
         "ref": _str_param("Element ref to generate a locator for."),
     }, required=["ref"]))

_add("web_query", "Query the current WebView/Chrome DOM by CSS selector.",
     parameters=_schema({
         "selector": _str_param("CSS selector to query."),
         "attrs": _str_param("Comma-separated extra attributes to include."),
         "limit": _int_param("Maximum number of matches to return.", default=20),
     }, required=["selector"]))

_add("web_text",
     "Extract readable page text from the current WebView/Chrome DOM. Use this for article/body/page content to summarize; use web_snapshot/snapshot_refs for clickable refs.",
     parameters=_schema({
         "selector": _str_param("Optional CSS selector. Empty auto-selects article, main, [role=main], then body.", default=""),
         "offset": _int_param("Character offset for continuation.", default=0),
         "limit": _int_param("Maximum characters to return.", default=6000),
     }))

_add("web_form_url",
     "Inspect an HTML form and report its submit URL/payload without interacting (read-only; redacts secrets). "
     "Use for information retrieval/debugging; not a substitute for real frontend interaction.",
     parameters=_schema({
         "target": _str_param("CSS selector or web_* ref pointing to a form or element inside one."),
         "max_fields": _int_param("Maximum number of form fields to inspect.", default=50),
         "max_value_length": _int_param("Truncate each field value to this many characters.", default=200),
         "names_only": _bool_param("Emit field names only; omit values and URL.", default=False),
     }, required=["target"]))

_add("describe", "Describe an element ref from the latest snapshot.",
     parameters=_schema({"ref": _str_param("Element ref to describe.")}, required=["ref"]))

_add("find_by_text", "Find elements by visible text.",
     parameters=_schema({
         "text": _str_param("Text to search for."),
         "scope": _str_param("Search scope.", default="full"),
         "any_text": _str_array_param("Additional text variants to match (OR). Literal, case-insensitive. No regex."),
     }, required=["text"]))

_add("screenshot", "Take a screenshot and return base64 JSON.",
     parameters=_schema({
         "region": _str_param("full or ref:<ref>.", default="full"),
         "filename": _str_param("Save screenshot to file."),
     }))

_add("get_page_source", "Return page source: compressed XML for native, raw HTML for web.",
     parameters=_schema({
         "context": _str_param("Context: native, webview, or exact name.", default="native"),
         "raw": _bool_param("Return uncompressed native XML. Web page source is always raw."),
      }))

_add("webview_url", "Return the current WebView URL.")
_add("webview_title", "Return the current WebView page title.")

# ============================================================
# Actions
# ============================================================

_add("tap", "Tap on an element by ref.",
     parameters=_schema({"ref": _str_param("Element ref to tap.")}, required=["ref"]))

_add("click", "Web-friendly alias for tap.",
     parameters=_schema({"ref": _str_param("Element ref to click.")}, required=["ref"]))

_add("type_text", "Type text into an element.",
     parameters=_schema({
         "ref": _str_param("Element ref of the input field."),
         "text": _str_param("Text to type."),
         "submit": _bool_param("Submit after typing."),
         "slowly": _bool_param("Type one character at a time for autocomplete/React-Select inputs."),
     }, required=["ref", "text"]))

_add("fill", "Web-friendly alias for type_text.",
     parameters=_schema({
         "ref": _str_param("Element ref of the input field."),
         "text": _str_param("Text to type."),
         "submit": _bool_param("Submit after typing."),
         "slowly": _bool_param("Type one character at a time for autocomplete/React-Select inputs."),
     }, required=["ref", "text"]))

_add("select", "Select an option in an HTML <select> element.",
     parameters=_schema({
         "ref": _str_param("Ref of the <select> element."),
         "value": _str_param("Option value, label, or index."),
         "by": _str_param("Selection method: value, label, or index.", default="value",
                          enum=["value", "label", "index"]),
     }, required=["ref", "value"]))

_add("select_option", "Select an option from a dropdown (custom or native) by visible text.",
     parameters=_schema({
         "ref": _str_param("Ref or CSS selector of the dropdown trigger/input."),
         "text": _str_param("Visible text of the option to select."),
         "timeout": _float_param("Max seconds to wait for options to appear.", default=3.0),
         "exact": _bool_param("Require exact text match (default true). Set false for partial match."),
     }, required=["ref", "text"]))

_add("set_date", "Set a date value on an input element (react-datepicker, native date, etc.).",
     parameters=_schema({
         "ref": _str_param("Ref or CSS selector of the date input."),
         "date": _str_param("Date string: '15 May 1990', '1990-05-15', or '05/15/1990'."),
     }, required=["ref", "date"]))

_add("file_upload", "Upload a file to an <input type='file'> element.",
     parameters=_schema({
         "ref": _str_param("Ref or CSS selector of the file input."),
         "path": _str_param("Local file path or device path (e.g. /sdcard/Download/photo.jpg)."),
     }, required=["ref", "path"]))

_add("wait_for", "Wait for text to appear/disappear or element to become visible.",
     parameters=_schema({
         "text": _str_param("Text to wait for (appear)."),
         "gone": _str_param("Text to wait for (disappear)."),
         "ref": _str_param("Ref of element to wait for visibility."),
         "timeout": _float_param("Timeout in seconds.", default=15.0),
         "poll": _float_param("Poll interval in seconds.", default=0.5),
     }))

_add("console_messages", "Read browser console messages from WebView/Chrome.",
     parameters=_schema({
         "level": _str_param("Log level filter: all, error, warning, info, debug.", default="all",
                             enum=["all", "error", "warning", "info", "debug"]),
     }))

_add("tabs", "Manage WebView tabs/windows: list, switch, close, new.",
     parameters=_schema({
         "action": _str_param("Tab action.", enum=["list", "switch", "close", "new"]),
         "index": {"type": "integer", "description": "Tab index for switch/close."},
         "url": _str_param("URL for new tab."),
     }, required=["action"]))

_add("network_requests", "List captured network requests (requires --enable-network-log on session start).",
     parameters=_schema({
         "filter": _str_param("URL regexp filter."),
         "static": {"type": "boolean", "description": "Include static resources (images, fonts, etc.).", "default": False},
     }))

_add("scroll", "Scroll in a direction.",
     parameters=_schema({
         "direction": _str_param("Scroll direction.", enum=["up", "down", "left", "right"]),
         "ref": _str_param("Optional container ref to scroll within."),
         "percent": _float_param("Scroll distance as fraction of viewport.", default=0.8),
     }, required=["direction"]))

# Directional scroll aliases
for _dir in ("up", "down", "left", "right"):
    _add(f"scroll_{_dir}", f"Scroll {_dir}.",
         daemon_tool="scroll",
         parameters=_schema({
             "ref": _str_param("Optional container ref to scroll within."),
             "percent": _float_param("Scroll distance as fraction of viewport.", default=0.8),
         }),
         inject_args={"direction": _dir})

_add("swipe", "Swipe in a direction (native only).",
     parameters=_schema({
         "direction": _str_param("Swipe direction.", enum=["up", "down", "left", "right"]),
         "ref": _str_param("Optional element ref."),
         "percent": _float_param("Swipe distance as fraction.", default=0.8),
     }, required=["direction"]))

# Directional swipe aliases
for _dir in ("up", "down", "left", "right"):
    _add(f"swipe_{_dir}", f"Swipe {_dir} (native only).",
         daemon_tool="swipe",
         parameters=_schema({
             "ref": _str_param("Optional element ref."),
             "percent": _float_param("Swipe distance as fraction.", default=0.8),
         }),
         inject_args={"direction": _dir})

_add("press_key", "Press a key (back, home, enter, delete, tab).",
     parameters=_schema({"key": _str_param("Key name.", enum=["back", "home", "enter", "delete", "tab"])},
                        required=["key"]))

_add("wait", "Wait for N seconds.",
     parameters=_schema({"seconds": _float_param("Seconds to wait.", default=1.0)}))

_add("long_press", "Long press on an element.",
     parameters=_schema({
         "ref": _str_param("Element ref."),
         "duration": _int_param("Duration in milliseconds.", default=500),
     }, required=["ref"]))

_add("double_tap", "Double tap on an element by ref.",
     parameters=_schema({"ref": _str_param("Element ref to double-tap.")}, required=["ref"]))

_add("drag", "Drag an element to coordinates.",
     parameters=_schema({
         "ref": _str_param("Element ref to drag."),
         "end_x": _int_param("Target X coordinate."),
         "end_y": _int_param("Target Y coordinate."),
         "speed": _int_param("Drag speed in pixels/sec."),
     }, required=["ref", "end_x", "end_y"]))

_add("fling", "Fling in a direction (native only).",
     parameters=_schema({
         "direction": _str_param("Fling direction.", enum=["up", "down", "left", "right"]),
         "ref": _str_param("Optional container ref."),
         "speed": _int_param("Fling speed in pixels/sec."),
     }, required=["direction"]))

# Directional fling aliases
for _dir in ("up", "down", "left", "right"):
    _add(f"fling_{_dir}", f"Fling {_dir} (native only).",
         daemon_tool="fling",
         parameters=_schema({
             "ref": _str_param("Optional container ref."),
             "speed": _int_param("Fling speed in pixels/sec."),
         }),
         inject_args={"direction": _dir})

_add("pinch_open", "Pinch open gesture on an element.",
     parameters=_schema({
         "ref": _str_param("Element ref."),
         "percent": _float_param("Pinch distance as fraction.", default=0.5),
         "speed": _int_param("Pinch speed."),
     }, required=["ref"]))

_add("pinch_close", "Pinch close gesture on an element.",
     parameters=_schema({
         "ref": _str_param("Element ref."),
         "percent": _float_param("Pinch distance as fraction.", default=0.5),
         "speed": _int_param("Pinch speed."),
     }, required=["ref"]))

_add("web_eval", "Evaluate JavaScript in the current WebView (Playwright browser_evaluate equivalent). Use for read-only DOM extraction: collect links, article URLs, headings, structured text, or page metadata. Returns JSON when the script returns an array/object. Prefer goto/click/fill for navigation and interaction; do not mutate form values or navigate.",
     parameters=_schema({
         "script": _str_param("JavaScript code to execute."),
         "ref": _str_param("Optional ref to pass as argument."),
         "no_lint": _bool_param("Disable runtime warnings about navigation/value-injection patterns.", default=False),
     }, required=["script"]))

# ============================================================
# Containers
# ============================================================

_add("list_containers", "List scrollable containers on screen.")

_add("find_container", "Find a container by text content.",
     parameters=_schema({
         "text": _str_param("Text to search for in container children."),
         "role_hint": _str_param("Filter by container kind."),
     }, required=["text"]))

_add("within_container", "Get elements within a container.",
     parameters=_schema({
         "container_ref": _str_param("Ref of the container."),
         "role": _str_param("Filter by element role."),
         "position": _str_param("Position selector: first, last, right_most, left_most.", default="first"),
     }, required=["container_ref"]))

# ============================================================
# App management
# ============================================================

_add("get_current_app", "Get current app package and activity.")

_add("activate_app", "Activate (bring to foreground) an app.",
     parameters=_schema({"app_id": _str_param("App package ID.")}, required=["app_id"]))

_add("terminate_app", "Terminate an app.",
     parameters=_schema({"app_id": _str_param("App package ID.")}, required=["app_id"]))

_add("list_apps", "List installed apps on device.")

_add("restart_app", "Restart an app (terminate + activate).",
     parameters=_schema({
         "app_id": _str_param("App package ID."),
         "wait_seconds": _int_param("Seconds to wait between terminate and activate.", default=3),
     }, required=["app_id"]))

# ============================================================
# Device info
# ============================================================

_add("get_device_info", "Get comprehensive device information (model, brand, display, etc.).")

_add("is_locked", "Check if the device is locked.")

_add("get_orientation", "Get current screen orientation.")

_add("set_orientation", "Set screen orientation.",
     parameters=_schema({
         "orientation": _str_param("PORTRAIT or LANDSCAPE.", enum=["PORTRAIT", "LANDSCAPE"]),
     }, required=["orientation"]))

# ============================================================
# Context
# ============================================================

_add("list_contexts", "Show available Appium contexts (NATIVE_APP, WEBVIEW_*, CHROMIUM).")

_add("get_context", "Return the current Appium context name.")

_add("switch_context", "Switch to an Appium context.",
     parameters=_schema({
         "context": _str_param("Context selector: native, webview, auto, current, or exact name."),
     }, required=["context"]))

_add("native_switch", "Switch to NATIVE_APP context.")

_add("webview_switch",
     "Switch to a WebView/CHROMIUM context. "
     "PREREQUISITE: a WebView app (e.g. Chrome) must be active with a page loaded. "
     "Call activate_app first and confirm the app is running before calling this. "
     "Fails with ERROR if no WebView context is available.",
     parameters=_schema({
         "context": _str_param("WebView context name (optional, picks first if empty)."),
     }))

_add("webview_status", "Show WebView availability, URL/title, and prerequisites.")

# ============================================================
# Web navigation
# ============================================================

_add("goto", "Navigate WebView to a URL.",
     parameters=_schema({"url": _str_param("URL to navigate to.")}, required=["url"]))

_add("go_back", "Go back in WebView history.")

_add("go_forward", "Go forward in WebView history.")

_add("reload", "Reload the current WebView page.")

# ============================================================
# Web dialogs
# ============================================================

_add("dialog_accept", "Accept the current alert/confirm/prompt dialog.",
     parameters=_schema({
         "prompt_text": _str_param("Text for prompt dialog (optional)."),
     }))

_add("dialog_dismiss", "Dismiss the current alert/confirm/prompt dialog.")

_add("dialog_text", "Read the text of the current alert/confirm/prompt dialog.")

# ============================================================
# Verification
# ============================================================

_add("assert_visible", "Assert that an element or text is visible on screen.",
     parameters=_schema({
         "text": _str_param("Text to check visibility of."),
         "ref": _str_param("Ref to check visibility of."),
     }))

# ============================================================
# Legacy locator interaction
# ============================================================

_add("find_element", "Find an element by locator strategy.",
     parameters=_schema({
         "by": _str_param("Locator strategy: xpath, id, accessibility_id, class_name.",
                          enum=["xpath", "id", "accessibility_id", "class_name"]),
         "value": _str_param("Locator value."),
     }, required=["by", "value"]))

_add("click_element", "Click an element by locator strategy.",
     parameters=_schema({
         "by": _str_param("Locator strategy.", enum=["xpath", "id", "accessibility_id", "class_name"]),
         "value": _str_param("Locator value."),
     }, required=["by", "value"]))

_add("get_text", "Get text of an element by locator.",
     parameters=_schema({
         "by": _str_param("Locator strategy.", enum=["xpath", "id", "accessibility_id", "class_name"]),
         "value": _str_param("Locator value."),
     }, required=["by", "value"]))

_add("press_keycode", "Press an Android keycode.",
     parameters=_schema({"keycode": _int_param("Android keycode number.")}, required=["keycode"]))

_add("send_keys", "Send keys to an element by locator.",
     parameters=_schema({
         "by": _str_param("Locator strategy.", enum=["xpath", "id", "accessibility_id", "class_name"]),
         "value": _str_param("Locator value."),
         "text": _str_param("Text to send."),
     }, required=["by", "value", "text"]))

_add("wait_short_loading", "Wait for a short loading period.",
     parameters=_schema({"seconds": _str_param("Seconds to wait.", default="5")}))

_add("scroll_element", "Scroll within a located element.",
     parameters=_schema({
         "by": _str_param("Locator strategy.", enum=["xpath", "id", "accessibility_id", "class_name"]),
         "value": _str_param("Locator value."),
         "direction": _str_param("Scroll direction.", default="up", enum=["up", "down", "left", "right"]),
     }, required=["by", "value"]))

_add("scroll_to_element", "Scroll until an element is found.",
     parameters=_schema({
         "by": _str_param("Locator strategy.", enum=["xpath", "id", "accessibility_id", "class_name"]),
         "value": _str_param("Locator value."),
         "scrollable_by": _str_param("Scrollable element locator strategy.", default="xpath"),
         "scrollable_value": _str_param("Scrollable element locator value.",
                                        default="//*[@scrollable='true']"),
     }, required=["by", "value"]))


# ============================================================
# Public API
# ============================================================

# Index by name for O(1) lookup
_TOOL_INDEX: dict[str, ToolDef] = {t.name: t for t in _TOOLS}

# Set of all known tool names (used for allowlist)
KNOWN_TOOL_NAMES: frozenset[str] = frozenset(_TOOL_INDEX.keys())

# Set of daemon tool names actually dispatched (subset; aliases map to base tools)
KNOWN_DAEMON_TOOLS: frozenset[str] = frozenset(t.daemon_tool for t in _TOOLS)


def get_tool(name: str) -> ToolDef | None:
    """Look up a tool by canonical name. Returns None if not found."""
    return _TOOL_INDEX.get(name)


def list_tools() -> list[ToolDef]:
    """Return all registered tools in definition order."""
    return list(_TOOLS)


def normalize_tool_call(name: str, arguments: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """Resolve a tool call to (daemon_tool_name, merged_arguments).

    Merges inject_args (for directional aliases) with caller-supplied arguments.
    Raises KeyError if tool name is not registered.
    """
    tool_def = _TOOL_INDEX.get(name)
    if tool_def is None:
        raise KeyError(f"Unknown tool: {name}")
    merged = {**tool_def.inject_args, **(arguments or {})}
    return tool_def.daemon_tool, merged
