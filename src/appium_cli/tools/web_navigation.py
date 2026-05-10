"""WebView navigation tools: goto, go_back, go_forward, reload."""

from __future__ import annotations

from appium_cli.daemon import state
from appium_cli.tools.contexts import is_web_context
from appium_cli.utils.errors import AppiumCliError
from appium_cli.utils.exit_codes import FEATURE_NOT_ENABLED


def _require_web_driver():
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    ctx = state.current_context
    if is_web_context(ctx):
        return state.driver
    # Auto-switch to WebView if available
    from appium_cli.tools.contexts import switch_to_context, available_contexts
    web_contexts = [c for c in available_contexts(state.driver) if is_web_context(c)]
    if web_contexts:
        switch_to_context(web_contexts[0], state.driver)
        return state.driver
    raise AppiumCliError(
        "Navigation commands require a WebView context. "
        "No WebView context is available. Ensure the app has a WebView with debugging enabled.",
        exit_code=FEATURE_NOT_ENABLED,
    )


def goto(url: str) -> str:
    """Navigate WebView to a URL."""
    driver = _require_web_driver()
    driver.get(url)
    try:
        actual_url = driver.current_url or url
        return f"Navigated to {actual_url}"
    except Exception:
        return f"Navigated to {url}"


def go_back() -> str:
    """Go back in WebView history."""
    driver = _require_web_driver()
    driver.back()
    try:
        url = driver.current_url or ""
        return f"Navigated back to {url}" if url else "Navigated back"
    except Exception:
        return "Navigated back"


def go_forward() -> str:
    """Go forward in WebView history."""
    driver = _require_web_driver()
    driver.forward()
    try:
        url = driver.current_url or ""
        return f"Navigated forward to {url}" if url else "Navigated forward"
    except Exception:
        return "Navigated forward"


def reload() -> str:
    """Reload the current WebView page."""
    driver = _require_web_driver()
    driver.refresh()
    try:
        url = driver.current_url or ""
        return f"Reloaded {url}" if url else "Reloaded"
    except Exception:
        return "Reloaded"


# ---------------------------------------------------------------------------
# Tab / window management
# ---------------------------------------------------------------------------

import time as _time


def tabs(action: str, index: int | None = None, url: str = "") -> str:
    """Manage WebView tabs/windows: list, switch, close, new."""
    driver = _require_web_driver()
    action = action.lower().strip()

    if action == "list":
        handles = driver.window_handles
        current = driver.current_window_handle
        lines: list[str] = []
        for i, h in enumerate(handles):
            marker = " *" if h == current else ""
            try:
                driver.switch_to.window(h)
                title = driver.title or ""
                page_url = driver.current_url or ""
                lines.append(f"  {i}: {title} ({page_url}){marker}")
            except Exception:
                lines.append(f"  {i}: {h}{marker}")
        # Restore original window
        try:
            driver.switch_to.window(current)
        except Exception:
            pass
        header = f"{len(handles)} tab(s):"
        return header + "\n" + "\n".join(lines)

    if action == "switch":
        if index is None:
            raise AppiumCliError("--index is required for tabs switch")
        handles = driver.window_handles
        if index < 0 or index >= len(handles):
            raise AppiumCliError(f"index {index} out of range (0-{len(handles) - 1})")
        driver.switch_to.window(handles[index])
        try:
            title = driver.title or ""
            page_url = driver.current_url or ""
            return f"Switched to tab {index}: {title} ({page_url})"
        except Exception:
            return f"Switched to tab {index}"

    if action == "close":
        handles = driver.window_handles
        if len(handles) <= 1:
            raise AppiumCliError("Cannot close the last remaining tab")
        current = driver.current_window_handle
        target_idx = index if index is not None else handles.index(current)
        if target_idx < 0 or target_idx >= len(handles):
            raise AppiumCliError(f"index {target_idx} out of range (0-{len(handles) - 1})")
        target_handle = handles[target_idx]
        driver.switch_to.window(target_handle)
        driver.close()
        remaining = [h for h in handles if h != target_handle]
        driver.switch_to.window(remaining[0])
        return f"Closed tab {target_idx}. Now on tab 0."

    if action == "new":
        target_url = url or "about:blank"
        driver.execute_script(f"window.open('{target_url}')")
        _time.sleep(0.5)
        handles = driver.window_handles
        driver.switch_to.window(handles[-1])
        try:
            title = driver.title or ""
            page_url = driver.current_url or ""
            return f"Opened new tab {len(handles) - 1}: {title} ({page_url})"
        except Exception:
            return f"Opened new tab {len(handles) - 1}"

    raise AppiumCliError(f"Unknown tabs action '{action}'. Use list, switch, close, or new.")
