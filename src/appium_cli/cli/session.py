"""Session daemon commands."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

import typer

from appium_cli.cli.server import (
    DEFAULT_PORT,
    ServerState,
    resolve_external_url,
    start_server,
)
from appium_cli.daemon.client import request
from appium_cli.utils import exit_codes
from appium_cli.utils.adb import list_android_devices
from appium_cli.utils.paths import (
    clear_current_session,
    daemon_log_path,
    ensure_app_dir,
    ensure_runtime_dir,
    generate_session_id,
    read_current_session,
    session_artifact_dir,
    session_pid_path,
    session_socket_path,
    write_current_session,
)


app = typer.Typer(help="Manage the persistent Appium WebDriver session daemon.")


def _echo_json(payload: dict) -> None:
    typer.echo(json.dumps(payload, indent=2))


def _path_exists_safe(path: Path) -> bool:
    """Return True if path exists; treat OSError as not-exists.

    Some filesystems (notably virtiofs on Docker Desktop devcontainers) can
    raise OSError on stat() of leftover socket entries. Treat those as absent
    so daemon lifecycle checks remain usable.
    """
    try:
        return path.exists()
    except OSError:
        return False


def _unlink_safe(path: Path) -> None:
    """Unlink a path, ignoring missing-file and unsupported-FS errors."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _daemon_running() -> bool:
    if not _path_exists_safe(session_socket_path()):
        return False
    try:
        response = request("ping")
        return bool(response.get("ok"))
    except Exception:
        return False


def _read_pid() -> int | None:
    try:
        return int(session_pid_path().read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _select_udid(explicit_udid: str | None, *, external_server: bool = False) -> str:
    if explicit_udid:
        return explicit_udid
    try:
        devices = [device for device in list_android_devices() if device.status == "device"]
    except (FileNotFoundError, RuntimeError) as exc:
        if external_server:
            raise RuntimeError(
                "Cannot enumerate Android devices (adb not available). "
                "Specify the device with --udid when using --server-url."
            ) from exc
        raise
    if not devices:
        raise RuntimeError("No connected Android device with status 'device' was found")
    return devices[0].udid


def _validate_external_url(value: str) -> str:
    """Validate and normalize an external Appium server URL."""
    try:
        parsed = urlparse(value)
    except Exception as exc:
        raise ValueError(f"Invalid server URL: {value}") from exc
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"Invalid server URL '{value}': scheme must be http:// or https://"
        )
    if not parsed.hostname:
        raise ValueError(f"Invalid server URL '{value}': missing host")
    return value.rstrip("/")


def _extract_port(url: str) -> int:
    try:
        parsed = urlparse(url)
        if parsed.port:
            return parsed.port
        return 443 if parsed.scheme == "https" else 80
    except Exception:
        return DEFAULT_PORT


