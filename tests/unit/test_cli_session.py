from __future__ import annotations

import pytest
import typer

from appium_cli.cli import session as session_cli
from appium_cli.utils import exit_codes


def test_session_status_reports_running_when_webdriver_session_is_ready(monkeypatch, capsys) -> None:
    calls: list[str] = []

    def fake_request(tool: str):
        calls.append(tool)
        return {
            "ok": True,
            "text": "Driver is initialized and ready",
            "data": {
                "ready": True,
                "session_id": "session-1",
                "udid": "device-1",
                "server_url": "http://127.0.0.1:4723",
                "shell_capable": True,
            },
        }

    monkeypatch.setattr(session_cli, "request", fake_request)

    session_cli.status()

    assert calls == ["get_driver_status"]
    assert capsys.readouterr().out.splitlines() == [
        "running: true",
        "session_id: session-1",
        "udid: device-1",
        "server_url: http://127.0.0.1:4723",
        "shell_capable: true",
    ]


def test_session_status_reports_stopped_when_webdriver_session_is_dead(monkeypatch, capsys) -> None:
    def fake_request(tool: str):
        assert tool == "get_driver_status"
        return {
            "ok": True,
            "text": "Driver is not initialized",
            "data": {"ready": False, "session_id": "session-1"},
        }

    monkeypatch.setattr(session_cli, "request", fake_request)

    with pytest.raises(typer.Exit) as exc_info:
        session_cli.status()

    assert exc_info.value.exit_code == exit_codes.STOPPED
    assert capsys.readouterr().out == "running: false\n"


def test_session_status_reports_stopped_when_daemon_request_fails(monkeypatch, capsys) -> None:
    def fake_request(tool: str):
        assert tool == "get_driver_status"
        raise OSError("socket missing")

    monkeypatch.setattr(session_cli, "request", fake_request)

    with pytest.raises(typer.Exit) as exc_info:
        session_cli.status()

    assert exc_info.value.exit_code == exit_codes.STOPPED
    assert capsys.readouterr().out == "running: false\n"


def test_daemon_running_handles_oserror_from_socket_exists(monkeypatch) -> None:
    """_daemon_running must not crash when socket exists() raises OSError (virtiofs)."""
    from pathlib import Path

    class FailingPath(type(Path())):
        def exists(self):  # type: ignore[override]
            raise OSError("Operation not supported")

    monkeypatch.setattr(
        session_cli,
        "session_socket_path",
        lambda: FailingPath("/nonexistent/session.sock"),
    )

    assert session_cli._daemon_running() is False


def test_unlink_safe_swallows_oserror(monkeypatch, tmp_path) -> None:
    from pathlib import Path

    class FailingPath(type(Path())):
        def unlink(self, missing_ok=False):  # type: ignore[override]
            raise OSError("Operation not supported")

    session_cli._unlink_safe(FailingPath(str(tmp_path / "nope.sock")))


def test_path_exists_safe_returns_true_on_real_file(tmp_path) -> None:
    p = tmp_path / "file"
    p.write_text("x")
    assert session_cli._path_exists_safe(p) is True
