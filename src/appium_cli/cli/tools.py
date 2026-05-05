"""CLI wrappers for daemon-backed tool commands."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from appium_cli.daemon.client import request
from appium_cli.utils import exit_codes


def _daemon_request(tool: str, json_output: bool, args: dict | None = None) -> None:
    try:
        response = request(tool, args=args)
    except (FileNotFoundError, ConnectionError, OSError) as exc:
        if json_output:
            typer.echo(json.dumps({"ok": False, "error": "Session daemon is not running", "detail": str(exc)}))
        else:
            typer.echo("ERROR: Session daemon is not running", err=True)
        raise typer.Exit(exit_codes.STOPPED) from exc

    if json_output:
        typer.echo(json.dumps(response, indent=2))
    elif response.get("ok"):
        typer.echo(response.get("text", ""), nl=not str(response.get("text", "")).endswith("\n"))
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
    scope: Annotated[str, typer.Option("--scope", help="Snapshot scope.")] = "full",
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Get an accessibility snapshot with refs."""

    _daemon_request("snapshot", json_output, {"scope": scope})


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
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Take a screenshot and return the smartestiroid-compatible JSON string."""

    _daemon_request("screenshot", json_output, {"region": region})


def get_page_source(
    json_output: Annotated[bool, typer.Option("--json", help="Wrap the result in JSON.")] = False,
) -> None:
    """Return compressed current screen XML."""

    _daemon_request("get_page_source", json_output)


def tap(ref: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("tap", json_output, {"ref": ref})


def type_text(ref: str, text: str, submit: Annotated[bool, typer.Option("--submit")] = False, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    _daemon_request("type_text", json_output, {"ref": ref, "text": text, "submit": submit})


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
