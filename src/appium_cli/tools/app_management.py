"""App management tools."""

from __future__ import annotations

import time

from appium_cli.daemon import state
from appium_cli.tools.actions import _ok_with_snapshot
from appium_cli.tools.device_info import _shell


def _require_driver():
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    return state.driver


def get_current_app() -> str:
    driver = _require_driver()
    return f"Current app package: {driver.current_package}\nCurrent activity: {driver.current_activity}"


def activate_app(app_id: str) -> str:
    driver = _require_driver()
    driver.activate_app(app_id)
    time.sleep(1)
    return f"Successfully activated app: {app_id}\n{_ok_with_snapshot()}"


def terminate_app(app_id: str) -> str:
    driver = _require_driver()
    result = driver.terminate_app(app_id)
    time.sleep(0.5)
    return f"Successfully terminated app: {app_id} (result: {result})\n{_ok_with_snapshot()}"


def list_apps() -> str:
    output = _shell("pm", "list", "packages")
    packages = [line.removeprefix("package:") for line in output.splitlines() if line.strip()]
    lines = [f"Installed apps ({len(packages)}):"]
    lines.extend(packages)
    return "\n".join(lines)


def restart_app(app_id: str, wait_seconds: int = 3) -> str:
    driver = _require_driver()
    driver.terminate_app(app_id)
    time.sleep(wait_seconds)
    driver.activate_app(app_id)
    time.sleep(1)
    return f"Successfully restarted app: {app_id} (waited {wait_seconds}s between terminate and activate)\n{_ok_with_snapshot()}"
