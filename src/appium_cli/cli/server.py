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

import typer

from appium_cli.utils import exit_codes
from appium_cli.utils.paths import ensure_app_dir, server_log_path, server_state_path


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


def _status_url(port: int) -> str:
    return f"{_url(port)}/status"


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


def get_status(port: int = 4723) -> ServerState:
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


def start_server(port: int = 4723, allow_adb_shell: bool = True, chromedriver_autodownload: bool = True) -> ServerState:
    current = get_status(port)
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
    port: Annotated[int, typer.Option("--port", help="Appium server port.")] = 4723,
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
    port: Annotated[int, typer.Option("--port", help="Appium server port.")] = 4723,
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


@app.command("stop")
def stop(
    json_output: Annotated[bool, typer.Option("--json", help="Print structured JSON output.")] = False,
) -> None:
    """Stop only the Appium server started by appium-cli."""

    saved = _read_state()
    if saved.get("ownership") != "self":
        if json_output:
            _echo_json({"ok": True, "stopped": False, "ownership": saved.get("ownership", "none"), "message": "No self-owned Appium server to stop."})
            return
        typer.echo("No self-owned Appium server to stop.")
        return

    pid = saved.get("pid")
    if not isinstance(pid, int) or not _pid_running(pid):
        server_state_path().unlink(missing_ok=True)
        if json_output:
            _echo_json({"ok": True, "stopped": True, "already_stopped": True, "pid": pid})
            return
        typer.echo("Self-owned Appium server is already stopped.")
        return

    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 10
    while time.time() < deadline:
        if not _pid_running(pid):
            server_state_path().unlink(missing_ok=True)
            if json_output:
                _echo_json({"ok": True, "stopped": True, "pid": pid})
                return
            typer.echo("Stopped self-owned Appium server.")
            return
        time.sleep(0.2)

    message = f"Appium process {pid} did not stop after SIGTERM"
    if json_output:
        _echo_json({"ok": False, "error": message, "pid": pid, "exit_code": exit_codes.GENERAL_ERROR})
    else:
        typer.echo(f"ERROR: {message}", err=True)
    raise typer.Exit(exit_codes.GENERAL_ERROR)
