"""Responses API tool schema registry."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from appium_cli.openai_tools import get_openai_tools


def _response_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert appium-cli's Chat-style schema to Responses API function schema."""

    func = schema.get("function", {})
    parameters = deepcopy(func.get("parameters") or {"type": "object", "properties": {}})
    if parameters.get("type") == "object":
        parameters.setdefault("additionalProperties", False)
    return {
        "type": "function",
        "name": func["name"],
        "description": func.get("description", ""),
        "parameters": parameters,
    }


def get_response_tool_schemas() -> list[dict[str, Any]]:
    return [_response_tool_schema(schema) for schema in get_openai_tools()]
