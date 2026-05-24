"""Snapshot-ref based actions and gestures.

All ref-based actions resolve elements through RefResolver with
multi-strategy lookup and bounds verification.

Context-aware: actions branch to native (UiAutomator2 gestures) or
web (Selenium click/send_keys/JS) depending on the ref's stored context.
"""

from __future__ import annotations

import re
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
    """Deprecated: raise AppiumCliError instead of returning FAILED strings."""
    raise AppiumCliError(message)


def _is_web_ref(ref: str) -> bool:
    """Check if ref belongs to a web context."""
    clean = ref.strip("[]").removeprefix("ref:")
    entry = state.ref_resolver.get_entry(clean)
    if entry is None:
        return False
    return is_web_context(entry.context)


def _css_selector_from_target(target: str) -> str | None:
    """Extract CSS selector from target string, or None if not a CSS target."""
    if target.startswith("css:"):
        return target[4:]
    if target.startswith(("#", ".", "[")):
        return target
    return None


def _is_web_target(ref: str) -> bool:
    """Check if ref is a web target (web ref or CSS selector)."""
    if _css_selector_from_target(ref) is not None:
        return True
    return _is_web_ref(ref)


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
    """Resolve ref to WebElement via RefResolver with bounds verification.

    Also supports CSS selectors: ``css:#submit``, ``#submit``, ``.btn``, ``[name=x]``.
    """
    css = _css_selector_from_target(ref)
    if css is not None:
        driver = _require_driver()
        elements = driver.find_elements("css selector", css)
        if not elements:
            raise ElementNotFoundError(
                f"CSS selector '{css}' matched no elements. "
                "Check the selector or use web_query to inspect the DOM."
            )
        return elements[0]
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
        if _is_web_target(ref):
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
            try:
                element.click()
            except Exception as click_exc:
                if "intercepted" not in str(click_exc).lower():
                    raise
                driver = _require_driver()
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center',inline:'center'})",
                    element,
                )
                time.sleep(0.3)
                try:
                    element.click()
                except Exception as retry_exc:
                    if "intercepted" not in str(retry_exc).lower():
                        raise
                    blocker_info = driver.execute_script("""
                        var rect = arguments[0].getBoundingClientRect();
                        var cx = rect.x + rect.width / 2;
                        var cy = rect.y + rect.height / 2;
                        var top = document.elementFromPoint(cx, cy);
                        if (!top || top === arguments[0]) return null;
                        var tag = top.tagName.toLowerCase();
                        var cls = top.className ? ('.' + String(top.className).split(' ')[0]) : '';
                        var id = top.id ? ('#' + top.id) : '';
                        return tag + id + cls;
                    """, element)
                    msg = f"Click intercepted on '{ref}'"
                    if blocker_info:
                        msg += f" by <{blocker_info}>"
                    msg += ". Try closing overlays or scrolling."
                    raise AppiumCliError(msg) from retry_exc
            time.sleep(0.5)
            return _ok()
        _require_driver().execute_script("mobile: clickGesture", _gesture_target(ref))
        time.sleep(0.5)
        return _ok()
    except ElementNotFoundError as exc:
        raise AppiumCliError(str(exc)) from exc
    except AppiumCliError:
        raise
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


def click(ref: str) -> str:
    """Web-friendly alias for tap."""
    return tap(ref)


def type_text(ref: str, text: str, submit: bool = False, slowly: bool = False) -> str:
    try:
        element = _resolve_element(ref)
        if isinstance(element, _CoordinateElement):
            raise AppiumCliError(
                f"ref '{ref}' resolved to coordinates only; type_text/fill requires a real element. "
                "This usually means the element's CSS selector matches multiple DOM nodes "
                "and none matched the expected bounds. Run 'appium-cli snapshot' or "
                "'appium-cli web_snapshot' to refresh refs, then retry with the new ref."
            )
        web = _is_web_target(ref)
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
        raise AppiumCliError(str(exc)) from exc
    except AppiumCliError:
        raise
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


def fill(ref: str, text: str, submit: bool = False, slowly: bool = False) -> str:
    """Web-friendly alias for type_text."""
    return type_text(ref, text, submit, slowly)


