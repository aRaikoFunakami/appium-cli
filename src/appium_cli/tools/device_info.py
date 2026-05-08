"""Device information tools."""

from __future__ import annotations

import subprocess
from urllib.parse import urlparse

from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

from appium_cli.daemon import state
from appium_cli.utils import exit_codes
from appium_cli.utils.errors import AppiumCliError


def _is_local_server() -> bool:
    server_url = state.session_metadata.get("server_url", "")
    host = urlparse(server_url).hostname
    return host in {"127.0.0.1", "localhost", "::1"}


def _adb_shell(command: str, args: list[str]) -> str:
    udid = state.session_metadata.get("udid")
    if not udid:
        raise AppiumCliError("ADB fallback requires a known device udid", exit_codes.FEATURE_NOT_ENABLED)
    result = subprocess.run(
        ["adb", "-s", udid, "shell", command, *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "adb shell failed"
        raise AppiumCliError(message, exit_codes.GENERAL_ERROR)
    return result.stdout.strip()


def _shell(command: str, *args: str) -> str:
    if state.driver is None:
        raise ValueError("Driver is not initialized")

    if state.session_metadata.get("shell_capable") is False:
        if state.session_metadata.get("adb_fallback") and _is_local_server():
            return _adb_shell(command, list(args))
        raise AppiumCliError(
            "mobile: shell is not enabled for this Appium session",
            exit_codes.FEATURE_NOT_ENABLED,
        )

    try:
        result = state.driver.execute_script(
            "mobile: shell",
            {"command": command, "args": list(args)},
        )
    except WebDriverException:
        if state.session_metadata.get("adb_fallback") and _is_local_server():
            return _adb_shell(command, list(args))
        raise AppiumCliError(
            "mobile: shell is not enabled for this Appium session",
            exit_codes.FEATURE_NOT_ENABLED,
        )

    if isinstance(result, dict):
        return result.get("stdout", "").strip() if "stdout" in result else str(result)
    return str(result).strip()


def get_device_info() -> str:
    """Get comprehensive device information in smartestiroid-compatible format."""

    if state.driver is None:
        raise ValueError("Driver is not initialized")

    try:
        info = {
            "model": _shell("getprop", "ro.product.model"),
            "brand": _shell("getprop", "ro.product.brand"),
            "device_name": _shell("getprop", "ro.product.name"),
            "android_version": _shell("getprop", "ro.build.version.release"),
            "sdk": _shell("getprop", "ro.build.version.sdk"),
            "display_resolution": _shell("wm", "size"),
            "density": _shell("wm", "density"),
            "current_package": state.driver.current_package,
            "current_activity": state.driver.current_activity,
            "orientation": state.driver.orientation,
            "is_locked": state.driver.is_locked(),
        }
        output = "Device Information:\n"
        output += f"Model: {info['model']}\n"
        output += f"Brand: {info['brand']}\n"
        output += f"Device Name: {info['device_name']}\n"
        output += f"Android Version: {info['android_version']}\n"
        output += f"SDK: {info['sdk']}\n"
        output += f"Display: {info['display_resolution']}\n"
        output += f"Density: {info['density']}\n"
        output += f"Current Package: {info['current_package']}\n"
        output += f"Current Activity: {info['current_activity']}\n"
        output += f"Orientation: {info['orientation']}\n"
        output += f"Is Locked: {info['is_locked']}\n"
        return output
    except InvalidSessionIdException:
        raise


def is_locked() -> str:
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    locked = state.driver.is_locked()
    return f"Device is {'locked' if locked else 'unlocked'}"


def get_orientation() -> str:
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    return f"Current orientation: {state.driver.orientation}"


def set_orientation(orientation: str) -> str:
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    normalized = orientation.upper()
    if normalized not in {"PORTRAIT", "LANDSCAPE"}:
        raise ValueError("Invalid orientation. Use 'PORTRAIT' or 'LANDSCAPE'")
    state.driver.orientation = normalized

    return f"Successfully set orientation to: {orientation}"
