"""OpenAI tool interface adapter for appium-cli.

This module provides:
- ``get_openai_tools()`` — Generate OpenAI Chat Completions tool definitions
- ``call_tool()`` — Execute a tool call through the session daemon
- ``get_tool_skill_prompt()`` — Return reusable appium-cli tool usage guidance

It does NOT import or depend on the OpenAI SDK. External callers import
this module and wire it into their own OpenAI client loop.

Usage example (external caller)::

    from openai import OpenAI
    from appium_cli.openai_tools import get_openai_tools, call_tool

    client = OpenAI()
    tools = get_openai_tools()

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[...],
        tools=tools,
    )

    for tool_call in response.choices[0].message.tool_calls:
        result = call_tool(tool_call.function.name, tool_call.function.arguments)
        # submit result back to OpenAI...
"""

from __future__ import annotations

import json
from typing import Any

from appium_cli.daemon.client import request
from appium_cli.tool_registry import ToolDef, get_tool, list_tools, normalize_tool_call
from appium_cli.utils import exit_codes


TOOL_SKILL_PROMPT = """appium-cli tool skill:

Use appium-cli tools as a snapshot/ref-based mobile automation surface. Observe the current UI, choose refs from the latest observation or saved snapshot artifacts, act on those refs, then observe or inspect the post-action state before choosing the next target.

Context rules:
- Native context: use snapshot for observation, tap for clicks/taps, type_text for native text entry, and scroll_down/scroll_up/swipe_* for native gestures.
- WebView/Chrome context: use web_snapshot for observation, click for links/buttons, fill for inputs, select/select_option/set_date for form controls, and webview_url/webview_title for quick URL/title checks.
- After goto or webview_switch succeeds, treat page-level work as WebView automation until native_switch is called.
- Do not use native tap/type_text workflows for normal DOM interaction when web_* refs or CSS selectors are available.

Navigation and app launch:
- Use goto(url) to navigate the current WebView/Chrome tab. goto auto-switches to WebView when needed.
- Do not use web_eval to assign window.location/location.href/history state, and do not search for or tap a browser address bar just to load a URL.
- Use tabs tools only when the task actually requires multiple tabs.
- If the target app package is known, use activate_app(package). Do not loop on launcher snapshots looking for app icons; launcher labels are often text-only and not actionable.

Observation strategy:
- Primary observation is snapshot in native context and web_snapshot in WebView context.
- Prefer targeted artifact inspection before broad output: snapshot_search for text, snapshot_refs for ref lists, and snapshot_show with a ref for one element/subtree.
- Use web_query to discover WebView elements, CSS selectors, attributes, and matching refs without reading a whole DOM tree.
- Use screenshot only when visual pixels are necessary. Use get_page_source only as a diagnostic escape hatch after snapshot/web_snapshot, snapshot_search, snapshot_refs, snapshot_show, and web_query are insufficient.
- Prefer web_snapshot depth=8 unless there is a clear reason to use a shallower depth.

Ref and targeting rules:
- Use refs only from the latest current observation or latest snapshot artifacts. Old refs can become stale after snapshot/web_snapshot, navigation, reload, scrolling, dialogs, or major screen changes.
- If visible text has no ref, target the nearest actionable parent row, button, link, container, or form control.
- If duplicates are present, inspect candidates with snapshot_refs or snapshot_show before acting.
- Snapshot refs are valid function-call arguments. CSS selectors discovered by web_query are not refs unless passed through supported CSS selector syntax such as css:#submit, css:.class, or css:[name='q'].
- Use generate_locator(ref) when a durable locator or CSS selector is needed.

Async UI and forms:
- Use wait_for for asynchronous conditions: text appears, text disappears, or a ref becomes visible.
- For simple inputs, fill/type_text and continue. For single-input forms such as search bars, URL bars, and filters, submit the input when the task requires applying it.
- Never submit intermediate fields in a multi-field form unless the user asked for submission.
- For autocomplete, combobox, React-Select, validation popovers, or search-as-you-type fields, use slow typing when needed, then observe with web_snapshot and either click the matching option or dismiss unneeded transient UI before interacting with another element.
- Do not use web_eval to set input values; use fill so browser/framework input events fire.

WebView fallbacks and limitations:
- Targeting order in WebView is refs first, CSS selectors/web_query/generated locators second, legacy locator tools last.
- Native touch-only gestures such as long_press, drag, fling_*, pinch_*, and native swipe_* are not available in WebView context; use WebView actions or switch to native intentionally.
- web_form_url is read-only and skips frontend interaction. Use it only for information retrieval or debugging, not to claim that a form was tested or submitted through the UI.
"""


def get_tool_skill_prompt() -> str:
    """Return reusable appium-cli tool usage guidance for tool-calling agents.

    The returned text is a composable prompt fragment, not a complete system
    prompt. Callers should combine it with their own role, memory, safety,
    output-format, and completion instructions.
    """
    return TOOL_SKILL_PROMPT


def _tool_to_openai_schema(tool_def: ToolDef) -> dict[str, Any]:
    """Convert a ToolDef to OpenAI Chat Completions tool format."""
    return {
        "type": "function",
        "function": {
            "name": tool_def.name,
            "description": tool_def.description,
            "parameters": tool_def.parameters,
        },
    }


def get_openai_tools() -> list[dict[str, Any]]:
    """Return all tools as OpenAI Chat Completions tool definitions.

    Each entry has the shape::

        {
            "type": "function",
            "function": {
                "name": "snapshot",
                "description": "...",
                "parameters": { "type": "object", "properties": {...}, ... }
            }
        }
    """
    return [_tool_to_openai_schema(t) for t in list_tools()]


def get_openai_tool(name: str) -> dict[str, Any] | None:
    """Return a single tool definition by name, or None if not found."""
    tool_def = get_tool(name)
    if tool_def is None:
        return None
    return _tool_to_openai_schema(tool_def)


def call_tool(name: str, arguments: dict[str, Any] | str | None = None) -> dict[str, Any]:
    """Execute a tool call through the session daemon.

    Args:
        name: Canonical tool name (e.g. "snapshot", "scroll_down").
        arguments: Tool arguments as a dict or JSON string (OpenAI returns
                   arguments as a JSON string in tool_calls).

    Returns:
        Daemon response dict with keys: ok, text, data, and optionally
        error/exit_code on failure.
    """
    # Parse JSON string arguments (OpenAI returns them as strings)
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except (json.JSONDecodeError, ValueError):
            return {
                "ok": False,
                "error": f"Invalid JSON arguments: {arguments!r}",
                "exit_code": exit_codes.GENERAL_ERROR,
            }

    # Resolve tool name and merge directional alias args
    try:
        daemon_tool, merged_args = normalize_tool_call(name, arguments)
    except KeyError:
        return {
            "ok": False,
            "error": f"Unknown tool: {name}",
            "exit_code": exit_codes.GENERAL_ERROR,
        }

    # Call the daemon with raw=True so snapshot tools return the full tree
    # content instead of just artifact file paths (metadata-only mode is for
    # human CLI usage; programmatic callers need the tree text).
    try:
        response = request(daemon_tool, args=merged_args if merged_args else None, raw=True)
    except (FileNotFoundError, ConnectionError, OSError) as exc:
        return {
            "ok": False,
            "error": "Session daemon is not running",
            "detail": str(exc),
            "exit_code": exit_codes.STOPPED,
        }

    return response