def select(ref: str, value: str, by: str = "value") -> str:
    """Select an option in an HTML <select> element."""
    try:
        element = _resolve_element(ref)
        if isinstance(element, _CoordinateElement):
            raise AppiumCliError("select requires a real element, not coordinates")

        from selenium.webdriver.support.ui import Select
        sel = Select(element)
        if by == "value":
            sel.select_by_value(value)
        elif by == "label":
            sel.select_by_visible_text(value)
        elif by == "index":
            sel.select_by_index(int(value))
        else:
            raise AppiumCliError(f"Unknown select method: '{by}'. Use value, label, or index.")

        time.sleep(0.3)
        return _ok()
    except ElementNotFoundError as exc:
        raise AppiumCliError(str(exc)) from exc
    except AppiumCliError:
        raise
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


def select_option(ref: str, text: str, timeout: float = 3.0, exact: bool = True) -> str:
    """Select an option from a custom dropdown (react-select, etc.) or native <select> by visible text."""
    try:
        element = _resolve_element(ref)
        if isinstance(element, _CoordinateElement):
            raise AppiumCliError("select_option requires a real element, not coordinates")
        driver = _require_driver()

        # Check if this is a native <select>
        tag = driver.execute_script("return arguments[0].tagName.toLowerCase()", element)
        if tag == "select":
            from selenium.webdriver.support.ui import Select
            try:
                Select(element).select_by_visible_text(text)
            except Exception:
                Select(element).select_by_value(text)
            time.sleep(0.3)
            return _ok()

        # Custom dropdown: click to open
        element.click()

        # Poll for option appearance with timeout
        deadline = time.monotonic() + max(timeout, 0)
        found = None
        while True:
            time.sleep(0.3)
            found = driver.execute_script("""
                var text = arguments[0];
                var exact = arguments[1];
                var selectors = [
                    '[role="option"]',
                    '[class*="option"]',
                    '[id*="-option-"]',
                    '.dropdown-item',
                    'li[role="menuitem"]'
                ];
                var candidates = document.querySelectorAll(selectors.join(','));
                var available = [];
                for (var i = 0; i < candidates.length; i++) {
                    var el = candidates[i];
                    if (el.offsetParent === null) continue;
                    var t = el.innerText.trim();
                    if (!t) continue;
                    if (exact ? (t === text) : (t.indexOf(text) !== -1)) {
                        el.click();
                        return {found: true};
                    }
                    if (available.length < 10) available.push(t);
                }
                return {found: false, available: available};
            """, text, exact)

            if found and found.get("found"):
                time.sleep(0.3)
                return _ok()

            if time.monotonic() >= deadline:
                break

        available = found.get("available", []) if found else []
        hint = f" Available: {', '.join(available)}" if available else ""
        raise AppiumCliError(
            f"Option '{text}' not found in dropdown after {timeout}s.{hint} "
            "Try web_query('[role=option],[class*=option]') to see options."
        )
    except ElementNotFoundError as exc:
        raise AppiumCliError(str(exc)) from exc
    except AppiumCliError:
        raise
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


_MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _parse_date(date_str: str) -> tuple[int, int, int] | None:
    """Parse date string to (year, month, day). Returns None on failure."""
    s = date_str.strip()
    # ISO: 1990-05-15
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    # US: 05/15/1990
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return int(m.group(3)), int(m.group(1)), int(m.group(2))
    # Display: 15 May 1990
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", s)
    if m:
        month = _MONTH_NAMES.get(m.group(2).lower())
        if month:
            return int(m.group(3)), month, int(m.group(1))
    return None


def set_date(ref: str, date: str) -> str:
    """Set a date value on an input element, supporting react-datepicker and native date inputs."""
    parsed = _parse_date(date)
    if parsed is None:
        raise AppiumCliError(
            f"Cannot parse date '{date}'. "
            "Supported formats: '15 May 1990', '1990-05-15', '05/15/1990'."
        )
    year, month, day = parsed
    try:
        element = _resolve_element(ref)
        if isinstance(element, _CoordinateElement):
            raise AppiumCliError("set_date requires a real element, not coordinates")
        driver = _require_driver()

        # Determine input type
        input_type = driver.execute_script(
            "return (arguments[0].type || '').toLowerCase()", element
        )

        if input_type == "date":
            # Native date input: use ISO format
            iso = f"{year:04d}-{month:02d}-{day:02d}"
            driver.execute_script("""
                var nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                nativeSetter.call(arguments[0], arguments[1]);
                arguments[0].dispatchEvent(new Event('input', {bubbles: true}));
                arguments[0].dispatchEvent(new Event('change', {bubbles: true}));
            """, element, iso)
        else:
            # Text input (react-datepicker, etc.): use display format
            display = f"{day:02d} {_MONTH_ABBR[month]} {year}"
            driver.execute_script("""
                var nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                nativeSetter.call(arguments[0], arguments[1]);
                arguments[0].dispatchEvent(new Event('input', {bubbles: true}));
                arguments[0].dispatchEvent(new Event('change', {bubbles: true}));
            """, element, display)

        time.sleep(0.3)
        return _ok()
    except ElementNotFoundError as exc:
        raise AppiumCliError(str(exc)) from exc
    except AppiumCliError:
        raise
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


