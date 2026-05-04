import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from appium_cli.daemon.client import request
from appium_cli.daemon.server import serve


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
