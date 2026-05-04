"""Snapshot-ref based actions and gestures.

All ref-based actions resolve elements through RefResolver with
multi-strategy lookup and bounds verification.
"""

from __future__ import annotations

import time
from typing import Any

from appium_cli.core.ref_resolver import ElementNotFoundError, _CoordinateElement
from appium_cli.daemon import state
from appium_cli.tools.observation import refresh_snapshot


_SCROLL_DIRECTION_REVERSE = {"up": "down", "down": "up", "left": "right", "right": "left"}
_KEYCODE_MAP = {"back": 4, "home": 3, "enter": 66, "delete": 67, "tab": 61}


def _require_driver():
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    return state.driver


def _failed(message: str) -> str:
    return f"FAILED: {message}"


def _ok_with_snapshot() -> str:
    try:
        return "OK\n" + refresh_snapshot()
    except Exception as exc:
        return f"OK\nWARNING: snapshot refresh failed: {exc}"


def _resolve_element(ref: str) -> Any:
    """Resolve ref to WebElement via RefResolver with bounds verification."""
    driver = _require_driver()
    return state.ref_resolver.resolve(ref, driver)


def _gesture_target(ref: str) -> dict[str, Any]:
    """Resolve ref to gesture parameters (elementId or x,y coordinates)."""
    element = _resolve_element(ref)
    if isinstance(element, _CoordinateElement):
        return {"x": element.x, "y": element.y}
    return {"elementId": element.id}


def _screen_rect() -> dict[str, int]:
    size = _require_driver().get_window_size()
    return {"left": 0, "top": 0, "width": int(size["width"]), "height": int(size["height"])}


def tap(ref: str) -> str:
    try:
        _require_driver().execute_script("mobile: clickGesture", _gesture_target(ref))
        time.sleep(0.5)
        return _ok_with_snapshot()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except Exception as exc:
        return _failed(str(exc))


def type_text(ref: str, text: str, submit: bool = False) -> str:
    try:
        element = _resolve_element(ref)
        if isinstance(element, _CoordinateElement):
            return _failed(f"ref '{ref}' resolved to coordinates only; type_text requires a real element")
        element.click()
        try:
            element.clear()
        except Exception:
            pass
        element.send_keys(text)
        if submit:
            _require_driver().press_keycode(66)
        time.sleep(0.5)
        return _ok_with_snapshot()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except Exception as exc:
        return _failed(str(exc))


def scroll(direction: str, ref: str = "", percent: float = 0.8) -> str:
    try:
        if direction not in _SCROLL_DIRECTION_REVERSE:
            return _failed("direction must be one of: up, down, left, right")
        params: dict[str, Any] = {"direction": _SCROLL_DIRECTION_REVERSE[direction], "percent": percent}
        if ref:
            params.update(_gesture_target(ref))
        else:
            params.update(_screen_rect())
        can_scroll_more = _require_driver().execute_script("mobile: scrollGesture", params)
        time.sleep(0.5)
        return _ok_with_snapshot() + f"\ncan_scroll_more: {can_scroll_more}"
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except Exception as exc:
        return _failed(str(exc))


def swipe(direction: str, ref: str = "", percent: float = 0.8) -> str:
    try:
        if direction not in _SCROLL_DIRECTION_REVERSE:
            return _failed("direction must be one of: up, down, left, right")
        params: dict[str, Any] = {"direction": direction, "percent": min(percent, 1.0)}
        if ref:
            params.update(_gesture_target(ref))
        else:
            params.update(_screen_rect())
        _require_driver().execute_script("mobile: swipeGesture", params)
        time.sleep(0.5)
        return _ok_with_snapshot()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except Exception as exc:
        return _failed(str(exc))


def press_key(key: str) -> str:
    if key not in _KEYCODE_MAP:
        return _failed(f"unknown key '{key}'. Use one of: {', '.join(sorted(_KEYCODE_MAP))}")
    try:
        _require_driver().press_keycode(_KEYCODE_MAP[key])
        time.sleep(0.5)
        return _ok_with_snapshot()
    except Exception as exc:
        return _failed(str(exc))


def wait(seconds: float = 1.0) -> str:
    time.sleep(seconds)
    return _ok_with_snapshot()


def long_press(ref: str, duration: int = 500) -> str:
    try:
        params = _gesture_target(ref)
        params["duration"] = duration
        _require_driver().execute_script("mobile: longClickGesture", params)
        time.sleep(0.5)
        return _ok_with_snapshot()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except Exception as exc:
        return _failed(str(exc))


def double_tap(ref: str) -> str:
    try:
        _require_driver().execute_script("mobile: doubleClickGesture", _gesture_target(ref))
        time.sleep(0.5)
        return _ok_with_snapshot()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except Exception as exc:
        return _failed(str(exc))


def drag(ref: str, end_x: int, end_y: int, speed: int | None = None) -> str:
    try:
        params = _gesture_target(ref)
        params.update({"endX": end_x, "endY": end_y})
        if speed is not None:
            params["speed"] = speed
        _require_driver().execute_script("mobile: dragGesture", params)
        time.sleep(0.5)
        return _ok_with_snapshot()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except Exception as exc:
        return _failed(str(exc))


def fling(direction: str, ref: str = "", speed: int | None = None) -> str:
    try:
        params: dict[str, Any] = {"direction": direction}
        if speed is not None:
            params["speed"] = speed
        if ref:
            params.update(_gesture_target(ref))
        else:
            params.update(_screen_rect())
        can_scroll_more = _require_driver().execute_script("mobile: flingGesture", params)
        time.sleep(0.5)
        return _ok_with_snapshot() + f"\ncan_scroll_more: {can_scroll_more}"
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except Exception as exc:
        return _failed(str(exc))


def pinch_open(ref: str, percent: float = 0.5, speed: int | None = None) -> str:
    return _pinch("mobile: pinchOpenGesture", ref, percent, speed)


def pinch_close(ref: str, percent: float = 0.5, speed: int | None = None) -> str:
    return _pinch("mobile: pinchCloseGesture", ref, percent, speed)


def _pinch(script: str, ref: str, percent: float, speed: int | None) -> str:
    try:
        params = _gesture_target(ref)
        params["percent"] = percent
        if speed is not None:
            params["speed"] = speed
        _require_driver().execute_script(script, params)
        time.sleep(0.5)
        return _ok_with_snapshot()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except Exception as exc:
        return _failed(str(exc))
