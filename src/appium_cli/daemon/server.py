"""Unix socket JSON-RPC server for the session daemon."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any, Callable

from appium_cli.daemon import state
from appium_cli.tools.session import format_driver_status, is_driver_alive
from appium_cli.utils import exit_codes
from appium_cli.utils.paths import (
    ensure_app_dir,
    ensure_runtime_dir,
    session_pid_path,
    session_socket_path,
)


Handler = Callable[[dict[str, Any]], dict[str, Any]]


def _default_handler(request: dict[str, Any]) -> dict[str, Any]:
    tool = request.get("tool")
    if tool == "ping":
        return {"text": "pong", "data": {"session": state.session_metadata}}
    if tool == "get_driver_status":
        ready = is_driver_alive()
        return {"text": format_driver_status(ready), "data": {"initialized": state.driver is not None, "ready": ready}}
    raise KeyError(f"Unknown tool: {tool}")


def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    explicit_ok = result.get("ok")
    if explicit_ok is False:
        response = {
            "id": request_id,
            "ok": False,
            "error": result.get("error") or result.get("text", ""),
            "exit_code": result.get("exit_code", exit_codes.GENERAL_ERROR),
        }
        if "detail" in result:
            response["detail"] = result["detail"]
        if "data" in result:
            response["data"] = result["data"]
        if "text" in result:
            response["text"] = result["text"]
        return response

    text = result.get("text", "")
    if isinstance(text, str) and text.startswith("FAILED:"):
        return {"id": request_id, "ok": False, "error": text, "exit_code": exit_codes.GENERAL_ERROR}
    return {
        "id": request_id,
        "ok": True,
        "text": text,
        "data": result.get("data", {}),
    }


def _error(request_id: Any, exc: Exception, exit_code: int = exit_codes.GENERAL_ERROR) -> dict[str, Any]:
    return {"id": request_id, "ok": False, "error": str(exc), "exit_code": getattr(exc, "exit_code", exit_code)}


def _send_response(connection: socket.socket, response_payload: dict[str, Any]) -> bool:
    try:
        connection.sendall((json.dumps(response_payload) + "\n").encode("utf-8"))
    except (BrokenPipeError, ConnectionResetError, OSError):
        return False
    return True


def _unlink_safe(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def serve(
    socket_path: Path | None = None,
    handler: Handler = _default_handler,
) -> None:
    """Serve JSON-RPC requests until a shutdown request is received."""

    if socket_path is None:
        socket_path = session_socket_path()
    pid_path = session_pid_path()

    ensure_app_dir()
    ensure_runtime_dir()
    _unlink_safe(socket_path)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")
    shutdown = False

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        try:
            server.bind(str(socket_path))
        except OSError as exc:
            _unlink_safe(pid_path)
            raise OSError(
                f"Failed to bind Unix domain socket at {socket_path}. "
                f"Filesystem may not support Unix sockets (e.g. virtiofs). "
                f"Underlying error: {exc}"
            ) from exc
        server.listen(8)
        while not shutdown:
            connection, _ = server.accept()
            with connection:
                reader = connection.makefile("r", encoding="utf-8")
                raw = reader.readline()
                if not raw:
                    continue
                request_payload: dict[str, Any] | None = None
                try:
                    request_payload = json.loads(raw)
                    if request_payload.get("tool") == "shutdown":
                        shutdown = True
                        response_payload = _response(request_payload.get("id"), {"text": "shutdown", "data": {}})
                    else:
                        response_payload = _response(request_payload.get("id"), handler(request_payload))
                except Exception as exc:
                    response_payload = _error(request_payload.get("id") if request_payload else None, exc)
                _send_response(connection, response_payload)

    _unlink_safe(socket_path)
    _unlink_safe(pid_path)
