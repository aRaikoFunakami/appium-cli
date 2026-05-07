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
