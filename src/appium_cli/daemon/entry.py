"""Daemon process entry point."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from appium import webdriver
from appium.options.android import UiAutomator2Options
from selenium.common.exceptions import WebDriverException

from appium_cli.daemon import state
from appium_cli.daemon.server import serve
from appium_cli.tools import actions
from appium_cli.tools import app_management, container
from appium_cli.tools import device_info as device_info_tools
from appium_cli.tools import interaction
from appium_cli.tools.device_info import get_device_info
from appium_cli.tools.observation import describe, find_by_text, get_page_source, screenshot, snapshot
from appium_cli.tools.session import get_driver_status


def _create_driver(server_url: str, udid: str | None):
    options = UiAutomator2Options()
    options.set_capability("platformName", "Android")
    options.set_capability("appium:automationName", "UiAutomator2")
    if udid:
        options.set_capability("appium:udid", udid)
        options.set_capability("appium:deviceName", udid)
    return webdriver.Remote(server_url, options=options)


def _probe_shell(driver) -> bool:
    try:
        driver.execute_script("mobile: shell", {"command": "echo", "args": ["appium-cli"]})
        return True
    except WebDriverException:
        return False


def _handler(request: dict[str, Any]) -> dict[str, Any]:
    tool = request.get("tool")
    if tool == "ping":
        return {"text": "pong", "data": state.session_metadata}
    if tool == "get_driver_status":
        return {"text": get_driver_status(), "data": state.session_metadata}
    if tool == "get_device_info":
        return {"text": get_device_info(), "data": {}}
    args = request.get("args") or {}
    if tool == "snapshot":
        return {"text": snapshot(**args), "data": {}}
    if tool == "describe":
        return {"text": describe(**args), "data": {}}
    if tool == "find_by_text":
        return {"text": find_by_text(**args), "data": {}}
    if tool == "screenshot":
        return {"text": screenshot(**args), "data": {}}
    if tool == "get_page_source":
        return {"text": get_page_source(), "data": {}}
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
    parser.add_argument("--app-dir", help="Absolute path to .appium-cli directory parent")
    args = parser.parse_args()

    # Ensure get_app_dir() resolves to the same directory as the CLI process
    if args.app_dir:
        app_dir_parent = str(Path(args.app_dir).parent)
        os.chdir(app_dir_parent)

    driver = None
    try:
        driver = _create_driver(args.server_url, args.udid)
        shell_capable = _probe_shell(driver)
        state.driver = driver
        state.session_metadata = {
            "server_url": args.server_url,
            "udid": args.udid,
            "session_id": driver.session_id,
            "shell_capable": shell_capable,
            "adb_fallback": args.adb_fallback,
        }
        serve(handler=_handler)
    finally:
        if driver is not None:
            driver.quit()
        state.reset()


if __name__ == "__main__":
    main()