def scroll(direction: str, ref: str = "", percent: float = 0.8) -> str:
    try:
        if direction not in _SCROLL_DIRECTION_REVERSE:
            raise AppiumCliError("direction must be one of: up, down, left, right")

        # Web context scroll via JS
        if (ref and _is_web_target(ref)) or (not ref and is_web_context(state.current_context)):
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
        raise AppiumCliError(str(exc)) from exc
    except AppiumCliError:
        raise
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


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
            raise AppiumCliError("direction must be one of: up, down, left, right")
        if (ref and _is_web_target(ref)) or (not ref and is_web_context(state.current_context)):
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
        raise AppiumCliError(str(exc)) from exc
    except AppiumCliError:
        raise
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


def press_key(key: str) -> str:
    ctx = state.current_context
    if is_web_context(ctx):
        return _web_press_key(key)
    if key not in _KEYCODE_MAP:
        raise AppiumCliError(f"unknown key '{key}'. Use one of: {', '.join(sorted(_KEYCODE_MAP))}")
    try:
        _require_driver().press_keycode(_KEYCODE_MAP[key])
        time.sleep(0.5)
        return _ok()
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


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
                raise AppiumCliError(
                    f"unknown W3C key '{key}'. Use one of: "
                    f"{', '.join(sorted(_W3C_KEY_MAP))} or a single character."
                )
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).send_keys(w3c_val).perform()
        time.sleep(0.5)
        return _ok()
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


def wait(seconds: float = 1.0) -> str:
    time.sleep(seconds)
    return _ok()


def long_press(ref: str, duration: int = 500) -> str:
    try:
        if _is_web_target(ref):
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
        raise AppiumCliError(str(exc)) from exc
    except AppiumCliError:
        raise
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


def double_tap(ref: str) -> str:
    try:
        if _is_web_target(ref):
            raise AppiumCliError(
                "double_tap is not supported in WebView context.",
                exit_code=FEATURE_NOT_ENABLED,
            )
        _require_driver().execute_script("mobile: doubleClickGesture", _gesture_target(ref))
        time.sleep(0.5)
        return _ok()
    except ElementNotFoundError as exc:
        raise AppiumCliError(str(exc)) from exc
    except AppiumCliError:
        raise
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


def drag(ref: str, end_x: int, end_y: int, speed: int | None = None) -> str:
    try:
        if _is_web_target(ref):
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
        raise AppiumCliError(str(exc)) from exc
    except AppiumCliError:
        raise
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


def fling(direction: str, ref: str = "", speed: int | None = None) -> str:
    try:
        if (ref and _is_web_target(ref)) or (not ref and is_web_context(state.current_context)):
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
        raise AppiumCliError(str(exc)) from exc
    except AppiumCliError:
        raise
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


def pinch_open(ref: str, percent: float = 0.5, speed: int | None = None) -> str:
    if _is_web_target(ref):
        raise AppiumCliError(
            "pinch_open is not supported in WebView context.",
            exit_code=FEATURE_NOT_ENABLED,
        )
    return _pinch("mobile: pinchOpenGesture", ref, percent, speed)


def pinch_close(ref: str, percent: float = 0.5, speed: int | None = None) -> str:
    if _is_web_target(ref):
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
        raise AppiumCliError(str(exc)) from exc
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


_WEB_EVAL_NAVIGATION_PATTERNS = (
    (re.compile(r"window\s*\.\s*location\s*(?:\.\s*(?:href|assign|replace))?\s*(?:=|\()"),
     "Looks like a navigation via window.location. Prefer `appium-cli goto <url>`."),
    (re.compile(r"\blocation\s*\.\s*href\s*="),
     "Looks like a navigation via location.href. Prefer `appium-cli goto <url>`."),
    (re.compile(r"\bhistory\s*\.\s*(?:push|replace)State\b"),
     "Looks like a history.pushState/replaceState navigation. Prefer `appium-cli goto`."),
)
_WEB_EVAL_VALUE_INJECTION_PATTERNS = (
    (re.compile(r"\.\s*value\s*=\s*"),
     "Looks like a direct .value assignment. Prefer `appium-cli fill` (or `fill --slowly`) so React/Vue listeners fire."),
    (re.compile(r"dispatchEvent\s*\(\s*new\s+(?:Input|Keyboard)?Event\s*\(\s*['\"](?:input|change|keydown|keyup|keypress)['\"]"),
     "Looks like a synthetic input/change event dispatch. Prefer `appium-cli fill` for form fields."),
)


