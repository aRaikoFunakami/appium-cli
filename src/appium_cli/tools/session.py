"""Session status tool."""

from __future__ import annotations

from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

from appium_cli.daemon import state


READY_STATUS = "Driver is initialized and ready"
NOT_READY_STATUS = "Driver is not initialized"


def is_driver_alive() -> bool:
    driver = state.driver
    if driver is None:
        return False
    try:
        _ = driver.current_package
    except (InvalidSessionIdException, WebDriverException):
        return False
    return True


def format_driver_status(ready: bool) -> str:
    return READY_STATUS if ready else NOT_READY_STATUS


def get_driver_status() -> str:
    return format_driver_status(is_driver_alive())
