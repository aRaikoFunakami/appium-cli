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


class _FakeProc:
    def __init__(self, command, **kwargs):
        self.command = command
        self.pid = 999
        self.returncode = None
        _FakeProc.last = self

    def poll(self):
        return None

    def terminate(self):
        pass


def _capture_session_start(monkeypatch, tmp_path, **kwargs):
    """Run session start and return the daemon command argv."""
    from appium_cli.cli import server as server_mod

    # Daemon is not running yet.
    monkeypatch.setattr(session_cli, "_daemon_running", lambda: False)
    # After spawn, simulate the daemon becoming ready.
    daemon_ready = {"v": False}
    orig_daemon_running = session_cli._daemon_running

    def daemon_running_after_spawn():
        return daemon_ready["v"]

    # Set up paths into tmp.
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(session_cli, "ensure_app_dir", lambda: tmp_path)
    monkeypatch.setattr(session_cli, "ensure_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(session_cli, "session_socket_path", lambda: tmp_path / "session.sock")
    monkeypatch.setattr(session_cli, "session_pid_path", lambda: tmp_path / "session.pid")
    monkeypatch.setattr(session_cli, "daemon_log_path", lambda sid: tmp_path / f"{sid}.log")
    monkeypatch.setattr(session_cli, "session_artifact_dir", lambda sid: tmp_path / sid)
    monkeypatch.setattr(session_cli, "generate_session_id", lambda: "sess-1")
    monkeypatch.setattr(session_cli, "write_current_session", lambda sid: None)
    monkeypatch.setattr(session_cli, "_select_udid", lambda u, **kw: u or "device-1")

    # Pretend daemon becomes ready on first poll after spawn.
    poll_calls = {"n": 0}

    def fake_daemon_running():
        poll_calls["n"] += 1
        return poll_calls["n"] > 1  # First call (in start) = False, second (after spawn) = True

    monkeypatch.setattr(session_cli, "_daemon_running", fake_daemon_running)

    def fake_popen(cmd, **kw):
        return _FakeProc(cmd, **kw)

    monkeypatch.setattr(session_cli.subprocess, "Popen", fake_popen)

    session_cli.start(**kwargs)
    return _FakeProc.last.command


def test_session_start_with_server_url_skips_start_server(monkeypatch, tmp_path) -> None:
    called = []
    monkeypatch.setattr(session_cli, "start_server", lambda *a, **k: called.append(True) or None)

    cmd = _capture_session_start(
        monkeypatch, tmp_path,
        server_url="http://host.docker.internal:4723",
        port=None, udid="device-1", allow_adb_shell=True,
        enable_network_log=False, json_output=False,
    )

    assert called == []
    assert "--server-url" in cmd
    assert cmd[cmd.index("--server-url") + 1] == "http://host.docker.internal:4723"
    # External non-loopback URL -> no --adb-fallback.
    assert "--adb-fallback" not in cmd


def test_session_start_honors_env_when_no_flags(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APPIUM_SERVER_URL", "http://host.docker.internal:4723/")
    called = []
    monkeypatch.setattr(session_cli, "start_server", lambda *a, **k: called.append(True) or None)

    cmd = _capture_session_start(
        monkeypatch, tmp_path,
        server_url=None, port=None, udid="device-1",
        allow_adb_shell=True, enable_network_log=False, json_output=False,
    )

    assert called == []
    # Trailing slash normalized.
    assert cmd[cmd.index("--server-url") + 1] == "http://host.docker.internal:4723"


def test_session_start_explicit_port_overrides_env(monkeypatch, tmp_path) -> None:
    from appium_cli.cli.server import ServerState

    monkeypatch.setenv("APPIUM_SERVER_URL", "http://host.docker.internal:4723")
    state = ServerState(True, "self", 4725, "http://127.0.0.1:4725", pid=1, shell_capable=True)
    monkeypatch.setattr(session_cli, "start_server", lambda port, **k: state)

    cmd = _capture_session_start(
        monkeypatch, tmp_path,
        server_url=None, port=4725, udid="device-1",
        allow_adb_shell=True, enable_network_log=False, json_output=False,
    )
    assert cmd[cmd.index("--server-url") + 1] == "http://127.0.0.1:4725"


def test_session_start_url_warns_when_port_also_supplied(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(session_cli, "start_server", lambda *a, **k: None)

    cmd = _capture_session_start(
        monkeypatch, tmp_path,
        server_url="http://host.docker.internal:4723", port=4725, udid="device-1",
        allow_adb_shell=True, enable_network_log=False, json_output=False,
    )

    err = capsys.readouterr().err
    assert "ignored" in err
    assert cmd[cmd.index("--server-url") + 1] == "http://host.docker.internal:4723"


def test_session_start_rejects_invalid_url(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(session_cli, "_daemon_running", lambda: False)
    monkeypatch.setattr(session_cli, "ensure_app_dir", lambda: tmp_path)
    monkeypatch.setattr(session_cli, "ensure_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(session_cli, "session_socket_path", lambda: tmp_path / "s.sock")
    monkeypatch.setattr(session_cli, "session_pid_path", lambda: tmp_path / "s.pid")
    monkeypatch.setattr(session_cli, "session_artifact_dir", lambda sid: tmp_path / sid)
    monkeypatch.setattr(session_cli, "generate_session_id", lambda: "sess-bad")

    with pytest.raises(typer.Exit):
        session_cli.start(
            server_url="ftp://x", port=None, udid="device-1",
            allow_adb_shell=True, enable_network_log=False, json_output=False,
        )


def test_session_start_external_loopback_enables_adb_fallback(monkeypatch, tmp_path) -> None:
    # Loopback URL is treated as external by user choice; daemon should still get --adb-fallback.
    monkeypatch.setattr(session_cli, "start_server", lambda *a, **k: None)
    cmd = _capture_session_start(
        monkeypatch, tmp_path,
        server_url="http://127.0.0.1:4723", port=None, udid="device-1",
        allow_adb_shell=True, enable_network_log=False, json_output=False,
    )
    assert "--adb-fallback" in cmd


def test_select_udid_external_server_no_adb_gives_helpful_error(monkeypatch) -> None:
    """When external server is used and adb is unavailable, error should mention --udid."""
    monkeypatch.setattr(session_cli, "list_android_devices", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("adb was not found on PATH")))

    with pytest.raises(RuntimeError, match="--udid"):
        session_cli._select_udid(None, external_server=True)


def test_select_udid_external_server_with_explicit_udid(monkeypatch) -> None:
    """Explicit --udid should bypass adb enumeration entirely."""
    assert session_cli._select_udid("my-device", external_server=True) == "my-device"


def test_select_udid_local_server_no_adb_raises_original_error(monkeypatch) -> None:
    """Without external_server flag, the original FileNotFoundError propagates."""
    monkeypatch.setattr(session_cli, "list_android_devices", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("adb was not found on PATH")))

    with pytest.raises(FileNotFoundError, match="adb was not found"):
        session_cli._select_udid(None, external_server=False)
