"""WebView navigation tools: goto, go_back, go_forward, reload."""

from __future__ import annotations

from appium_cli.daemon import state
from appium_cli.tools.actions import _ok_with_snapshot
from appium_cli.tools.contexts import is_web_context
from appium_cli.utils.errors import AppiumCliError
from appium_cli.utils.exit_codes import FEATURE_NOT_ENABLED


def _require_web_driver():
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    ctx = state.current_context
    if not is_web_context(ctx):
        raise AppiumCliError(
            "Navigation commands require a WebView context. "
            "Use switch_context or snapshot --context=webview first.",
            exit_code=FEATURE_NOT_ENABLED,
        )
    return state.driver


def goto(url: str) -> str:
    """Navigate WebView to a URL."""
    driver = _require_web_driver()
    driver.get(url)
    try:
        actual_url = driver.current_url or url
        return _ok_with_snapshot(message=f"Navigated to {actual_url}")
    except Exception:
        return _ok_with_snapshot(message=f"Navigated to {url}")


def go_back() -> str:
    """Go back in WebView history."""
    driver = _require_web_driver()
    driver.back()
    try:
        url = driver.current_url or ""
        return _ok_with_snapshot(message=f"Navigated back to {url}" if url else "Navigated back")
    except Exception:
        return _ok_with_snapshot(message="Navigated back")


def go_forward() -> str:
    """Go forward in WebView history."""
    driver = _require_web_driver()
    driver.forward()
    try:
        url = driver.current_url or ""
        return _ok_with_snapshot(message=f"Navigated forward to {url}" if url else "Navigated forward")
    except Exception:
        return _ok_with_snapshot(message="Navigated forward")


def reload() -> str:
    """Reload the current WebView page."""
    driver = _require_web_driver()
    driver.refresh()
    try:
        url = driver.current_url or ""
        return _ok_with_snapshot(message=f"Reloaded {url}" if url else "Reloaded")
    except Exception:
        return _ok_with_snapshot(message="Reloaded")
