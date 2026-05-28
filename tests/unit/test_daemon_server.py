import io
import json
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from appium_cli.daemon.client import request
from appium_cli.daemon.server import _send_response, serve


def test_daemon_json_rpc_ping_and_shutdown(monkeypatch) -> None:
    temp_dir = TemporaryDirectory(dir="/tmp")
    temp_path = Path(temp_dir.name)
    socket_path = temp_path / "session.sock"
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: temp_path)

    thread = threading.Thread(target=serve, kwargs={"socket_path": socket_path}, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while not socket_path.exists() and time.time() < deadline:
        time.sleep(0.05)

    ping = request("ping", socket_path=socket_path)
    assert ping["ok"] is True
    assert ping["text"] == "pong"

    shutdown = request("shutdown", socket_path=socket_path)
    assert shutdown["ok"] is True
    thread.join(timeout=5)
    assert not thread.is_alive()
    temp_dir.cleanup()


class BrokenConnection:
    def sendall(self, _payload: bytes) -> None:
        raise BrokenPipeError("client disconnected")


def test_send_response_ignores_client_disconnect() -> None:
    assert _send_response(BrokenConnection(), {"id": "1", "ok": True}) is False


def test_client_request_includes_raw_flag(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return False

        def connect(self, path: str) -> None:
            captured["path"] = path

        def sendall(self, payload: bytes) -> None:
            captured["payload"] = json.loads(payload.decode("utf-8"))

        def makefile(self, *_args, **_kwargs):
            return io.StringIO('{"ok": true, "text": "OK", "data": {}}\n')

    monkeypatch.setattr("socket.socket", lambda *_args, **_kwargs: FakeSocket())

    response = request("snapshot", args={"scope": "full"}, socket_path=Path("session.sock"), raw=True)

    assert response["ok"] is True
    assert captured["path"] == "session.sock"
    assert captured["payload"]["tool"] == "snapshot"
    assert captured["payload"]["args"] == {"scope": "full"}
    assert captured["payload"]["raw"] is True


def test_response_converts_failed_string_to_error():
    """Compatibility: FAILED: strings should produce ok=False responses."""
    from appium_cli.daemon.server import _response
    resp = _response("req-1", {"text": "FAILED: element not found", "data": {}})
    assert resp["ok"] is False
    assert resp["error"] == "FAILED: element not found"
    assert "exit_code" in resp


def test_response_passes_success_as_ok():
    from appium_cli.daemon.server import _response
    resp = _response("req-2", {"text": "OK", "data": {}})
    assert resp["ok"] is True
    assert resp["text"] == "OK"


def test_response_preserves_explicit_failure_data():
    from appium_cli.daemon.server import _response
    resp = _response(
        "req-3",
        {
            "ok": False,
            "text": "AUTO_REFRESHED_REF_MISSING: choose a new ref",
            "error": "AUTO_REFRESHED_REF_MISSING: choose a new ref",
            "data": {"auto_refreshed": True, "action_executed": False},
        },
    )
    assert resp["ok"] is False
    assert resp["error"].startswith("AUTO_REFRESHED_REF_MISSING")
    assert resp["text"].startswith("AUTO_REFRESHED_REF_MISSING")
    assert resp["data"] == {"auto_refreshed": True, "action_executed": False}


def test_serve_raises_clear_error_when_bind_fails(monkeypatch, tmp_path) -> None:
    """Bind failure surfaces the attempted socket path and underlying error."""
    import socket as socket_module
    import pytest as _pytest
    from appium_cli.daemon.server import serve

    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setenv("APPIUM_CLI_RUNTIME_DIR", str(tmp_path / "runtime"))

    real_socket = socket_module.socket

    class FailingSocket(real_socket):
        def bind(self, _addr):  # type: ignore[override]
            raise OSError("Operation not supported")

    monkeypatch.setattr(socket_module, "socket", FailingSocket)

    sock_path = tmp_path / "runtime" / "session.sock"
    with _pytest.raises(OSError) as exc_info:
        serve(socket_path=sock_path)

    assert str(sock_path) in str(exc_info.value)
    assert "virtiofs" in str(exc_info.value)


def test_unlink_safe_in_server_module(tmp_path) -> None:
    from appium_cli.daemon.server import _unlink_safe
    _unlink_safe(tmp_path / "missing")  # should not raise
