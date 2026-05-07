from __future__ import annotations

import sys
from types import SimpleNamespace

from selenium.common.exceptions import InvalidSessionIdException

from appium_cli.daemon import entry, state


class DriverWithInvalidQuit:
    session_id = "webdriver-session-1"

    def execute_script(self, *_args, **_kwargs) -> str:
        return "ok"

    def quit(self) -> None:
        raise InvalidSessionIdException("session already gone")


def test_main_ignores_invalid_session_during_driver_quit(monkeypatch) -> None:
    driver = DriverWithInvalidQuit()

    monkeypatch.setattr(sys, "argv", ["entry", "--server-url", "http://127.0.0.1:4723", "--udid", "device-1"])
    monkeypatch.setattr(entry, "_create_driver", lambda _server_url, _udid: driver)
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

    def fake_snapshot_refs(**kwargs):
        calls.append(("refs", kwargs))
        return "refs"

    monkeypatch.setattr(entry, "snapshot_show", fake_snapshot_show)
    monkeypatch.setattr(entry, "snapshot_search", fake_snapshot_search)
    monkeypatch.setattr(entry, "snapshot_refs", fake_snapshot_refs)

    assert entry._handler(
        {"tool": "snapshot_show", "args": {"snapshot_id": "latest"}, "raw": True}
    )["text"] == "shown"
    assert entry._handler(
        {"tool": "snapshot_search", "args": {"text": "OK"}, "raw": True}
    )["text"] == "found"
    assert entry._handler(
        {"tool": "snapshot_refs", "args": {"snapshot_id": "latest"}, "raw": True}
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

    monkeypatch.setattr(entry, "generate_locator", fake_generate_locator)
    monkeypatch.setattr(entry, "web_query", fake_web_query)

    assert entry._handler(
        {"tool": "generate_locator", "args": {"ref": "ok"}, "raw": True}
    )["text"] == "locator"
    assert entry._handler(
        {"tool": "web_query", "args": {"selector": "button"}, "raw": True}
    )["text"] == "query"

    assert calls == [
        ("locator", {"ref": "ok", "raw": True}),
        ("query", {"selector": "button", "raw": True}),
    ]


def test_action_handler_sets_and_restores_raw_output(monkeypatch) -> None:
    seen: list[bool] = []

    def fake_wait(seconds: float = 1.0) -> str:
        seen.append(state.action_raw_output)
        return f"raw={state.action_raw_output}, seconds={seconds}"

    monkeypatch.setattr(entry.actions, "wait", fake_wait)
    state.action_raw_output = False

    response = entry._handler({"tool": "wait", "args": {"seconds": 0.0}, "raw": True})

    assert response == {"text": "raw=True, seconds=0.0", "data": {}}
    assert seen == [True]
    assert state.action_raw_output is False
