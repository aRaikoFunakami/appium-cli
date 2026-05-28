from __future__ import annotations

import sys
from types import SimpleNamespace

from selenium.common.exceptions import InvalidSessionIdException

from appium_cli.core.ref_resolver import ElementNotFoundError, StaleSnapshotError
from appium_cli.daemon import entry, state
from appium_cli.utils.errors import AppiumCliError


class DriverWithInvalidQuit:
    session_id = "webdriver-session-1"

    def execute_script(self, *_args, **_kwargs) -> str:
        return "ok"

    def quit(self) -> None:
        raise InvalidSessionIdException("session already gone")


def test_main_ignores_invalid_session_during_driver_quit(monkeypatch) -> None:
    driver = DriverWithInvalidQuit()

    monkeypatch.setattr(sys, "argv", ["entry", "--server-url", "http://127.0.0.1:4723", "--udid", "device-1"])
    monkeypatch.setattr(entry, "_create_driver", lambda _server_url, _udid, **_kw: driver)
    monkeypatch.setattr(entry, "serve", lambda handler: None)

    entry.main()

    assert state.driver is None


def test_snapshot_handler_passes_raw_and_returns_metadata(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_refresh_snapshot(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="raw tree", data={"snapshot_id": "snap-1"})

    monkeypatch.setattr(entry, "refresh_snapshot", fake_refresh_snapshot)

    response = entry._handler(
        {"tool": "snapshot", "args": {"scope": "full", "context": "native"}, "raw": True}
    )

    assert response == {"text": "raw tree", "data": {"snapshot_id": "snap-1"}}
    assert calls == [{"scope": "full", "context": "native", "raw": True}]


def test_snapshot_artifact_handlers_pass_raw(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_snapshot_show(**kwargs):
        calls.append(("show", kwargs))
        return "shown"

    def fake_snapshot_search(**kwargs):
        calls.append(("search", kwargs))
        return "found"

    def fake_web_refs(**kwargs):
        calls.append(("refs", kwargs))
        return "refs"

    monkeypatch.setattr(entry, "snapshot_show", fake_snapshot_show)
    monkeypatch.setattr(entry, "snapshot_search", fake_snapshot_search)
    monkeypatch.setattr(entry, "web_refs", fake_web_refs)

    assert entry._handler(
        {"tool": "snapshot_show", "args": {"snapshot_id": "latest"}, "raw": True}
    )["text"] == "shown"
    assert entry._handler(
        {"tool": "snapshot_search", "args": {"text": "OK"}, "raw": True}
    )["text"] == "found"
    assert entry._handler(
        {"tool": "web_refs", "args": {"snapshot_id": "latest"}, "raw": True}
    )["text"] == "refs"

    assert calls == [
        ("show", {"snapshot_id": "latest", "raw": True}),
        ("search", {"text": "OK", "raw": True}),
        ("refs", {"snapshot_id": "latest", "raw": True}),
    ]


def test_locator_query_handlers_pass_raw(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_generate_locator(**kwargs):
        calls.append(("locator", kwargs))
        return "locator"

    def fake_web_query(**kwargs):
        calls.append(("query", kwargs))
        return "query"

    def fake_web_text(**kwargs):
        calls.append(("text", kwargs))
        return "text"

    monkeypatch.setattr(entry, "generate_locator", fake_generate_locator)
    monkeypatch.setattr(entry, "web_query", fake_web_query)
    monkeypatch.setattr(entry, "web_text", fake_web_text)

    assert entry._handler(
        {"tool": "generate_locator", "args": {"ref": "ok"}, "raw": True}
    )["text"] == "locator"
    assert entry._handler(
        {"tool": "web_query", "args": {"selector": "button"}, "raw": True}
    )["text"] == "query"
    assert entry._handler(
        {"tool": "web_text", "args": {"selector": "article"}, "raw": True}
    )["text"] == "text"

    assert calls == [
        ("locator", {"ref": "ok", "raw": True}),
        ("query", {"selector": "button", "raw": True}),
        ("text", {"selector": "article", "raw": True}),
    ]


def test_action_handler_delegates_to_handle_request(monkeypatch) -> None:
    def fake_wait(seconds: float = 1.0) -> str:
        return f"seconds={seconds}"

    monkeypatch.setattr(entry.actions, "wait", fake_wait)

    response = entry._handler({"tool": "wait", "args": {"seconds": 0.0}})

    assert response == {"text": "seconds=0.0", "data": {}}


def _raise_wrapped_stale(
    ref: str = "rv_popups",
    *,
    context: str = "NATIVE_APP",
    reason: str = "tap(tabbackground_2)",
) -> None:
    stale = StaleSnapshotError(
        ref,
        f"snapshot_required: snapshot is stale after {reason}. Call snapshot() before using refs.",
        context=context,
        reason=reason,
    )
    try:
        raise stale
    except StaleSnapshotError as exc:
        raise AppiumCliError(str(exc)) from exc


def _raise_wrapped_missing(ref: str = "rv_popups") -> None:
    missing = ElementNotFoundError(ref, "Not registered in the current in-memory snapshot.")
    try:
        raise missing
    except ElementNotFoundError as exc:
        raise AppiumCliError(str(exc)) from exc


def test_stale_action_auto_refreshes_and_retries_once(monkeypatch) -> None:
    calls: list[str] = []
    refresh_calls: list[dict] = []

    def fake_tap(ref: str) -> str:
        calls.append(ref)
        if len(calls) == 1:
            _raise_wrapped_stale(ref)
        return "OK"

    def fake_refresh_snapshot(**kwargs):
        refresh_calls.append(kwargs)
        return SimpleNamespace(text="snapshot_id: fresh\n", data={"snapshot_id": "fresh"})

    monkeypatch.setattr(entry.actions, "tap", fake_tap)
    monkeypatch.setattr(entry, "refresh_snapshot", fake_refresh_snapshot)

    response = entry._handler({"tool": "tap", "args": {"ref": "rv_popups"}})

    assert response["text"] == "OK"
    assert response["data"]["auto_refreshed"] is True
    assert response["data"]["action_executed"] is True
    assert response["data"]["snapshot"]["data"] == {"snapshot_id": "fresh"}
    assert calls == ["rv_popups", "rv_popups"]
    assert refresh_calls == [{"scope": "full", "context": "native", "boxes": False, "raw": False}]


def test_stale_action_refreshes_web_context(monkeypatch) -> None:
    refresh_calls: list[dict] = []

    def fake_click(ref: str) -> str:
        if not refresh_calls:
            _raise_wrapped_stale(ref, context="WEBVIEW_com.example", reason="tap(web_button)")
        return "OK"

    def fake_refresh_snapshot(**kwargs):
        refresh_calls.append(kwargs)
        return SimpleNamespace(text="snapshot_id: web-fresh\n", data={"snapshot_id": "web-fresh"})

    monkeypatch.setattr(entry.actions, "click", fake_click)
    monkeypatch.setattr(entry, "refresh_snapshot", fake_refresh_snapshot)

    response = entry._handler({"tool": "click", "args": {"ref": "web_button"}})

    assert response["data"]["auto_refreshed"] is True
    assert refresh_calls[0]["context"] == "WEBVIEW_com.example"


def test_stale_action_returns_ref_missing_after_refresh(monkeypatch) -> None:
    calls = 0

    def fake_scroll(direction: str, ref: str, percent: float = 0.8) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            _raise_wrapped_stale(ref)
        _raise_wrapped_missing(ref)

    def fake_refresh_snapshot(**_kwargs):
        return SimpleNamespace(text="snapshot_id: fresh\n", data={"snapshot_id": "fresh"})

    monkeypatch.setattr(entry.actions, "scroll", fake_scroll)
    monkeypatch.setattr(entry, "refresh_snapshot", fake_refresh_snapshot)

    response = entry._handler(
        {"tool": "scroll", "args": {"direction": "up", "ref": "rv_popups", "percent": 0.8}}
    )

    assert response["ok"] is False
    assert response["data"]["auto_refreshed"] is True
    assert response["data"]["action_executed"] is False
    assert response["data"]["missing_ref"] == "rv_popups"
    assert calls == 2


def test_non_stale_action_error_does_not_auto_refresh(monkeypatch) -> None:
    refresh_calls: list[dict] = []

    def fake_scroll(direction: str, ref: str, percent: float = 0.8) -> str:
        raise AppiumCliError("ref 'container' resolved to coordinates only; scroll requires a real element")

    def fake_refresh_snapshot(**kwargs):
        refresh_calls.append(kwargs)
        return SimpleNamespace(text="", data={})

    monkeypatch.setattr(entry.actions, "scroll", fake_scroll)
    monkeypatch.setattr(entry, "refresh_snapshot", fake_refresh_snapshot)

    try:
        entry._handler({"tool": "scroll", "args": {"direction": "up", "ref": "container"}})
    except AppiumCliError as exc:
        assert "coordinates only" in str(exc)
    else:
        raise AssertionError("expected AppiumCliError")
    assert refresh_calls == []