def _is_loopback_url(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


@app.command("status")
def status(
    json_output: Annotated[bool, typer.Option("--json", help="Print structured JSON output.")] = False,
) -> None:
    """Show daemon/WebDriver session status."""

    try:
        response = request("get_driver_status")
    except (FileNotFoundError, ConnectionError, OSError, RuntimeError) as exc:
        if json_output:
            _echo_json({"ok": False, "running": False, "error": "Session daemon is not running", "detail": str(exc), "exit_code": exit_codes.STOPPED})
        else:
            typer.echo("running: false")
        raise typer.Exit(exit_codes.STOPPED)

    data = response.get("data", {})
    if not response.get("ok") or not data.get("ready", response.get("text") == "Driver is initialized and ready"):
        if json_output:
            _echo_json({"ok": False, "running": False, "status": response.get("text", ""), "data": data, "exit_code": exit_codes.STOPPED})
        else:
            typer.echo("running: false")
        raise typer.Exit(exit_codes.STOPPED)

    if json_output:
        _echo_json({"ok": True, "running": True, **data})
        return

    typer.echo("running: true")
    typer.echo(f"session_id: {data.get('session_id', 'unknown')}")
    typer.echo(f"udid: {data.get('udid', 'unknown')}")
    typer.echo(f"server_url: {data.get('server_url', 'unknown')}")
    shell = data.get("shell_capable", "unknown")
    typer.echo(f"shell_capable: {str(shell).lower() if isinstance(shell, bool) else shell}")


@app.command("start")
def start(
    port: Annotated[int | None, typer.Option("--port", help="Appium server port (local mode).")] = None,
    server_url: Annotated[
        str | None,
        typer.Option(
            "--server-url",
            help="Connect to an external Appium server (e.g. http://host.docker.internal:4723). Overrides --port and APPIUM_SERVER_URL.",
        ),
    ] = None,
    udid: Annotated[str | None, typer.Option("--udid", help="Android device UDID.")] = None,
    allow_adb_shell: Annotated[
        bool,
        typer.Option("--allow-adb-shell/--no-allow-adb-shell", help="Allow mobile: shell when starting Appium."),
    ] = True,
    enable_network_log: Annotated[
        bool,
        typer.Option("--enable-network-log", help="Enable network request logging (goog:loggingPrefs)."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print structured JSON output.")] = False,
) -> None:
    """Start the daemon-owned WebDriver session."""

    if _daemon_running():
        # Fetch full session details so callers get udid/server_url.
        try:
            resp = request("get_driver_status")
            data = resp.get("data", {}) if resp.get("ok") else {}
        except Exception:
            data = {}
        if json_output:
            _echo_json({"ok": True, "already_running": True, "running": True, **data})
            return
        typer.echo("Session daemon is already running.")
        return

    # Resolve effective server location with precedence:
    #   1. explicit --server-url
    #   2. explicit --port (local)
    #   3. APPIUM_SERVER_URL env (external)
    #   4. default local port 4723
    effective_url: str | None = None
    if server_url is not None:
        if port is not None:
            typer.echo(
                f"WARNING: --port {port} is ignored because --server-url was supplied.",
                err=True,
            )
        try:
            effective_url = _validate_external_url(server_url)
        except ValueError as exc:
            if json_output:
                _echo_json({"ok": False, "error": str(exc), "exit_code": exit_codes.GENERAL_ERROR})
            else:
                typer.echo(f"ERROR: {exc}", err=True)
            raise typer.Exit(exit_codes.GENERAL_ERROR) from exc
    elif port is None:
        # No explicit --port: honor APPIUM_SERVER_URL env if set.
        env_url = resolve_external_url()
        if env_url is not None:
            effective_url = env_url

    app_dir = ensure_app_dir()
    ensure_runtime_dir()
    sid = generate_session_id()
    artifact_dir = session_artifact_dir(sid)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    _unlink_safe(session_socket_path())
    if (pid := _read_pid()) and not _pid_running(pid):
        _unlink_safe(session_pid_path())

    try:
        if effective_url is not None:
            server_state = ServerState(
                running=True,
                ownership="external",
                port=_extract_port(effective_url),
                url=effective_url,
                pid=None,
                shell_capable=None,
            )
        else:
            local_port = port if port is not None else DEFAULT_PORT
            server_state = start_server(port=local_port, allow_adb_shell=allow_adb_shell)
        selected_udid = _select_udid(udid, external_server=(effective_url is not None))
    except Exception as exc:
        if json_output:
            _echo_json({"ok": False, "error": str(exc), "exit_code": exit_codes.GENERAL_ERROR})
        else:
            typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(exit_codes.GENERAL_ERROR) from exc

    command = [
        sys.executable,
        "-m",
        "appium_cli.daemon.entry",
        "--server-url",
        server_state.url,
        "--udid",
        selected_udid,
        "--app-dir",
        str(app_dir.resolve()),
    ]
    # Only enable adb fallback for self-owned local servers. External hosts
    # (including host.docker.internal host-Appium) handle adb themselves.
    if server_state.ownership == "external" and _is_loopback_url(server_state.url):
        command.append("--adb-fallback")
    if enable_network_log:
        command.append("--enable-network-log")

    log_file = daemon_log_path(sid).open("ab")
    process = subprocess.Popen(
        command,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    deadline = time.time() + 60
    while time.time() < deadline:
        if process.poll() is not None:
            message = f"session daemon exited early with code {process.returncode}. See {daemon_log_path(sid)}"
            if json_output:
                _echo_json({"ok": False, "error": message, "exit_code": exit_codes.GENERAL_ERROR, "daemon_returncode": process.returncode, "log_path": str(daemon_log_path(sid))})
            else:
                typer.echo(f"ERROR: {message}", err=True)
            raise typer.Exit(exit_codes.GENERAL_ERROR)
        if _daemon_running():
            write_current_session(sid)
            if json_output:
                _echo_json({"ok": True, "started": True, "running": True, "udid": selected_udid, "pid": process.pid, "session_id": sid, "server_url": server_state.url})
                return
            typer.echo(f"Started session daemon for {selected_udid} (pid={process.pid}, session={sid})")
            return
        time.sleep(0.5)

    process.terminate()
    message = f"session daemon did not become ready. See {daemon_log_path(sid)}"
    if json_output:
        _echo_json({"ok": False, "error": message, "exit_code": exit_codes.GENERAL_ERROR, "log_path": str(daemon_log_path(sid))})
    else:
        typer.echo(f"ERROR: {message}", err=True)
    raise typer.Exit(exit_codes.GENERAL_ERROR)


@app.command("stop")
def stop(
    json_output: Annotated[bool, typer.Option("--json", help="Print structured JSON output.")] = False,
) -> None:
    """Stop the daemon-owned WebDriver session."""

    if not _daemon_running():
        if json_output:
            _echo_json({"ok": True, "running": False, "stopped": False, "message": "Session daemon is not running."})
            return
        typer.echo("Session daemon is not running.")
        return
    response = request("shutdown")
    if not response.get("ok"):
        if json_output:
            _echo_json({"ok": False, "error": response.get("error", "shutdown failed"), "exit_code": response.get("exit_code", exit_codes.GENERAL_ERROR)})
        else:
            typer.echo(f"ERROR: {response.get('error', 'shutdown failed')}", err=True)
        raise typer.Exit(response.get("exit_code", exit_codes.GENERAL_ERROR))

    deadline = time.time() + 15
    pid = _read_pid()
    while pid and time.time() < deadline:
        if not _pid_running(pid):
            break
        time.sleep(0.2)

    # Force-terminate the daemon if it is still alive after the graceful window.
    # This can happen when driver.quit() hangs (e.g. because a prior webview_switch
    # left Appium holding a broken ChromeDriver process).  Without this kill the
    # orphaned daemon keeps running and races with any subsequent session start,
    # which can crash the host Appium server.
    if pid and _pid_running(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        kill_deadline = time.time() + 3
        while _pid_running(pid) and time.time() < kill_deadline:
            time.sleep(0.1)
        if _pid_running(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    _unlink_safe(session_socket_path())
    _unlink_safe(session_pid_path())
    clear_current_session()
    if json_output:
        _echo_json({"ok": True, "running": False, "stopped": True, "pid": pid})
        return
    typer.echo("Stopped session daemon.")
