"""Unit tests for openai_tools module."""

from __future__ import annotations

import json

import pytest

from appium_cli.openai_tools import call_tool, get_openai_tool, get_openai_tools
from appium_cli.utils import exit_codes


class TestGetOpenAITools:
    def test_returns_list_of_tool_definitions(self) -> None:
        tools = get_openai_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 60

    def test_each_tool_has_correct_shape(self) -> None:
        tools = get_openai_tools()
        for tool in tools:
            assert tool["type"] == "function", f"Missing type:function in {tool}"
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            params = func["parameters"]
            assert params["type"] == "object"
            assert "properties" in params

    def test_snapshot_tool_definition(self) -> None:
        tools = get_openai_tools()
        snapshot_tools = [t for t in tools if t["function"]["name"] == "snapshot"]
        assert len(snapshot_tools) == 1
        func = snapshot_tools[0]["function"]
        assert "accessibility snapshot" in func["description"].lower()
        props = func["parameters"]["properties"]
        assert "scope" in props
        assert "context" in props

    def test_directional_aliases_are_separate_tools(self) -> None:
        tools = get_openai_tools()
        names = {t["function"]["name"] for t in tools}
        assert "scroll_down" in names
        assert "swipe_up" in names
        assert "fling_left" in names


class TestGetOpenAITool:
    def test_returns_single_tool(self) -> None:
        tool = get_openai_tool("tap")
        assert tool is not None
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "tap"

    def test_returns_none_for_unknown(self) -> None:
        assert get_openai_tool("nonexistent") is None


class TestCallTool:
    def test_dict_arguments(self, monkeypatch) -> None:
        captured = {}

        def fake_request(tool, args=None, **kwargs):
            captured["tool"] = tool
            captured["args"] = args
            captured["raw"] = kwargs.get("raw", False)
            return {"ok": True, "text": "OK", "data": {}}

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        result = call_tool("tap", {"ref": "login_btn"})
        assert result["ok"] is True
        assert captured["tool"] == "tap"
        assert captured["args"] == {"ref": "login_btn"}
        assert captured["raw"] is True

    def test_json_string_arguments(self, monkeypatch) -> None:
        captured = {}

        def fake_request(tool, args=None, **kwargs):
            captured["tool"] = tool
            captured["args"] = args
            return {"ok": True, "text": "OK", "data": {}}

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        result = call_tool("tap", '{"ref": "submit_btn"}')
        assert result["ok"] is True
        assert captured["args"] == {"ref": "submit_btn"}

    def test_empty_string_arguments(self, monkeypatch) -> None:
        captured = {}

        def fake_request(tool, args=None, **kwargs):
            captured["tool"] = tool
            captured["args"] = args
            return {"ok": True, "text": "pong", "data": {}}

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        result = call_tool("list_containers", "")
        assert result["ok"] is True
        assert captured["args"] is None  # empty dict -> None

    def test_none_arguments(self, monkeypatch) -> None:
        captured = {}

        def fake_request(tool, args=None, **kwargs):
            captured["tool"] = tool
            captured["args"] = args
            return {"ok": True, "text": "OK", "data": {}}

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        result = call_tool("get_device_info", None)
        assert result["ok"] is True
        assert captured["args"] is None

    def test_directional_alias_merges_args(self, monkeypatch) -> None:
        captured = {}

        def fake_request(tool, args=None, **kwargs):
            captured["tool"] = tool
            captured["args"] = args
            return {"ok": True, "text": "OK\nsnap", "data": {}}

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        result = call_tool("scroll_down", {"ref": "recycler_view", "percent": 0.5})
        assert result["ok"] is True
        assert captured["tool"] == "scroll"
        assert captured["args"] == {"direction": "down", "ref": "recycler_view", "percent": 0.5}

    def test_unknown_tool_returns_error(self) -> None:
        result = call_tool("nonexistent_tool", {})
        assert result["ok"] is False
        assert "Unknown tool" in result["error"]
        assert result["exit_code"] == exit_codes.GENERAL_ERROR

    def test_invalid_json_arguments_returns_error(self) -> None:
        result = call_tool("tap", "{invalid json")
        assert result["ok"] is False
        assert "Invalid JSON" in result["error"]

    def test_daemon_not_running_returns_error(self, monkeypatch) -> None:
        def fake_request(tool, args=None, **kwargs):
            raise FileNotFoundError("socket not found")

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        result = call_tool("snapshot", {"scope": "full"})
        assert result["ok"] is False
        assert "Session daemon is not running" in result["error"]
        assert result["exit_code"] == exit_codes.STOPPED

    def test_daemon_response_preserved(self, monkeypatch) -> None:
        """Daemon response should be returned as-is."""
        daemon_response = {
            "id": "abc-123",
            "ok": True,
            "text": "Device Information:\nModel: Pixel 6\n",
            "data": {"some": "metadata"},
        }

        def fake_request(tool, args=None, **kwargs):
            return daemon_response

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        result = call_tool("get_device_info", None)
        assert result == daemon_response
