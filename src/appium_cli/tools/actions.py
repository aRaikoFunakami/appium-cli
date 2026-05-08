"""Snapshot-ref based actions and gestures.

All ref-based actions resolve elements through RefResolver with
multi-strategy lookup and bounds verification.

Context-aware: actions branch to native (UiAutomator2 gestures) or
web (Selenium click/send_keys/JS) depending on the ref's stored context.
"""

from __future__ import annotations

import time
from typing import Any

from appium_cli.core.ref_resolver import ElementNotFoundError, _CoordinateElement
from appium_cli.daemon import state
from appium_cli.tools.contexts import is_web_context
from appium_cli.utils.errors import AppiumCliError
from appium_cli.utils.exit_codes import FEATURE_NOT_ENABLED


_SCROLL_DIRECTION_REVERSE = {"up": "down", "down": "up", "left": "right", "right": "left"}
_KEYCODE_MAP = {"back": 4, "home": 3, "enter": 66, "delete": 67, "tab": 61}

# W3C key names for WebView press_key
_W3C_KEY_MAP: dict[str, str] = {
    "enter": "\ue006",
    "tab": "\ue004",
    "backspace": "\ue003",
    "delete": "\ue017",
    "escape": "\ue00c",
    "space": " ",
    "arrowup": "\ue013",
    "arrowdown": "\ue015",
    "arrowleft": "\ue012",
    "arrowright": "\ue014",
    "home": "\ue011",
    "end": "\ue010",
    "pageup": "\ue00e",
    "pagedown": "\ue00f",
}


def _require_driver():
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    return state.driver


def _failed(message: str) -> str:
    return f"FAILED: {message}"


def _is_web_ref(ref: str) -> bool:
    """Check if ref belongs to a web context."""
    clean = ref.strip("[]").removeprefix("ref:")
    entry = state.ref_resolver.get_entry(clean)
    if entry is None:
        return False
    return is_web_context(entry.context)


def _ref_context(ref: str) -> str:
    """Get the context of a ref, or current context."""
    clean = ref.strip("[]").removeprefix("ref:")
    entry = state.ref_resolver.get_entry(clean)
    if entry is None:
        return state.current_context
    return entry.context


def _ok(message: str = "OK") -> str:
    """Return a simple action success message — no post-action snapshot."""
    return message


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


def _require_native_context(action: str) -> None:
    """Raise FEATURE_NOT_ENABLED if the current context is web."""
    ctx = state.current_context
    if is_web_context(ctx):
        raise AppiumCliError(
            f"'{action}' gesture is not supported in WebView context ({ctx}).",
            exit_code=FEATURE_NOT_ENABLED,
        )


def tap(ref: str) -> str:
    try:
        if _is_web_ref(ref):
            element = _resolve_element(ref)
            if isinstance(element, _CoordinateElement):
                _require_driver().execute_script(
                    """
                    const x = arguments[0] - window.scrollX;
                    const y = arguments[1] - window.scrollY;
                    const el = document.elementFromPoint(x, y);
                    if (!el) {
                        throw new Error(`No element at (${arguments[0]}, ${arguments[1]})`);
                    }
                    el.click();
                    """,
                    element.x,
                    element.y,
                )
                time.sleep(0.5)
                return _ok()
            element.click()
            time.sleep(0.5)
            return _ok()
        _require_driver().execute_script("mobile: clickGesture", _gesture_target(ref))
        time.sleep(0.5)
        return _ok()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except AppiumCliError:
        raise
    except Exception as exc:
        return _failed(str(exc))


def click(ref: str) -> str:
    """Web-friendly alias for tap."""
    return tap(ref)


def type_text(ref: str, text: str, submit: bool = False, slowly: bool = False) -> str:
    try:
        element = _resolve_element(ref)
        if isinstance(element, _CoordinateElement):
            return _failed(f"ref '{ref}' resolved to coordinates only; type_text requires a real element")
        web = _is_web_ref(ref)
        if web:
            if slowly:
                # Autocomplete/React-Select: click to focus, type char-by-char
                element.click()
                for char in text:
                    element.send_keys(char)
                    time.sleep(0.08)
            else:
                element.clear()
                element.send_keys(text)
                if submit:
                    try:
                        element.submit()
                    except Exception:
                        from selenium.webdriver.common.keys import Keys
                        element.send_keys(Keys.ENTER)
        else:
            element.click()
            try:
                element.clear()
            except Exception:
                pass
            element.send_keys(text)
            if submit:
                _require_driver().press_keycode(66)
        time.sleep(0.5)
        return _ok()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except AppiumCliError:
        raise
    except Exception as exc:
        return _failed(str(exc))


