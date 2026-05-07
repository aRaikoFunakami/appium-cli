"""Tests for Responses API tool schema conversion."""

from __future__ import annotations

from agent_browser.agent.registry import get_response_tool_schemas


def test_response_tool_schemas_are_direct_functions() -> None:
    tools = get_response_tool_schemas()
    assert len(tools) >= 60
    first = tools[0]
    assert first["type"] == "function"
    assert "name" in first
    assert "parameters" in first
    assert "function" not in first
