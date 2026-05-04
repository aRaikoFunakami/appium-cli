"""Session status tool."""

from __future__ import annotations

from appium_cli.daemon import state


def get_driver_status() -> str:
    if state.driver:
        return "Driver is initialized and ready"
    return "Driver is not initialized"