def fill(ref: str, text: str, submit: bool = False, slowly: bool = False) -> str:
    """Web-friendly alias for type_text."""
    return type_text(ref, text, submit, slowly)


def select(ref: str, value: str, by: str = "value") -> str:
    """Select an option in an HTML <select> element."""
    try:
        element = _resolve_element(ref)
        if isinstance(element, _CoordinateElement):
            return _failed("select requires a real element, not coordinates")

        from selenium.webdriver.support.ui import Select
        sel = Select(element)
        if by == "value":
            sel.select_by_value(value)
        elif by == "label":
            sel.select_by_visible_text(value)
        elif by == "index":
            sel.select_by_index(int(value))
        else:
            return _failed(f"Unknown select method: '{by}'. Use value, label, or index.")

        time.sleep(0.3)
        return _ok()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except AppiumCliError:
        raise
    except Exception as exc:
        return _failed(str(exc))


def scroll(direction: str, ref: str = "", percent: float = 0.8) -> str:
    try:
        if direction not in _SCROLL_DIRECTION_REVERSE:
            return _failed("direction must be one of: up, down, left, right")

        # Web context scroll via JS
        if (ref and _is_web_ref(ref)) or (not ref and is_web_context(state.current_context)):
            return _web_scroll(direction, ref, percent)

        params: dict[str, Any] = {"direction": _SCROLL_DIRECTION_REVERSE[direction], "percent": percent}
        if ref:
            params.update(_gesture_target(ref))
        else:
            params.update(_screen_rect())
        can_scroll_more = _require_driver().execute_script("mobile: scrollGesture", params)
        time.sleep(0.5)
        ctx = _ref_context(ref) if ref else state.current_context
        return _ok(f"OK\ncan_scroll_more: {can_scroll_more}")
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except AppiumCliError:
        raise
    except Exception as exc:
        return _failed(str(exc))


def _web_scroll(direction: str, ref: str, percent: float) -> str:
    """Scroll in WebView via JavaScript."""
    driver = _require_driver()
    viewport_size = driver.get_window_size()
    distance = int(viewport_size["height"] * percent * 0.6)

    if direction == "down":
        dx, dy = 0, distance
    elif direction == "up":
        dx, dy = 0, -distance
    elif direction == "right":
        dx, dy = int(viewport_size["width"] * percent * 0.6), 0
    else:  # left
        dx, dy = -int(viewport_size["width"] * percent * 0.6), 0

    if ref:
        element = _resolve_element(ref)
        if not isinstance(element, _CoordinateElement):
            driver.execute_script("arguments[0].scrollBy(arguments[1], arguments[2])", element, dx, dy)
        else:
            driver.execute_script(f"window.scrollBy({dx}, {dy})")
    else:
        driver.execute_script(f"window.scrollBy({dx}, {dy})")

    time.sleep(0.5)
    ctx = _ref_context(ref) if ref else state.current_context
    return _ok()


def swipe(direction: str, ref: str = "", percent: float = 0.8) -> str:
    try:
        if direction not in _SCROLL_DIRECTION_REVERSE:
            return _failed("direction must be one of: up, down, left, right")
        if (ref and _is_web_ref(ref)) or (not ref and is_web_context(state.current_context)):
            _require_native_context("swipe")
        params: dict[str, Any] = {"direction": direction, "percent": min(percent, 1.0)}
        if ref:
            params.update(_gesture_target(ref))
        else:
            params.update(_screen_rect())
        _require_driver().execute_script("mobile: swipeGesture", params)
        time.sleep(0.5)
        return _ok()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except AppiumCliError:
        raise
    except Exception as exc:
        return _failed(str(exc))


def press_key(key: str) -> str:
    ctx = state.current_context
    if is_web_context(ctx):
        return _web_press_key(key)
    if key not in _KEYCODE_MAP:
        return _failed(f"unknown key '{key}'. Use one of: {', '.join(sorted(_KEYCODE_MAP))}")
    try:
        _require_driver().press_keycode(_KEYCODE_MAP[key])
        time.sleep(0.5)
        return _ok()
    except Exception as exc:
        return _failed(str(exc))


def _web_press_key(key: str) -> str:
    """Send a key in WebView context using Selenium/W3C key names."""
    from selenium.webdriver.common.keys import Keys

    driver = _require_driver()
    key_lower = key.lower()

    w3c_val = _W3C_KEY_MAP.get(key_lower)
    if w3c_val is None:
        if len(key) == 1:
            w3c_val = key
        else:
            attr = key.upper().replace(" ", "_")
            w3c_val = getattr(Keys, attr, None)
            if w3c_val is None:
                return _failed(
                    f"unknown W3C key '{key}'. Use one of: "
                    f"{', '.join(sorted(_W3C_KEY_MAP))} or a single character."
                )
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).send_keys(w3c_val).perform()
        time.sleep(0.5)
        return _ok()
    except Exception as exc:
        return _failed(str(exc))


