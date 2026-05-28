"""Command-line entry point for appium-cli."""

from __future__ import annotations

import atexit
import json
import sys
import time
from datetime import datetime, timezone
from typing import Annotated

import typer

from appium_cli import __version__
from appium_cli.cli.devices import devices
from appium_cli.cli.doctor import doctor
from appium_cli.cli.install import install
from appium_cli.cli.runtime import set_raw_output
from appium_cli.cli.server import app as server_app
from appium_cli.cli.session import app as session_app
from appium_cli.cli.tools import (
    activate_app,
    assert_visible,
    click,
    click_element,
    describe,
    dialog_accept,
    dialog_dismiss,
    dialog_text,
    double_tap,
    drag,
    fill,
    find_by_text,
    find_element,
    find_container,
    fling,
    fling_down,
    fling_left,
    fling_right,
    fling_up,
    get_context,
    get_current_app,
    get_device_info,
    generate_locator,
    get_orientation,
    get_page_source,
    get_text,
    go_back,
    go_forward,
    goto,
    is_locked,
    list_contexts,
    long_press,
    list_apps,
    list_containers,
    native_switch,
    pinch_close,
    pinch_open,
    press_key,
    press_keycode,
    reload_page,
    restart_app,
    screenshot,
    scroll,
    scroll_down,
    scroll_element,
    scroll_left,
    scroll_right,
    scroll_to_element,
    scroll_up,
    select,
    select_option,
    set_date,
    set_orientation,
    send_keys,
    snapshot,
    snapshot_actionable_tree,
    web_refs,
    snapshot_search,
    snapshot_show,
    switch_context,
    swipe,
    swipe_down,
    swipe_left,
    swipe_right,
    swipe_up,
    tap,
    terminate_app,
    type_text,
    wait,
    wait_for,
    wait_short_loading,
    web_eval,
    web_form_url,
    web_query,
    web_text,
    web_snapshot,
    webview_status,
    webview_switch,
    webview_title,
    webview_url,
    within_container,
    file_upload,
    console_messages,
    tabs_cmd,
    network_requests_cmd,
)
from appium_cli.cli.usage_suggestions import format_suggestion, suggest_usage
from appium_cli.utils import exit_codes


# --- Invocation logging state ---
_log_start_time: float = 0.0
_log_argv: list[str] = []
_log_exit_code: int = 0

# Keys whose values should be excluded from log args
_SENSITIVE_KEYS = {"password", "token", "secret", "image_base64"}


def _sanitize_args(argv: list[str]) -> dict:
    """Build a sanitized args dict from argv for logging."""
    result: dict[str, str] = {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("--"):
            key = arg.lstrip("-").replace("-", "_")
            if key in _SENSITIVE_KEYS:
                result[key] = "***"
                i += 2
                continue
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                val = argv[i + 1]
                if key == "text" and len(val) > 100:
                    val = val[:100] + "..."
                result[key] = val
                i += 2
            else:
                result[key] = "true"
                i += 1
        else:
            result.setdefault("_positional", arg)
            i += 1
    return result


def _write_invocation_log() -> None:
    """atexit handler: append a JSONL line to the session invocation log."""
    try:
        from appium_cli.utils.paths import read_current_session, session_log_path

        sid = read_current_session()
        if not sid:
            return

        log_path = session_log_path(sid)
        duration_ms = int((time.time() - _log_start_time) * 1000)

        # Derive command name from argv
        cmd_parts: list[str] = []
        args_start = 0
        for i, arg in enumerate(_log_argv):
            if arg.startswith("--"):
                args_start = i
                break
            cmd_parts.append(arg)
            args_start = i + 1
        cmd = " ".join(cmd_parts) or "unknown"
        remaining_argv = _log_argv[args_start:]

        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
            "cmd": cmd,
            "args": _sanitize_args(remaining_argv),
            "status": "OK" if _log_exit_code == 0 else "FAILED",
            "exit_code": _log_exit_code,
            "duration_ms": duration_ms,
        }

        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Never let logging crash the CLI


