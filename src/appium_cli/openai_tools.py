"""OpenAI tool interface adapter for appium-cli.

This module provides:
- ``get_openai_tools()`` — Generate OpenAI Chat Completions tool definitions
- ``call_tool()`` — Execute a tool call through the session daemon

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

    # Call the daemon
    try:
        response = request(daemon_tool, args=merged_args if merged_args else None)
    except (FileNotFoundError, ConnectionError, OSError) as exc:
        return {
            "ok": False,
            "error": "Session daemon is not running",
            "detail": str(exc),
            "exit_code": exit_codes.STOPPED,
        }

    return response