def wait(seconds: float = 1.0) -> str:
    time.sleep(seconds)
    return _ok()


def long_press(ref: str, duration: int = 500) -> str:
    try:
        if _is_web_ref(ref):
            raise AppiumCliError(
                "long_press is not supported in WebView context.",
                exit_code=FEATURE_NOT_ENABLED,
            )
        params = _gesture_target(ref)
        params["duration"] = duration
        _require_driver().execute_script("mobile: longClickGesture", params)
        time.sleep(0.5)
        return _ok()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except AppiumCliError:
        raise
    except Exception as exc:
        return _failed(str(exc))


def double_tap(ref: str) -> str:
    try:
        if _is_web_ref(ref):
            raise AppiumCliError(
                "double_tap is not supported in WebView context.",
                exit_code=FEATURE_NOT_ENABLED,
            )
        _require_driver().execute_script("mobile: doubleClickGesture", _gesture_target(ref))
        time.sleep(0.5)
        return _ok()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except AppiumCliError:
        raise
    except Exception as exc:
        return _failed(str(exc))


def drag(ref: str, end_x: int, end_y: int, speed: int | None = None) -> str:
    try:
        if _is_web_ref(ref):
            raise AppiumCliError(
                "drag is not supported in WebView context.",
                exit_code=FEATURE_NOT_ENABLED,
            )
        params = _gesture_target(ref)
        params.update({"endX": end_x, "endY": end_y})
        if speed is not None:
            params["speed"] = speed
        _require_driver().execute_script("mobile: dragGesture", params)
        time.sleep(0.5)
        return _ok()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except AppiumCliError:
        raise
    except Exception as exc:
        return _failed(str(exc))


def fling(direction: str, ref: str = "", speed: int | None = None) -> str:
    try:
        if (ref and _is_web_ref(ref)) or (not ref and is_web_context(state.current_context)):
            raise AppiumCliError(
                "fling is not supported in WebView context.",
                exit_code=FEATURE_NOT_ENABLED,
            )
        params: dict[str, Any] = {"direction": direction}
        if speed is not None:
            params["speed"] = speed
        if ref:
            params.update(_gesture_target(ref))
        else:
            params.update(_screen_rect())
        can_scroll_more = _require_driver().execute_script("mobile: flingGesture", params)
        time.sleep(0.5)
        return _ok(f"OK\ncan_scroll_more: {can_scroll_more}")
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except AppiumCliError:
        raise
    except Exception as exc:
        return _failed(str(exc))


def pinch_open(ref: str, percent: float = 0.5, speed: int | None = None) -> str:
    if _is_web_ref(ref):
        raise AppiumCliError(
            "pinch_open is not supported in WebView context.",
            exit_code=FEATURE_NOT_ENABLED,
        )
    return _pinch("mobile: pinchOpenGesture", ref, percent, speed)


def pinch_close(ref: str, percent: float = 0.5, speed: int | None = None) -> str:
    if _is_web_ref(ref):
        raise AppiumCliError(
            "pinch_close is not supported in WebView context.",
            exit_code=FEATURE_NOT_ENABLED,
        )
    return _pinch("mobile: pinchCloseGesture", ref, percent, speed)


def _pinch(script: str, ref: str, percent: float, speed: int | None) -> str:
    try:
        params = _gesture_target(ref)
        params["percent"] = percent
        if speed is not None:
            params["speed"] = speed
        _require_driver().execute_script(script, params)
        time.sleep(0.5)
        return _ok()
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except Exception as exc:
        return _failed(str(exc))


def web_eval(script: str, ref: str = "") -> str:
    """Evaluate JavaScript in WebView context."""
    driver = _require_driver()
    if not is_web_context(state.current_context):
        raise AppiumCliError(
            "web_eval requires a WebView context. Use switch_context or snapshot --context=webview first.",
            exit_code=FEATURE_NOT_ENABLED,
        )
    try:
        if ref:
            element = _resolve_element(ref)
            if isinstance(element, _CoordinateElement):
                return _failed("web_eval ref must be a real element, not coordinates")
            result = driver.execute_script(script, element)
        else:
            result = driver.execute_script(script)
        if result is None:
            return "null"
        return str(result)
    except ElementNotFoundError as exc:
        return _failed(str(exc))
    except Exception as exc:
        return _failed(str(exc))
