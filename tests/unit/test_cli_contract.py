from __future__ import annotations

import json

from typer.testing import CliRunner

from appium_cli.__main__ import app
from appium_cli.cli import doctor as doctor_module
from appium_cli.cli import session as session_module
from appium_cli.cli import tools as tools_module
from appium_cli.cli.doctor import Check
from appium_cli.cli.server import ServerState


def test_directional_aliases_route_to_existing_daemon_tools(monkeypatch) -> None:
    calls: list[tuple[str, dict | None]] = []

    def fake_request(tool: str, args: dict | None = None):
        calls.append((tool, args))
        return {"ok": True, "text": "OK", "data": {}}

    monkeypatch.setattr(tools_module, "request", fake_request)
    runner = CliRunner()

    result = runner.invoke(app, ["scroll_down", "recycler_view", "--percent", "0.5"])
    assert result.exit_code == 0
    result = runner.invoke(app, ["swipe_left"])
    assert result.exit_code == 0
    result = runner.invoke(app, ["fling_up", "recycler_view", "--speed", "1000"])
    assert result.exit_code == 0

    assert calls == [
        ("scroll", {"direction": "down", "ref": "recycler_view", "percent": 0.5}),
        ("swipe", {"direction": "left", "ref": "", "percent": 0.8}),
        ("fling", {"direction": "up", "ref": "recycler_view", "speed": 1000}),
    ]


def test_all_top_level_commands_expose_json_option() -> None:
    runner = CliRunner()
    commands = [
        "doctor",
        "devices",
        "snapshot",
        "describe",
        "find_by_text",
        "screenshot",
        "get_page_source",
        "get_device_info",
        "tap",
        "click",
        "type_text",
        "fill",
        "select",
        "scroll",
        "scroll_up",
        "scroll_down",
        "scroll_left",
        "scroll_right",
        "swipe",
        "swipe_up",
        "swipe_down",
        "swipe_left",
        "swipe_right",
        "press_key",
        "wait",
        "long_press",
        "double_tap",
        "drag",
        "fling",
        "fling_up",
        "fling_down",
        "fling_left",
        "fling_right",
        "pinch_open",
        "pinch_close",
        "list_containers",
        "find_container",
        "within_container",
        "assert_visible",
        "get_current_app",
        "activate_app",
        "terminate_app",
        "list_apps",
        "restart_app",
        "is_locked",
        "get_orientation",
        "set_orientation",
        "find_element",
        "click_element",
        "get_text",
        "press_keycode",
        "send_keys",
        "wait_short_loading",
        "scroll_element",
        "scroll_to_element",
        "install",
        # WebView commands
        "list_contexts",
        "get_context",
        "switch_context",
        "native_switch",
        "webview_switch",
        "webview_status",
        "web_snapshot",
        "webview_url",
        "webview_title",
        "goto",
        "go_back",
        "go_forward",
        "reload",
        "web_eval",
        "dialog_accept",
        "dialog_dismiss",
        "dialog_text",
    ]

    for command in commands:
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, command
        assert "--json" in result.output, command


def test_server_and_session_subcommands_expose_json_option() -> None:
    runner = CliRunner()
    for command in (["server", "status"], ["server", "start"], ["server", "stop"], ["session", "status"], ["session", "start"], ["session", "stop"]):
        result = runner.invoke(app, [*command, "--help"])
        assert result.exit_code == 0, command
        assert "--json" in result.output, command


def test_doctor_json_output(monkeypatch) -> None:
    monkeypatch.setattr(doctor_module, "_checks", lambda: [Check("Node.js", "PASS", "/usr/bin/node")])

    result = CliRunner().invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["checks"][0]["name"] == "Node.js"


def test_server_status_json_output(monkeypatch) -> None:
    monkeypatch.setattr("appium_cli.cli.server.get_status", lambda port: ServerState(True, "external", port, f"http://127.0.0.1:{port}"))

    result = CliRunner().invoke(app, ["server", "status", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["running"] is True
    assert payload["ownership"] == "external"


def test_session_status_json_output(monkeypatch) -> None:
    def fake_request(tool: str):
        assert tool == "get_driver_status"
        return {
            "ok": True,
            "text": "Driver is initialized and ready",
            "data": {"ready": True, "session_id": "session-1", "udid": "device-1"},
        }

    monkeypatch.setattr(session_module, "request", fake_request)

    result = CliRunner().invoke(app, ["session", "status", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["running"] is True
    assert payload["session_id"] == "session-1"
