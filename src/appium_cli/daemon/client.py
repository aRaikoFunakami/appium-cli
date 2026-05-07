"""Unix socket JSON-RPC client for the session daemon."""

from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path
from typing import Any

from appium_cli.utils.paths import session_socket_path


def request(
    tool: str,
    args: dict[str, Any] | None = None,
    socket_path: Path | None = None,
    raw: bool = False,
) -> dict[str, Any]:
    if socket_path is None:
        socket_path = session_socket_path()
    payload = {"id": str(uuid.uuid4()), "tool": tool, "args": args or {}, "raw": raw}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        file = client.makefile("r", encoding="utf-8")
        line = file.readline()
    if not line:
        raise RuntimeError("daemon returned an empty response")
    return json.loads(line)
