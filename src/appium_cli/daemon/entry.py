"""Daemon process entry point."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from appium import webdriver
from appium.options.android import UiAutomator2Options
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

from appium_cli.daemon import state
from appium_cli.daemon.server import serve
from appium_cli.tools import actions
from appium_cli.tools import app_management, container
from appium_cli.tools import contexts
from appium_cli.tools import device_info as device_info_tools
from appium_cli.tools import interaction
from appium_cli.tools import web_dialogs
from appium_cli.tools import web_navigation
from appium_cli.tools.device_info import get_device_info
from appium_cli.tools.observation import (
    describe,
    find_by_text,
    generate_locator,
    get_page_source,
    refresh_snapshot,
    screenshot,
    snapshot_refs,
    snapshot_search,
    snapshot_show,
    web_query,
    web_text,
    web_form_url,
    webview_title,
    webview_url,
    console_messages,
    network_requests,
)
from appium_cli.tools.session import format_driver_status, is_driver_alive


def _create_driver(server_url: str, udid: str | None, *, enable_network_log: bool = False):
    options = UiAutomator2Options()
    options.set_capability("platformName", "Android")
    options.set_capability("appium:automationName", "UiAutomator2")
    if udid:
        options.set_capability("appium:udid", udid)
        options.set_capability("appium:deviceName", udid)
    # Optional: route adb traffic through a remote adb server (e.g. when running
    # inside a container while the device is attached to the host). When set,
    # these are forwarded to the Appium server as W3C capabilities so that
    # appium-uiautomator2-driver uses the remote adb server instead of localhost.
    remote_adb_host = os.environ.get("APPIUM_REMOTE_ADB_HOST")
    remote_adb_port = os.environ.get("APPIUM_REMOTE_ADB_PORT")
    if remote_adb_host:
        options.set_capability("appium:remoteAdbHost", remote_adb_host)
    if remote_adb_port:
        try:
            options.set_capability("appium:adbPort", int(remote_adb_port))
        except ValueError:
            pass
    if enable_network_log:
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    adb_exec_timeout = int(os.environ.get("APPIUM_ADB_EXEC_TIMEOUT", "60000"))
    options.set_capability("appium:adbExecTimeout", adb_exec_timeout)
    return webdriver.Remote(server_url, options=options)


def _probe_shell(driver) -> bool:
    try:
        driver.execute_script("mobile: shell", {"command": "echo", "args": ["appium-cli"]})
        return True
    except WebDriverException:
        return False


def _handler(request: dict[str, Any]) -> dict[str, Any]:
    return _handle_request(request)


def _handle_request(request: dict[str, Any]) -> dict[str, Any]:
    tool = request.get("tool")
    if tool == "ping":
        return {"text": "pong", "data": state.session_metadata}
    if tool == "get_driver_status":
        ready = is_driver_alive()
        return {
            "text": format_driver_status(ready),
            "data": {**state.session_metadata, "initialized": state.driver is not None, "ready": ready},
        }
    if tool == "get_device_info":
        return {"text": get_device_info(), "data": {}}
    args = request.get("args") or {}
    if tool == "snapshot":
        result = refresh_snapshot(**args, raw=bool(request.get("raw")))
        return {"text": result.text, "data": result.data}
    if tool == "snapshot_show":
        return {"text": snapshot_show(**args, raw=bool(request.get("raw"))), "data": {}}
    if tool == "snapshot_search":
        return {"text": snapshot_search(**args, raw=bool(request.get("raw"))), "data": {}}
    if tool == "snapshot_refs":
        return {"text": snapshot_refs(**args, raw=bool(request.get("raw"))), "data": {}}
    if tool == "generate_locator":
        return {"text": generate_locator(**args, raw=bool(request.get("raw"))), "data": {}}
    if tool == "web_query":
        return {"text": web_query(**args, raw=bool(request.get("raw"))), "data": {}}
    if tool == "web_text":
        return {"text": web_text(**args, raw=bool(request.get("raw"))), "data": {}}
    if tool == "web_form_url":
        return {"text": web_form_url(**args, raw=bool(request.get("raw"))), "data": {}}
    if tool == "web_eval":
        no_lint = bool(args.pop("no_lint", False))
        script = args.get("script", "")
        warnings = [] if no_lint else actions.lint_web_eval(script)
        text = actions.web_eval(**args)
        data = {"warnings": warnings} if warnings else {}
        return {"text": text, "data": data}
    if tool == "describe":
        return {"text": describe(**args), "data": {}}
    if tool == "find_by_text":
        return {"text": find_by_text(**args), "data": {}}
    if tool == "screenshot":
        return {"text": screenshot(**args), "data": {}}
    if tool == "get_page_source":
        return {"text": get_page_source(**args), "data": {}}
    # Context commands
    if tool == "list_contexts":
        return {"text": contexts.list_contexts(), "data": {}}
    if tool == "get_context":
        return {"text": contexts.get_context(), "data": {}}
    if tool == "switch_context":
        return {"text": contexts.switch_context(**args), "data": {}}
    if tool == "native_switch":
        return {"text": contexts.native_switch(), "data": {}}
    if tool == "webview_switch":
        return {"text": contexts.webview_switch(**args), "data": {}}
    if tool == "webview_status":
        return {"text": contexts.webview_status(), "data": {}}
    # WebView observation
    if tool == "web_snapshot":
        result = refresh_snapshot(**args, context="webview", raw=bool(request.get("raw")))
        return {"text": result.text, "data": result.data}
    if tool == "webview_url":
        return {"text": webview_url(), "data": {}}
    if tool == "webview_title":
        return {"text": webview_title(), "data": {}}
    # Web navigation
    if tool == "goto":
        return {"text": web_navigation.goto(**args), "data": {}}
    if tool == "go_back":
        return {"text": web_navigation.go_back(), "data": {}}
    if tool == "go_forward":
        return {"text": web_navigation.go_forward(), "data": {}}
    if tool == "reload":
        return {"text": web_navigation.reload(), "data": {}}
    # Web dialogs
    if tool == "dialog_accept":
        return {"text": web_dialogs.dialog_accept(**args), "data": {}}
    if tool == "dialog_dismiss":
        return {"text": web_dialogs.dialog_dismiss(), "data": {}}
    if tool == "dialog_text":
        return {"text": web_dialogs.dialog_text(), "data": {}}
    if tool == "console_messages":
        return {"text": console_messages(**args), "data": {}}
    if tool == "network_requests":
        return {"text": network_requests(**args), "data": {}}
    if tool == "tabs":
        return {"text": web_navigation.tabs(**args), "data": {}}
    if tool == "double_tap" and "by" in args:
        return {"text": interaction.double_tap(**args), "data": {}}
    if hasattr(actions, str(tool)):
        return {"text": getattr(actions, str(tool))(**args), "data": {}}
    if hasattr(container, str(tool)):
        return {"text": getattr(container, str(tool))(**args), "data": {}}
    if hasattr(app_management, str(tool)):
        return {"text": getattr(app_management, str(tool))(**args), "data": {}}
    if hasattr(device_info_tools, str(tool)):
        return {"text": getattr(device_info_tools, str(tool))(**args), "data": {}}
    if hasattr(interaction, str(tool)):
        return {"text": getattr(interaction, str(tool))(**args), "data": {}}
    raise KeyError(f"Unknown tool: {tool}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--udid")
    parser.add_argument("--adb-fallback", action="store_true")
    parser.add_argument("--enable-network-log", action="store_true")
    parser.add_argument("--app-dir", help="Absolute path to .appium-cli directory parent")
    args = parser.parse_args()

    # Ensure get_app_dir() resolves to the same directory as the CLI process
    if args.app_dir:
        app_dir_parent = str(Path(args.app_dir).parent)
        os.chdir(app_dir_parent)

    driver = None
    try:
        driver = _create_driver(args.server_url, args.udid, enable_network_log=args.enable_network_log)
        shell_capable = _probe_shell(driver)
        state.driver = driver
        state.session_metadata = {
            "server_url": args.server_url,
            "udid": args.udid,
            "session_id": driver.session_id,
            "shell_capable": shell_capable,
            "adb_fallback": args.adb_fallback,
            "network_log_enabled": args.enable_network_log,
        }
        serve(handler=_handler)
    finally:
        if driver is not None:
            # Switch back to native context before quitting.  When a WebView
            # context was active (e.g. Chrome), this gives Appium an explicit
            # signal to shut down ChromeDriver cleanly before the session is
            # deleted.  Without it, a WebView that failed mid-switch (ADB
            # timeout) can leave ChromeDriver in a zombie state, causing the
            # subsequent DELETE /session to crash the host Appium process.
            try:
                driver.switch_to.context("NATIVE_APP")
            except Exception:
                pass
            try:
                driver.quit()
            except (InvalidSessionIdException, WebDriverException):
                pass
        state.reset()


if __name__ == "__main__":
    main()