def lint_web_eval(script: str) -> list[str]:
    """Return non-fatal warnings for common web_eval misuse patterns."""
    warnings: list[str] = []
    if not isinstance(script, str) or not script:
        return warnings
    for pattern, message in _WEB_EVAL_NAVIGATION_PATTERNS:
        if pattern.search(script):
            warnings.append(message)
            break
    for pattern, message in _WEB_EVAL_VALUE_INJECTION_PATTERNS:
        if pattern.search(script):
            warnings.append(message)
            break
    return warnings


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
                raise AppiumCliError("web_eval ref must be a real element, not coordinates")
            result = driver.execute_script(script, element)
        else:
            result = driver.execute_script(script)
        if result is None:
            return "null"
        return str(result)
    except ElementNotFoundError as exc:
        raise AppiumCliError(str(exc)) from exc
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


def file_upload(ref: str, path: str) -> str:
    """Upload a file to an <input type='file'> element."""
    import base64
    import os

    try:
        element = _resolve_element(ref)
        if isinstance(element, _CoordinateElement):
            raise AppiumCliError("file_upload requires a real element, not coordinates")
        driver = _require_driver()

        local_path = os.path.expanduser(path)
        if os.path.isfile(local_path):
            filename = os.path.basename(local_path)
            device_path = f"/sdcard/Download/{filename}"
            with open(local_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            driver.push_file(device_path, base64data=b64)
            element.send_keys(device_path)
        else:
            # Assume path is already a device path
            element.send_keys(path)

        time.sleep(0.3)
        return _ok()
    except ElementNotFoundError as exc:
        raise AppiumCliError(str(exc)) from exc
    except AppiumCliError:
        raise
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc


def wait_for(
    text: str = "",
    gone: str = "",
    ref: str = "",
    timeout: float = 15.0,
    poll: float = 0.5,
) -> str:
    """Wait for text to appear/disappear or element to become visible/invisible."""
    driver = _require_driver()

    if not text and not gone and not ref:
        raise AppiumCliError("Specify --text, --gone, or --ref.")

    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import TimeoutException

    wait = WebDriverWait(driver, timeout, poll_frequency=poll)

    try:
        if text:
            # Wait for text to appear anywhere in the page
            if is_web_context(state.current_context):
                wait.until(lambda d: d.execute_script(
                    "return document.body && document.body.innerText.indexOf(arguments[0]) !== -1",
                    text,
                ))
            else:
                wait.until(lambda d: text in (d.page_source or ""))
            return _ok(f"Text '{text}' appeared")

        if gone:
            # Wait for text to disappear
            if is_web_context(state.current_context):
                wait.until(lambda d: d.execute_script(
                    "return !document.body || document.body.innerText.indexOf(arguments[0]) === -1",
                    gone,
                ))
            else:
                wait.until(lambda d: gone not in (d.page_source or ""))
            return _ok(f"Text '{gone}' disappeared")

        if ref:
            # Wait for ref element to be visible
            entry = state.ref_resolver.get_entry(ref.strip("[]").removeprefix("ref:"))
            if entry is not None:
                # Known ref: resolve and check visibility
                wait.until(lambda d: _try_resolve_visible(ref, d))
                return _ok(f"Element '{ref}' is visible")
            else:
                raise AppiumCliError(f"Ref '{ref}' not found in current snapshot. Take a new snapshot first.")

    except TimeoutException as exc:
        target = text or gone or ref
        raise AppiumCliError(f"Timed out after {timeout}s waiting for '{target}'") from exc
    except Exception as exc:
        raise AppiumCliError(str(exc)) from exc

    raise AppiumCliError("No wait condition specified")


def _try_resolve_visible(ref: str, driver: Any) -> bool:
    """Try to resolve and check element visibility. Returns False on failure."""
    try:
        element = state.ref_resolver.resolve(ref, driver)
        if isinstance(element, _CoordinateElement):
            return True
        return element.is_displayed()
    except Exception:
        return False
