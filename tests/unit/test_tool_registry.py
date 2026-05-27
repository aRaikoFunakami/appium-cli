"""Unit tests for tool_registry module."""

from __future__ import annotations

import pytest

from appium_cli.tool_registry import (
    KNOWN_DAEMON_TOOLS,
    KNOWN_TOOL_NAMES,
    ToolDef,
    get_tool,
    list_tools,
    normalize_tool_call,
)


class TestToolLookup:
    def test_get_tool_returns_tooldef(self) -> None:
        tool = get_tool("snapshot")
        assert tool is not None
        assert isinstance(tool, ToolDef)
        assert tool.name == "snapshot"
        assert tool.daemon_tool == "snapshot"

    def test_get_tool_unknown_returns_none(self) -> None:
        assert get_tool("nonexistent_tool") is None

    def test_list_tools_returns_all(self) -> None:
        tools = list_tools()
        assert len(tools) >= 60
        names = {t.name for t in tools}
        assert "snapshot" in names
        assert "tap" in names
        assert "scroll_down" in names

    def test_known_tool_names_is_frozenset(self) -> None:
        assert isinstance(KNOWN_TOOL_NAMES, frozenset)
        assert "tap" in KNOWN_TOOL_NAMES
        assert "nonexistent" not in KNOWN_TOOL_NAMES


class TestDirectionalAliases:
    @pytest.mark.parametrize("alias,expected_dir", [
        ("scroll_up", "up"),
        ("scroll_down", "down"),
        ("scroll_left", "left"),
        ("scroll_right", "right"),
    ])
    def test_scroll_aliases(self, alias: str, expected_dir: str) -> None:
        daemon_tool, args = normalize_tool_call(alias, {"ref": "container"})
        assert daemon_tool == "scroll"
        assert args["direction"] == expected_dir
        assert args["ref"] == "container"

    @pytest.mark.parametrize("alias,expected_dir", [
        ("swipe_up", "up"),
        ("swipe_down", "down"),
        ("swipe_left", "left"),
        ("swipe_right", "right"),
    ])
    def test_swipe_aliases(self, alias: str, expected_dir: str) -> None:
        daemon_tool, args = normalize_tool_call(alias, {})
        assert daemon_tool == "swipe"
        assert args["direction"] == expected_dir

    @pytest.mark.parametrize("alias,expected_dir", [
        ("fling_up", "up"),
        ("fling_down", "down"),
        ("fling_left", "left"),
        ("fling_right", "right"),
    ])
    def test_fling_aliases(self, alias: str, expected_dir: str) -> None:
        daemon_tool, args = normalize_tool_call(alias, {"ref": "list", "speed": 2000})
        assert daemon_tool == "fling"
        assert args["direction"] == expected_dir
        assert args["ref"] == "list"
        assert args["speed"] == 2000

    def test_alias_inject_does_not_override_caller_args(self) -> None:
        # inject_args provides direction, caller supplies ref and percent
        daemon_tool, args = normalize_tool_call("scroll_down", {"ref": "rv", "percent": 0.5})
        assert args == {"direction": "down", "ref": "rv", "percent": 0.5}


class TestNormalization:
    def test_normalize_known_tool(self) -> None:
        daemon_tool, args = normalize_tool_call("tap", {"ref": "login_btn"})
        assert daemon_tool == "tap"
        assert args == {"ref": "login_btn"}

    def test_normalize_unknown_tool_raises(self) -> None:
        with pytest.raises(KeyError, match="Unknown tool"):
            normalize_tool_call("nonexistent_tool", {})

    def test_normalize_none_args(self) -> None:
        daemon_tool, args = normalize_tool_call("list_containers", None)
        assert daemon_tool == "list_containers"
        assert args == {}


