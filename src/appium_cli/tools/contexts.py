"""Context inspection and switching tools for WebView/Chrome automation."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from appium_cli.daemon import state
from appium_cli.utils.errors import AppiumCliError
from appium_cli.utils.exit_codes import FEATURE_NOT_ENABLED


# ============================================================
# Constants
# ============================================================

NATIVE_CONTEXT = "NATIVE_APP"
WEB_CONTEXT_PREFIX = "WEBVIEW_"
CHROMIUM_CONTEXT = "CHROMIUM"


# ============================================================
# Helpers
# ============================================================


def is_web_context(context: str) -> bool:
    """Return True if *context* is a WebView or Chromium context."""
    return context.startswith(WEB_CONTEXT_PREFIX) or context == CHROMIUM_CONTEXT


def current_context(driver: Any) -> str:
    """Return the driver's current context and sync ``state.current_context``."""
    ctx: str = driver.current_context or NATIVE_CONTEXT
    state.current_context = ctx
    return ctx


def available_contexts(driver: Any) -> list[str]:
    """Return available contexts with ``NATIVE_APP`` always present."""
    contexts: list[str] = list(driver.contexts or [])
    if NATIVE_CONTEXT not in contexts:
        contexts.insert(0, NATIVE_CONTEXT)
    return contexts


def _first_web_context(driver: Any) -> str | None:
    """Return the first non-native context, or *None*."""
    for ctx in available_contexts(driver):
        if is_web_context(ctx):
            return ctx
    return None


def resolve_context(selector: str, driver: Any) -> str:
    """Map a user-facing selector to an exact Appium context name.

    Supported selectors:
        ``native``   → ``NATIVE_APP``
        ``current``  → whatever the driver reports
        ``webview``  → first available WebView/Chromium context
        ``auto``     → current context if web, else first web, else native
        exact name   → passed through as-is
    """
    sel = selector.strip().lower()

    if sel == "native":
        return NATIVE_CONTEXT

    if sel == "current":
        return current_context(driver)

    if sel == "webview":
        ctx = _first_web_context(driver)
        if ctx is None:
            raise AppiumCliError(
                "No WebView context available. "
                "Ensure the target app has a WebView with debugging enabled.",
                exit_code=FEATURE_NOT_ENABLED,
            )
        return ctx

    if sel == "auto":
        cur = current_context(driver)
        if is_web_context(cur):
            return cur
        ctx = _first_web_context(driver)
        return ctx if ctx is not None else NATIVE_CONTEXT

    # Exact context name (case-sensitive match)
    contexts = available_contexts(driver)
    # Try case-sensitive first
    if selector in contexts:
        return selector
    # Try case-insensitive fallback
    for ctx in contexts:
        if ctx.lower() == sel:
            return ctx
    raise AppiumCliError(
        f"Context '{selector}' not found. Available: {', '.join(contexts)}",
        exit_code=FEATURE_NOT_ENABLED,
    )


def switch_to_context(selector: str, driver: Any) -> str:
    """Resolve *selector* and switch the driver. Returns the actual context."""
    target = resolve_context(selector, driver)
    cur = current_context(driver)
    if cur != target:
        driver.switch_to.context(target)
        state.current_context = target
    return target


@contextmanager
def using_context(
    selector: str, driver: Any, *, restore: bool = True
) -> Generator[str, None, None]:
    """Context manager: switch to *selector*, yield the context name.

    If *restore* is True (default), switch back to the original context
    when the block exits.
    """
    original = current_context(driver)
    target = switch_to_context(selector, driver)
    try:
        yield target
    finally:
        if restore and current_context(driver) != original:
            driver.switch_to.context(original)
            state.current_context = original


# ============================================================
# Tool functions (called via daemon handler)
# ============================================================


def _require_driver() -> Any:
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    return state.driver


def list_contexts() -> str:
    """Show available Appium contexts with current marker."""
    driver = _require_driver()
    cur = current_context(driver)
    contexts = available_contexts(driver)
    lines: list[str] = []
    for ctx in contexts:
        marker = " (current)" if ctx == cur else ""
        kind = "web" if is_web_context(ctx) else "native"
        lines.append(f"  {ctx} [{kind}]{marker}")
    return "Contexts:\n" + "\n".join(lines)


def get_context() -> str:
    """Return current Appium context name."""
    driver = _require_driver()
    return current_context(driver)


def switch_context(context: str) -> str:
    """Switch to a context by selector or exact name."""
    driver = _require_driver()
    actual = switch_to_context(context, driver)
    return f"Switched to {actual}"


def native_switch() -> str:
    """Convenience: switch to NATIVE_APP."""
    return switch_context("native")


def webview_switch(context: str = "") -> str:
    """Convenience: switch to a WebView/CHROMIUM context.

    If *context* is empty, pick the first available WebView context.
    """
    driver = _require_driver()
    if context:
        target = resolve_context(context, driver)
        if not is_web_context(target):
            raise AppiumCliError(
                f"'{target}' is not a WebView context.",
                exit_code=FEATURE_NOT_ENABLED,
            )
        switch_to_context(context, driver)
        return f"Switched to {target}"
    return switch_context("webview")


def webview_status() -> str:
    """Diagnostic: WebView availability, URL/title, prerequisites."""
    driver = _require_driver()
    cur = current_context(driver)
    contexts = available_contexts(driver)
    web_contexts = [c for c in contexts if is_web_context(c)]

    lines: list[str] = [
        f"current_context: {cur}",
        f"available_contexts: {', '.join(contexts)}",
        f"webview_contexts: {', '.join(web_contexts) if web_contexts else 'none'}",
    ]

    if web_contexts:
        lines.append("webview_available: true")
        # Try to get URL and title if currently in a web context
        if is_web_context(cur):
            try:
                lines.append(f"url: {driver.current_url}")
            except Exception:
                lines.append("url: (unavailable)")
            try:
                lines.append(f"title: {driver.title}")
            except Exception:
                lines.append("title: (unavailable)")
    else:
        lines.append("webview_available: false")
        lines.append("")
        lines.append("hints:")
        lines.append("  - Ensure the app has a WebView with setWebContentsDebuggingEnabled(true)")
        lines.append("  - Wait for the WebView page to finish loading")
        lines.append("  - Check Chromedriver version compatibility with the device's Chrome/WebView")

    return "\n".join(lines)
