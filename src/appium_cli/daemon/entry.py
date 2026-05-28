"""Daemon process entry point."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from appium import webdriver
from appium.options.android import UiAutomator2Options
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

from appium_cli.core.ref_resolver import ElementNotFoundError, StaleSnapshotError
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
    web_refs,
    snapshot_search,
    snapshot_show,
    web_query,
    web_text,
    web_form_url,
    webview_title,
    webview_url,
    console_messages,
    network_requests,
    snapshot_actionable_tree,
)
from appium_cli.tools.session import format_driver_status, is_driver_alive
from appium_cli.utils.errors import AppiumCliError


_AUTO_REFRESH_ACTION_TOOLS = frozenset({
    "tap",
    "click",
    "type_text",
    "fill",
    "select",
    "select_option",
    "set_date",
    "scroll",
    "swipe",
    "fling",
    "drag",
    "long_press",
    "double_tap",
    "pinch_open",
    "pinch_close",
    "file_upload",
    "wait_for",
    "web_eval",
})


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
    args = request.get("args") or {}
    if _is_auto_refresh_eligible(str(tool), args):
        return _invoke_with_auto_refresh(str(tool), args, request)
    return _invoke_tool(str(tool), args, request)


def _invoke_tool(tool: str, args: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
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
    if tool == "snapshot":
        result = refresh_snapshot(**args, raw=bool(request.get("raw")))
        return {"text": result.text, "data": result.data}
    if tool == "snapshot_show":
        return {"text": snapshot_show(**args, raw=bool(request.get("raw"))), "data": {}}
    if tool == "snapshot_actionable_tree":
        return {"text": snapshot_actionable_tree(), "data": {}}
    if tool == "snapshot_search":
        return {"text": snapshot_search(**args, raw=bool(request.get("raw"))), "data": {}}
    if tool == "web_refs":
        return {"text": web_refs(**args, raw=bool(request.get("raw"))), "data": {}}
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


def _is_auto_refresh_eligible(tool: str, args: dict[str, Any]) -> bool:
    if tool not in _AUTO_REFRESH_ACTION_TOOLS:
        return False
    return hasattr(actions, tool) and _ref_arg(args) != ""


def _ref_arg(args: dict[str, Any]) -> str:
    for key in ("ref", "target", "container_ref"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _stale_error_from(exc: BaseException) -> StaleSnapshotError | None:
    if isinstance(exc, StaleSnapshotError):
        return exc
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, StaleSnapshotError):
        return cause
    return None


def _element_error_from(exc: BaseException) -> ElementNotFoundError | None:
    if isinstance(exc, ElementNotFoundError):
        return exc
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, ElementNotFoundError):
        return cause
    return None


def _refresh_context_for_stale_ref(args: dict[str, Any], stale: StaleSnapshotError) -> str:
    if stale.context:
        context = stale.context
    else:
        ref = _ref_arg(args)
        entry = state.ref_resolver.get_entry(ref) if ref else None
        if entry is None:
            raise stale
        context = entry.context
    return context if contexts.is_web_context(context) else "native"


def _snapshot_metadata(snapshot_result: Any) -> dict[str, Any]:
    return {
        "text": snapshot_result.text,
        "data": snapshot_result.data,
    }


def _with_auto_refresh_success(
    result: dict[str, Any],
    *,
    stale: StaleSnapshotError,
    snapshot_result: Any,
) -> dict[str, Any]:
    data = dict(result.get("data") or {})
    data.update({
        "auto_refreshed": True,
        "auto_refresh_reason": str(stale),
        "action_executed": True,
        "snapshot": _snapshot_metadata(snapshot_result),
    })
    return {**result, "data": data}


def _auto_refresh_ref_missing_response(
    tool: str,
    args: dict[str, Any],
    *,
    stale: StaleSnapshotError,
    retry_error: ElementNotFoundError,
    snapshot_result: Any,
) -> dict[str, Any]:
    missing_ref = _ref_arg(args) or retry_error.ref or stale.ref
    text = (
        f"AUTO_REFRESHED_REF_MISSING: ref '{missing_ref}' is not present after refreshing "
        "the current screen. Choose a ref from the fresh snapshot."
    )
    return {
        "ok": False,
        "text": text,
        "error": text,
        "data": {
            "auto_refreshed": True,
            "auto_refresh_reason": str(stale),
            "action_executed": False,
            "tool": tool,
            "missing_ref": missing_ref,
            "retry_error": str(retry_error),
            "snapshot": _snapshot_metadata(snapshot_result),
        },
    }


def _invoke_with_auto_refresh(tool: str, args: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    try:
        return _invoke_tool(tool, args, request)
    except Exception as exc:
        stale = _stale_error_from(exc)
        if stale is None:
            raise

    refresh_context = _refresh_context_for_stale_ref(args, stale)
    snapshot_result = refresh_snapshot(scope="full", context=refresh_context, boxes=False, raw=bool(request.get("raw")))

    try:
        result = _invoke_tool(tool, args, request)
    except Exception as retry_exc:
        retry_element_error = _element_error_from(retry_exc)
        if retry_element_error is not None:
            return _auto_refresh_ref_missing_response(
                tool,
                args,
                stale=stale,
                retry_error=retry_element_error,
                snapshot_result=snapshot_result,
            )
        raise

    return _with_auto_refresh_success(result, stale=stale, snapshot_result=snapshot_result)


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