class TestSchemaStructure:
    def test_all_tools_have_valid_schema(self) -> None:
        for tool in list_tools():
            assert tool.parameters.get("type") == "object", f"{tool.name} missing type:object"
            assert "properties" in tool.parameters, f"{tool.name} missing properties"

    def test_required_tools_have_required_field(self) -> None:
        tool = get_tool("tap")
        assert tool is not None
        assert "required" in tool.parameters
        assert "ref" in tool.parameters["required"]

    def test_no_required_field_when_no_required_params(self) -> None:
        tool = get_tool("list_containers")
        assert tool is not None
        assert "required" not in tool.parameters or tool.parameters.get("required") == []

    def test_get_page_source_schema_includes_raw(self) -> None:
        tool = get_tool("get_page_source")
        assert tool is not None
        raw = tool.parameters["properties"]["raw"]
        assert raw["type"] == "boolean"
        assert raw["default"] is False

    def test_snapshot_navigation_schemas(self) -> None:
        show = get_tool("snapshot_show")
        search = get_tool("snapshot_search")
        refs = get_tool("snapshot_refs")
        assert show is not None
        assert search is not None
        assert refs is not None
        assert show.parameters["properties"]["artifact"]["enum"] == [
            "compact", "full", "refs", "index", "meta"
        ]
        assert "text" in search.parameters["required"]
        assert refs.parameters["properties"]["role"]["type"] == "string"
        assert refs.parameters["properties"]["limit"]["default"] == 50
        assert refs.parameters["properties"]["offset"]["default"] == 0

    def test_or_search_schemas(self) -> None:
        search = get_tool("snapshot_search")
        find = get_tool("find_by_text")
        assert search is not None
        assert find is not None
        # any_text should be an optional array of strings
        search_any = search.parameters["properties"]["any_text"]
        assert search_any["type"] == "array"
        assert search_any["items"]["type"] == "string"
        assert "any_text" not in search.parameters.get("required", [])
        find_any = find.parameters["properties"]["any_text"]
        assert find_any["type"] == "array"
        assert find_any["items"]["type"] == "string"
        assert "any_text" not in find.parameters.get("required", [])

    def test_locator_query_schemas(self) -> None:
        locator = get_tool("generate_locator")
        query = get_tool("web_query")
        text = get_tool("web_text")
        assert locator is not None
        assert query is not None
        assert text is not None
        assert locator.parameters["required"] == ["ref"]
        assert query.parameters["required"] == ["selector"]
        assert query.parameters["properties"]["attrs"]["type"] == "string"
        assert query.parameters["properties"]["limit"]["default"] == 20
        assert text.parameters.get("required", []) == []
        assert text.parameters["properties"]["limit"]["default"] == 6000


class TestKnownDaemonTools:
    def test_includes_base_tools(self) -> None:
        assert "scroll" in KNOWN_DAEMON_TOOLS
        assert "swipe" in KNOWN_DAEMON_TOOLS
        assert "fling" in KNOWN_DAEMON_TOOLS
        assert "tap" in KNOWN_DAEMON_TOOLS
        assert "snapshot" in KNOWN_DAEMON_TOOLS

    def test_does_not_include_aliases_as_daemon_tools(self) -> None:
        # scroll_down maps to daemon tool "scroll", not "scroll_down"
        assert "scroll_down" not in KNOWN_DAEMON_TOOLS
        assert "swipe_up" not in KNOWN_DAEMON_TOOLS
        assert "fling_left" not in KNOWN_DAEMON_TOOLS


class TestExpectedToolsCoverage:
    """Verify all tools that daemon/entry.py currently dispatches are in the registry."""

    EXPECTED_DAEMON_TOOLS = {
        "snapshot", "describe", "find_by_text", "screenshot", "get_page_source",
        "snapshot_show", "snapshot_search", "snapshot_refs", "generate_locator", "web_query", "web_text", "web_form_url",
        "list_contexts", "get_context", "switch_context", "native_switch",
        "webview_switch", "webview_status", "web_snapshot", "webview_url", "webview_title",
        "goto", "go_back", "go_forward", "reload",
        "dialog_accept", "dialog_dismiss", "dialog_text",
        "tap", "click", "type_text", "fill", "select", "scroll", "swipe",
        "press_key", "wait", "long_press", "double_tap", "drag", "fling",
        "pinch_open", "pinch_close", "web_eval",
        "list_containers", "find_container", "within_container", "assert_visible",
        "get_current_app", "activate_app", "terminate_app", "list_apps", "restart_app",
        "get_device_info", "is_locked", "get_orientation", "set_orientation",
        "find_element", "click_element", "get_text", "press_keycode",
        "send_keys", "wait_short_loading", "scroll_element", "scroll_to_element",
    }

    def test_all_daemon_dispatched_tools_are_registered(self) -> None:
        missing = self.EXPECTED_DAEMON_TOOLS - KNOWN_DAEMON_TOOLS
        assert not missing, f"Tools missing from registry: {missing}"
