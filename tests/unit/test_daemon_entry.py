from __future__ import annotations

import sys

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