app = typer.Typer(
    help="CLI for Appium-based mobile automation by LLM agents.",
    no_args_is_help=True,
)
app.command(name="doctor")(doctor)
app.command(name="devices")(devices)
app.command(name="snapshot")(snapshot)
app.command(name="snapshot_show")(snapshot_show)
app.command(name="snapshot_actionable_tree")(snapshot_actionable_tree)
app.command(name="snapshot_search")(snapshot_search)
app.command(name="web_refs")(web_refs)
app.command(name="generate_locator")(generate_locator)
app.command(name="web_query")(web_query)
app.command(name="web_text")(web_text)
app.command(name="web_form_url")(web_form_url)
app.command(name="describe")(describe)
app.command(name="find_by_text")(find_by_text)
app.command(name="screenshot")(screenshot)
app.command(name="get_page_source")(get_page_source)
app.command(name="get_device_info")(get_device_info)
app.command(name="tap")(tap)
app.command(name="click")(click)
app.command(name="type_text")(type_text)
app.command(name="fill")(fill)
app.command(name="select")(select)
app.command(name="scroll")(scroll)
app.command(name="scroll_up")(scroll_up)
app.command(name="scroll_down")(scroll_down)
app.command(name="scroll_left")(scroll_left)
app.command(name="scroll_right")(scroll_right)
app.command(name="swipe")(swipe)
app.command(name="swipe_up")(swipe_up)
app.command(name="swipe_down")(swipe_down)
app.command(name="swipe_left")(swipe_left)
app.command(name="swipe_right")(swipe_right)
app.command(name="press_key")(press_key)
app.command(name="wait")(wait)
app.command(name="long_press")(long_press)
app.command(name="double_tap")(double_tap)
app.command(name="drag")(drag)
app.command(name="fling")(fling)
app.command(name="fling_up")(fling_up)
app.command(name="fling_down")(fling_down)
app.command(name="fling_left")(fling_left)
app.command(name="fling_right")(fling_right)
app.command(name="pinch_open")(pinch_open)
app.command(name="pinch_close")(pinch_close)
app.command(name="list_containers")(list_containers)
app.command(name="find_container")(find_container)
app.command(name="within_container")(within_container)
app.command(name="assert_visible")(assert_visible)
app.command(name="get_current_app")(get_current_app)
app.command(name="activate_app")(activate_app)
app.command(name="terminate_app")(terminate_app)
app.command(name="list_apps")(list_apps)
app.command(name="restart_app")(restart_app)
app.command(name="is_locked")(is_locked)
app.command(name="get_orientation")(get_orientation)
app.command(name="set_orientation")(set_orientation)
app.command(name="find_element")(find_element)
app.command(name="click_element")(click_element)
app.command(name="get_text")(get_text)
app.command(name="press_keycode")(press_keycode)
app.command(name="send_keys")(send_keys)
app.command(name="wait_short_loading")(wait_short_loading)
app.command(name="scroll_element")(scroll_element)
app.command(name="scroll_to_element")(scroll_to_element)
app.command(name="list_contexts")(list_contexts)
app.command(name="get_context")(get_context)
app.command(name="switch_context")(switch_context)
app.command(name="native_switch")(native_switch)
app.command(name="webview_switch")(webview_switch)
app.command(name="webview_status")(webview_status)
app.command(name="web_snapshot")(web_snapshot)
app.command(name="webview_url")(webview_url)
app.command(name="webview_title")(webview_title)
app.command(name="goto")(goto)
app.command(name="go_back")(go_back)
app.command(name="go_forward")(go_forward)
app.command(name="reload")(reload_page)
app.command(name="web_eval")(web_eval)
app.command(name="dialog_accept")(dialog_accept)
app.command(name="dialog_dismiss")(dialog_dismiss)
app.command(name="dialog_text")(dialog_text)
app.command(name="select_option")(select_option)
app.command(name="set_date")(set_date)
app.command(name="file_upload")(file_upload)
app.command(name="wait_for")(wait_for)
app.command(name="console_messages")(console_messages)
app.command(name="tabs")(tabs_cmd)
app.command(name="network_requests")(network_requests_cmd)
app.command(name="install")(install)
app.add_typer(server_app, name="server")
app.add_typer(session_app, name="session")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the appium-cli version and exit.",
        ),
    ] = False,
    raw: Annotated[
        bool,
        typer.Option(
            "--raw",
            help="Prefer bare tool output and pass raw mode to daemon-backed commands.",
        ),
    ] = False,
) -> None:
    """Run appium-cli."""
    global _log_start_time, _log_argv
    _log_start_time = time.time()
    _log_argv = sys.argv[1:]
    set_raw_output(raw)


def main() -> None:
    global _log_argv, _log_exit_code, _log_start_time
    atexit.register(_write_invocation_log)
    _log_start_time = time.time()
    _log_argv = sys.argv[1:]
    try:
        suggestion = suggest_usage(_log_argv)
        if suggestion is not None:
            typer.echo(format_suggestion(suggestion), err=True)
            raise SystemExit(exit_codes.USAGE_ERROR)
        app()
    except SystemExit as exc:
        _log_exit_code = exc.code if isinstance(exc.code, int) else 1
        raise


if __name__ == "__main__":
    main()
