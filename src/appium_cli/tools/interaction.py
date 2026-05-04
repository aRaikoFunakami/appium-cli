"""Legacy locator-based interaction and navigation tools."""

from __future__ import annotations

import time
from typing import Any

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import InvalidArgumentException, InvalidSelectorException, NoSuchElementException

from appium_cli.daemon import state
from appium_cli.tools.actions import _ok_with_snapshot


def _require_driver():
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    return state.driver


def _strategy(by: str):
    mapping = {
        "xpath": AppiumBy.XPATH,
        "id": AppiumBy.ID,
        "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
        "accessibility id": AppiumBy.ACCESSIBILITY_ID,
        "class_name": AppiumBy.CLASS_NAME,
        "class name": AppiumBy.CLASS_NAME,
        "name": AppiumBy.NAME,
    }
    return mapping.get(by, by)


def _find_element_internal(by: str, value: str) -> tuple[Any | None, str | None]:
    try:
        element = _require_driver().find_element(by=_strategy(by), value=value)
        return element, None
    except (InvalidArgumentException, InvalidSelectorException) as exc:
        return None, f"❌ Invalid locator: by='{by}' is not a valid locator strategy. Use 'xpath', 'id', 'accessibility_id', 'class_name', etc. Error: {exc.msg}"
    except NoSuchElementException:
        return None, f"❌ Element not found: No element found with by='{by}' and value='{value}'. IMPORTANT: Before trying different selectors, use get_page_source() to see the actual screen structure and find the correct element identifiers."


def find_element(by: str, value: str) -> str:
    element, error = _find_element_internal(by, value)
    if error:
        return error
    return f"Successfully found element by {by} with value {value}"


def click_element(by: str, value: str) -> str:
    element, error = _find_element_internal(by, value)
    if error:
        return error
    element.click()
    time.sleep(1)
    return f"Successfully clicked element by {by} with value {value}\n{_ok_with_snapshot()}"


def get_text(by: str, value: str) -> str:
    element, error = _find_element_internal(by, value)
    if error:
        return error
    return f"Element text: {element.text}"


def press_keycode(keycode: int) -> str:
    _require_driver().press_keycode(keycode)
    time.sleep(1)
    return f"Successfully pressed keycode {keycode}\n{_ok_with_snapshot()}"


def double_tap(by: str, value: str) -> str:
    element, error = _find_element_internal(by, value)
    if error:
        return error
    element.click()
    time.sleep(0.1)
    element.click()
    time.sleep(1)
    return f"Successfully double tapped element by {by} with value {value}\n{_ok_with_snapshot()}"


def send_keys(by: str, value: str, text: str) -> str:
    element, error = _find_element_internal(by, value)
    if error:
        return error
    element.click()
    element.send_keys(text)
    time.sleep(1)
    return f"Successfully sent keys '{text}' to element\n{_ok_with_snapshot()}"


def wait_short_loading(seconds: str = "5") -> str:
    _require_driver()
    try:
        wait_seconds = int(seconds)
    except ValueError:
        wait_seconds = 5
    time.sleep(wait_seconds)
    return f"Waited {wait_seconds} seconds for loading"


def _window_swipe(direction: str) -> None:
    driver = _require_driver()
    size = driver.get_window_size()
    width = int(size["width"])
    height = int(size["height"])
    mid_x = width // 2
    mid_y = height // 2
    if direction == "up":
        driver.swipe(mid_x, int(height * 0.75), mid_x, int(height * 0.25), 700)
    elif direction == "down":
        driver.swipe(mid_x, int(height * 0.25), mid_x, int(height * 0.75), 700)
    elif direction == "left":
        driver.swipe(int(width * 0.75), mid_y, int(width * 0.25), mid_y, 700)
    elif direction == "right":
        driver.swipe(int(width * 0.25), mid_y, int(width * 0.75), mid_y, 700)
    else:
        raise ValueError("direction must be one of: up, down, left, right")


def scroll_element(by: str, value: str, direction: str = "up") -> str:
    element, error = _find_element_internal(by, value)
    if error:
        return error
    rect = element.rect
    x = int(rect["x"] + rect["width"] / 2)
    top = int(rect["y"] + rect["height"] * 0.25)
    bottom = int(rect["y"] + rect["height"] * 0.75)
    left = int(rect["x"] + rect["width"] * 0.25)
    right = int(rect["x"] + rect["width"] * 0.75)
    driver = _require_driver()
    if direction == "up":
        driver.swipe(x, bottom, x, top, 700)
    elif direction == "down":
        driver.swipe(x, top, x, bottom, 700)
    elif direction == "left":
        driver.swipe(right, int(rect["y"] + rect["height"] / 2), left, int(rect["y"] + rect["height"] / 2), 700)
    elif direction == "right":
        driver.swipe(left, int(rect["y"] + rect["height"] / 2), right, int(rect["y"] + rect["height"] / 2), 700)
    else:
        return "❌ Invalid direction. Use 'up', 'down', 'left', or 'right'."
    time.sleep(1)
    return f"Successfully scrolled element by {by} with value {value} in {direction} direction\n{_ok_with_snapshot()}"


def scroll_to_element(by: str, value: str, scrollable_by: str = "xpath", scrollable_value: str = "//*[@scrollable='true']") -> str:
    for attempt in range(10):
        element, _ = _find_element_internal(by, value)
        if element is not None:
            return f"Element found after {attempt} scroll(s): by {by} with value {value}"
        scrollable, _ = _find_element_internal(scrollable_by, scrollable_value)
        if scrollable is not None:
            scroll_element(scrollable_by, scrollable_value, "up")
        else:
            _window_swipe("up")
        time.sleep(0.5)
    return f"Element not found after scrolling: by {by} with value {value}"
