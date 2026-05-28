"""Unit tests for openai_tools module."""

from __future__ import annotations

import json

import pytest

import appium_cli.openai_tools as openai_tools
from appium_cli.openai_tools import call_tool, get_openai_tool, get_openai_tools, get_tool_skill_prompt
from appium_cli.utils import exit_codes


@pytest.fixture(autouse=True)
def _reset_prompt_mode() -> None:
    openai_tools._reset_tool_skill_prompt_mode_for_tests()


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


class TestGetToolSkillPrompt:
    def test_returns_reusable_tool_usage_prompt_fragment(self) -> None:
        prompt = get_tool_skill_prompt()

        assert "appium-cli tool skill" in prompt
        assert "goto" in prompt
        assert "activate_app" in prompt
        assert "snapshot_search" in prompt
        assert "wait_for" in prompt
        assert "Current appium-cli context guidance: NATIVE_APP" in prompt
        assert "Current appium-cli context guidance: WebView / Chrome" not in prompt

    def test_includes_latest_skill_guidance(self) -> None:
        prompt = get_tool_skill_prompt()

        for expected in (
            "webview_status",
            "list_apps",
            "snapshot_actionable_tree",
            "list_containers",
            "within_container",
            "assert_visible",
            "find_by_text",
            "console_messages",
            "network_requests",
            "get_device_info",
            "wait_short_loading",
        ):
            assert expected in prompt

    def test_uses_function_call_oriented_guidance(self) -> None:
        prompt = get_tool_skill_prompt()

        assert "appium-cli snapshot" not in prompt
        assert "get_system_prompt" not in prompt
        assert "depth=8" not in prompt
        assert "Do not use depth for normal full-page observations" in prompt
        assert "Use depth only for scoped/debug snapshots" in prompt

    def test_documents_snapshot_required_after_positional_gestures(self) -> None:
        prompt = get_tool_skill_prompt()

        # Agents should prefer explicit refresh, while daemon recovery handles stale refs safely.
        assert "auto-refresh/retry once" in prompt
        assert "snapshot_actionable_tree({}) only renders the last snapshot" in prompt
        assert "Call snapshot({}) first when you need a guaranteed fresh tree" in prompt

    def test_includes_ordered_webview_workflow_examples(self) -> None:
        self._mock_successful_call("goto", {"url": "https://example.com"})
        prompt = get_tool_skill_prompt()

        assert "Current appium-cli context guidance: WebView / Chrome" in prompt
        assert "Open a URL and inspect the page" in prompt
        assert '1. goto({"url": "https://example.com"})' in prompt
        assert "2. web_snapshot({})" in prompt
        assert 'snapshot_search({"text": "target text"})' in prompt
        assert 'web_query({"selector": "a", "attrs": "href,textContent,aria-label", "limit": 50})' in prompt

    def test_includes_portal_category_workflow_example(self) -> None:
        self._mock_successful_call("goto", {"url": "https://example.com"})
        prompt = get_tool_skill_prompt()

        assert "Find a category or news page from a portal" in prompt
        assert 'goto({"url": "https://www.yahoo.co.jp/"})' in prompt
        assert 'snapshot_search({"text": "スポーツ"})' in prompt
        assert "a[href*='sports']" in prompt
        assert "a[href*='/articles/']" in prompt
        assert "Do not conclude that a link/category is absent from one broad query" in prompt

    def test_includes_native_and_form_workflow_examples(self) -> None:
        prompt = get_tool_skill_prompt()

        assert "Native UI: observe, understand operable hierarchy, act" in prompt
        assert "snapshot_actionable_tree({})" in prompt
        assert 'snapshot_search({"text": "<visible label>"})' in prompt
        assert 'tap({"ref": "<ref selected from the actionable hierarchy>"})' in prompt
        assert 'Do NOT default to role="button" in native UI' in prompt
        assert "tap_target_ref/action_target_ref" in prompt
        assert "Search or submit a simple single-input form" not in prompt

    def test_includes_any_text_or_guidance(self) -> None:
        prompt = get_tool_skill_prompt()

        assert "any_text" in prompt
        assert "Do not invent regex or AND syntax" in prompt

        self._mock_successful_call("webview_switch", {})
        prompt = get_tool_skill_prompt()
        assert "Search or submit a simple single-input form" in prompt
        assert 'fill({"ref": "web_<search input ref>", "text": "query", "submit": true})' in prompt
        assert "Multi-field station/address/location forms" in prompt
        assert 'press_key({"key": "escape"})' in prompt
        assert "file_upload" in prompt

    def test_prompt_mode_switches_to_webview_after_goto(self, monkeypatch) -> None:
        def fake_request(tool, args=None, **kwargs):
            return {"ok": True, "text": "Navigated to https://example.com", "data": {}}

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        assert "Current appium-cli context guidance: NATIVE_APP" in get_tool_skill_prompt()
        call_tool("goto", {"url": "https://example.com"})
        prompt = get_tool_skill_prompt()
        assert "Current appium-cli context guidance: WebView / Chrome" in prompt
        assert "Native UI: observe, find refs, act" not in prompt

    def test_prompt_mode_switches_back_to_native_after_native_switch(self, monkeypatch) -> None:
        def fake_request(tool, args=None, **kwargs):
            return {"ok": True, "text": "OK", "data": {}}

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        call_tool("webview_switch", {})
        assert "Current appium-cli context guidance: WebView / Chrome" in get_tool_skill_prompt()
        call_tool("native_switch", {})
        assert "Current appium-cli context guidance: NATIVE_APP" in get_tool_skill_prompt()

    def test_web_snapshot_does_not_switch_prompt_mode(self, monkeypatch) -> None:
        def fake_request(tool, args=None, **kwargs):
            return {"ok": True, "text": "snapshot_id: web-test\nsource: web\n", "data": {}}

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        call_tool("web_snapshot", {})
        assert "Current appium-cli context guidance: NATIVE_APP" in get_tool_skill_prompt()

    def test_failed_goto_does_not_switch_prompt_mode(self, monkeypatch) -> None:
        def fake_request(tool, args=None, **kwargs):
            return {"ok": False, "error": "No WebView context", "data": {}}

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        call_tool("goto", {"url": "https://example.com"})
        assert "Current appium-cli context guidance: NATIVE_APP" in get_tool_skill_prompt()

    def test_switch_context_updates_prompt_mode_for_obvious_targets(self, monkeypatch) -> None:
        def fake_request(tool, args=None, **kwargs):
            return {"ok": True, "text": f"Switched to {args.get('context')}", "data": {}}

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        call_tool("switch_context", {"context": "CHROMIUM"})
        assert "Current appium-cli context guidance: WebView / Chrome" in get_tool_skill_prompt()
        call_tool("switch_context", {"context": "NATIVE_APP"})
        assert "Current appium-cli context guidance: NATIVE_APP" in get_tool_skill_prompt()

    @staticmethod
    def _mock_successful_call(tool_name: str, args: dict[str, object]) -> None:
        def fake_request(tool, args=None, **kwargs):
            return {"ok": True, "text": "OK", "data": {}}

        original = openai_tools.request
        try:
            openai_tools.request = fake_request
            call_tool(tool_name, args)
        finally:
            openai_tools.request = original

    def test_does_not_expose_system_prompt_api(self) -> None:
        assert not hasattr(openai_tools, "get_system_prompt")


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
        assert captured["raw"] is False

    def test_snapshot_uses_metadata_output_by_default(self, monkeypatch) -> None:
        captured = {}

        def fake_request(tool, args=None, **kwargs):
            captured["tool"] = tool
            captured["args"] = args
            captured["raw"] = kwargs.get("raw", False)
            return {
                "ok": True,
                "text": "snapshot_id: web-test\nartifacts:\n  compact: /tmp/test.compact.yml\n",
                "data": {"snapshot_id": "web-test"},
            }

        monkeypatch.setattr("appium_cli.openai_tools.request", fake_request)

        result = call_tool("web_snapshot", {})
        assert result["ok"] is True
        assert captured["tool"] == "web_snapshot"
        assert captured["raw"] is False

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
