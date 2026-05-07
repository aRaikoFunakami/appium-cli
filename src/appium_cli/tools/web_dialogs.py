"""WebView dialog tools: dialog_accept, dialog_dismiss, dialog_text."""

from __future__ import annotations

from appium_cli.daemon import state
from appium_cli.tools.actions import _ok_with_snapshot


def _require_driver():
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    return state.driver


def dialog_accept(prompt_text: str = "") -> str:
    """Accept the current alert/confirm/prompt dialog.

    If *prompt_text* is provided, send it to a prompt dialog before accepting.
    """
    driver = _require_driver()
    try:
        alert = driver.switch_to.alert
        if prompt_text:
            alert.send_keys(prompt_text)
        alert.accept()
        return _ok_with_snapshot(message="Dialog accepted")
    except Exception as exc:
        return f"FAILED: {exc}"


def dialog_dismiss() -> str:
    """Dismiss the current alert/confirm/prompt dialog."""
    driver = _require_driver()
    try:
        alert = driver.switch_to.alert
        alert.dismiss()
        return _ok_with_snapshot(message="Dialog dismissed")
    except Exception as exc:
        return f"FAILED: {exc}"


def dialog_text() -> str:
    """Read the text of the current alert/confirm/prompt dialog."""
    driver = _require_driver()
    try:
        alert = driver.switch_to.alert
        return alert.text or ""
    except Exception as exc:
        return f"FAILED: {exc}"
