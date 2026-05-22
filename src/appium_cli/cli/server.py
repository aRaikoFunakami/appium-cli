"""Appium server singleton commands."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from shutil import which
from typing import Annotated, Literal
from urllib.parse import urlparse

import typer

from appium_cli.daemon.client import request as _daemon_request
from appium_cli.utils import exit_codes
from appium_cli.utils.paths import (
    clear_current_session,
    ensure_app_dir,
    server_log_path,
    server_state_path,
    session_pid_path,
    session_socket_path,
)


DEFAULT_PORT = 4723
EXTERNAL_URL_ENV = "APPIUM_SERVER_URL"

Ownership = Literal["self", "external", "none"]


app = typer.Typer(help="Manage the singleton Appium server.")


@dataclass
class ServerState:
    running: bool
    ownership: Ownership
    port: int
    url: str
    pid: int | None = None
    shell_capable: bool | None = None


def _url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _status_url_for(base_url: str) -> str:
    return base_url.rstrip("/") + "/status"


def _status_url(port: int) -> str:
    return _status_url_for(_url(port))


def resolve_external_url() -> str | None:
    """Return a normalized external Appium URL from APPIUM_SERVER_URL, if set."""
    raw = os.environ.get(EXTERNAL_URL_ENV, "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return raw.rstrip("/")


def _url_responds(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(_status_url_for(url), timeout=timeout) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def _read_state() -> dict:
    if not server_state_path().exists():
        return {}
    try:
        return json.loads(server_state_path().read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_state(state: ServerState) -> None:
    ensure_app_dir()
    server_state_path().write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def _state_payload(state: ServerState) -> dict:
    return asdict(state)


def _echo_json(payload: dict) -> None:
    typer.echo(json.dumps(payload, indent=2))


def _server_responds(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(_status_url(port), timeout=timeout) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def _pid_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _get_local_status(port: int) -> ServerState:
    """Status of a local Appium server only (ignores APPIUM_SERVER_URL)."""
    saved = _read_state()
    saved_port = int(saved.get("port", port))
    running = _server_responds(saved_port)
    if running:
        ownership: Ownership = "self" if saved.get("ownership") == "self" and _pid_running(saved.get("pid")) else "external"
        return ServerState(
            running=True,
            ownership=ownership,
            port=saved_port,
            url=_url(saved_port),
            pid=saved.get("pid") if ownership == "self" else None,
            shell_capable=saved.get("shell_capable"),
        )
    return ServerState(running=False, ownership="none", port=port, url=_url(port), shell_capable=None)


def get_status(port: int = DEFAULT_PORT) -> ServerState:
    # If APPIUM_SERVER_URL is set, report the external server's reachability.
    external_url = resolve_external_url()
    if external_url is not None:
        try:
            parsed = urlparse(external_url)
            ext_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except Exception:
            ext_port = port
        running = _url_responds(external_url)
        return ServerState(
            running=running,
            ownership="external" if running else "none",
            port=ext_port,
            url=external_url,
            pid=None,
            shell_capable=None,
        )

    return _get_local_status(port)


def start_server(port: int = DEFAULT_PORT, allow_adb_shell: bool = True, chromedriver_autodownload: bool = True) -> ServerState:
    # start_server is for self-owned local servers; ignore APPIUM_SERVER_URL here.
    current = _get_local_status(port)
    if current.running:
        _write_state(current)
        return current

    appium_bin = which("appium")
    if not appium_bin:
        raise RuntimeError("appium was not found on PATH")

    ensure_app_dir()
    command = [appium_bin, "--port", str(port)]
    insecure_features: list[str] = []
    if allow_adb_shell:
        insecure_features.append("uiautomator2:adb_shell")
    if chromedriver_autodownload:
        insecure_features.append("uiautomator2:chromedriver_autodownload")
    if insecure_features:
        command.extend(["--allow-insecure", ",".join(insecure_features)])

    log_file = server_log_path().open("ab")
    process = subprocess.Popen(
        command,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Appium exited early with code {process.returncode}. See {server_log_path()}")
        if _server_responds(port):
            state = ServerState(
                running=True,
                ownership="self",
                port=port,
                url=_url(port),
                pid=process.pid,
                shell_capable=allow_adb_shell,
            )
            _write_state(state)
            return state
        time.sleep(0.5)

    process.terminate()
    raise RuntimeError(f"Appium did not become ready. See {server_log_path()}")


@app.command("status")
def status(
    port: Annotated[int, typer.Option("--port", help="Appium server port.")] = DEFAULT_PORT,
    json_output: Annotated[bool, typer.Option("--json", help="Print structured JSON output.")] = False,
) -> None:
    """Show Appium server status."""

    state = get_status(port)
    if json_output:
        payload = {"ok": state.running, **_state_payload(state)}
        if not state.running:
            payload["exit_code"] = exit_codes.STOPPED
        _echo_json(payload)
        if not state.running:
            raise typer.Exit(exit_codes.STOPPED)
        return

    typer.echo(f"running: {str(state.running).lower()}")
    typer.echo(f"ownership: {state.ownership}")
    typer.echo(f"port: {state.port}")
    typer.echo(f"url: {state.url}")
    typer.echo(f"pid: {state.pid if state.pid is not None else 'unknown'}")
    shell = "unknown" if state.shell_capable is None else str(state.shell_capable).lower()
    typer.echo(f"shell_capable: {shell}")
    if not state.running:
        raise typer.Exit(exit_codes.STOPPED)


@app.command("start")
def start(
    port: Annotated[int, typer.Option("--port", help="Appium server port.")] = DEFAULT_PORT,
    allow_adb_shell: Annotated[
        bool,
        typer.Option(
            "--allow-adb-shell/--no-allow-adb-shell",
            help="Allow Appium mobile: shell when this command starts a new server.",
        ),
    ] = True,
    chromedriver_autodownload: Annotated[
        bool,
        typer.Option(
            "--chromedriver-autodownload/--no-chromedriver-autodownload",
            help="Allow Appium to download a matching Chromedriver for Chrome/WebView automation when this command starts a new server.",
        ),
    ] = True,
    json_output: Annotated[bool, typer.Option("--json", help="Print structured JSON output.")] = False,
) -> None:
    """Start or reuse the singleton Appium server."""

    # Host/external Appium mode: do not start a local server.
    external_url = resolve_external_url()
    if external_url is not None:
        if not _url_responds(external_url):
            message = (
                f"External Appium server at {external_url} (from {EXTERNAL_URL_ENV}) "
                f"is not reachable. Start it on the host first."
            )
            if json_output:
                _echo_json({"ok": False, "error": message, "url": external_url, "exit_code": exit_codes.GENERAL_ERROR})
            else:
                typer.echo(f"ERROR: {message}", err=True)
            raise typer.Exit(exit_codes.GENERAL_ERROR)
        try:
            parsed = urlparse(external_url)
            ext_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except Exception:
            ext_port = port
        ext_state = ServerState(
            running=True,
            ownership="external",
            port=ext_port,
            url=external_url,
            pid=None,
            shell_capable=None,
        )
        if json_output:
            _echo_json({
                "ok": True,
                "already_running": True,
                "started": False,
                "external": True,
                **_state_payload(ext_state),
            })
            return
        typer.echo(
            f"Host/external Appium mode detected ({EXTERNAL_URL_ENV}={external_url}); "
            f"use `appium-cli session start` directly."
        )
        return

    current = get_status(port)
    try:
        state = start_server(port, allow_adb_shell, chromedriver_autodownload)
    except RuntimeError as exc:
        if json_output:
            _echo_json({"ok": False, "error": str(exc), "exit_code": exit_codes.GENERAL_ERROR})
        else:
            typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(exit_codes.GENERAL_ERROR) from exc

    if current.running:
        if json_output:
            _echo_json({"ok": True, "already_running": True, "started": False, **_state_payload(state)})
            return
        typer.echo(f"Appium server already running at {state.url} (ownership={state.ownership})")
        return

    if json_output:
        _echo_json({"ok": True, "already_running": False, "started": True, **_state_payload(state)})
        return
    typer.echo(f"Started Appium server at {state.url} (pid={state.pid})")


def _unlink_safe(path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _stop_daemon_if_running() -> bool:
    """Gracefully stop the session daemon if it is running.

    Returns True if a daemon was found and stopped (or killed), False if
    no daemon was running.
    """
    sock = session_socket_path()
    try:
        alive = sock.exists()
    except OSError:
        alive = False
    if not alive:
        return False

    try:
        response = _daemon_request("ping")
        if not response.get("ok"):
            return False
    except (FileNotFoundError, ConnectionError, OSError, RuntimeError, json.JSONDecodeError):
        return False

    try:
        _daemon_request("shutdown")
    except (FileNotFoundError, ConnectionError, OSError, RuntimeError, json.JSONDecodeError):
        pass

    pid: int | None = None
    try:
        pid = int(session_pid_path().read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        pass

    deadline = time.time() + 15
    while pid and time.time() < deadline:
        if not _pid_running(pid):
            break
        time.sleep(0.2)

    if pid and _pid_running(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    _unlink_safe(sock)
    _unlink_safe(session_pid_path())
    clear_current_session()
    return True


@app.command("stop")
def stop(
    json_output: Annotated[bool, typer.Option("--json", help="Print structured JSON output.")] = False,
) -> None:
    """Stop the session daemon (if running) then the Appium server started by appium-cli."""

    daemon_stopped = _stop_daemon_if_running()
    if daemon_stopped:
        if json_output:
            pass  # report daemon_stopped in final payload below
        else:
            typer.echo("Stopped session daemon.")

    saved = _read_state()
    if saved.get("ownership") != "self":
        if json_output:
            _echo_json({"ok": True, "stopped": False, "daemon_stopped": daemon_stopped, "ownership": saved.get("ownership", "none"), "message": "No self-owned Appium server to stop."})
            return
        typer.echo("No self-owned Appium server to stop.")
        return

    pid = saved.get("pid")
    if not isinstance(pid, int) or not _pid_running(pid):
        server_state_path().unlink(missing_ok=True)
        if json_output:
            _echo_json({"ok": True, "stopped": True, "already_stopped": True, "daemon_stopped": daemon_stopped, "pid": pid})
            return
        typer.echo("Self-owned Appium server is already stopped.")
        return

    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 10
    while time.time() < deadline:
        if not _pid_running(pid):
            server_state_path().unlink(missing_ok=True)
            if json_output:
                _echo_json({"ok": True, "stopped": True, "daemon_stopped": daemon_stopped, "pid": pid})
                return
            typer.echo("Stopped self-owned Appium server.")
            return
        time.sleep(0.2)

    message = f"Appium process {pid} did not stop after SIGTERM"
    if json_output:
        _echo_json({"ok": False, "error": message, "daemon_stopped": daemon_stopped, "pid": pid, "exit_code": exit_codes.GENERAL_ERROR})
    else:
        typer.echo(f"ERROR: {message}", err=True)
    raise typer.Exit(exit_codes.GENERAL_ERROR)
