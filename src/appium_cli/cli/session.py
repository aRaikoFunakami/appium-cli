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

import typer

from appium_cli.cli.server import start_server
from appium_cli.daemon.client import request
from appium_cli.utils import exit_codes
from appium_cli.utils.adb import list_android_devices
from appium_cli.utils.paths import (
    clear_current_session,
    daemon_log_path,
    ensure_app_dir,
    generate_session_id,
    read_current_session,
    session_artifact_dir,
    session_pid_path,
    session_socket_path,
    write_current_session,
)


app = typer.Typer(help="Manage the persistent Appium WebDriver session daemon.")


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _daemon_running() -> bool:
    if not session_socket_path().exists():
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


def _select_udid(explicit_udid: str | None) -> str:
    if explicit_udid:
        return explicit_udid
    devices = [device for device in list_android_devices() if device.status == "device"]
    if not devices:
        raise RuntimeError("No connected Android device with status 'device' was found")
    return devices[0].udid


@app.command("status")
def status() -> None:
    """Show daemon/WebDriver session status."""

    if not _daemon_running():
        typer.echo("running: false")
        raise typer.Exit(exit_codes.STOPPED)
    response = request("ping")
    data = response.get("data", {})
    typer.echo("running: true")
    typer.echo(f"session_id: {data.get('session_id', 'unknown')}")
    typer.echo(f"udid: {data.get('udid', 'unknown')}")
    typer.echo(f"server_url: {data.get('server_url', 'unknown')}")
    shell = data.get("shell_capable", "unknown")
    typer.echo(f"shell_capable: {str(shell).lower() if isinstance(shell, bool) else shell}")


@app.command("start")
def start(
    port: Annotated[int, typer.Option("--port", help="Appium server port.")] = 4723,
    udid: Annotated[str | None, typer.Option("--udid", help="Android device UDID.")] = None,
    allow_adb_shell: Annotated[
        bool,
        typer.Option("--allow-adb-shell/--no-allow-adb-shell", help="Allow mobile: shell when starting Appium."),
    ] = True,
) -> None:
    """Start the daemon-owned WebDriver session."""

    if _daemon_running():
        typer.echo("Session daemon is already running.")
        return

    app_dir = ensure_app_dir()
    sid = generate_session_id()
    artifact_dir = session_artifact_dir(sid)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    session_socket_path().unlink(missing_ok=True)
    if (pid := _read_pid()) and not _pid_running(pid):
        session_pid_path().unlink(missing_ok=True)

    try:
        server_state = start_server(port=port, allow_adb_shell=allow_adb_shell)
        selected_udid = _select_udid(udid)
    except Exception as exc:
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
    if server_state.ownership == "external":
        command.append("--adb-fallback")

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
            typer.echo(
                f"ERROR: session daemon exited early with code {process.returncode}. See {daemon_log_path(sid)}",
                err=True,
            )
            raise typer.Exit(exit_codes.GENERAL_ERROR)
        if _daemon_running():
            write_current_session(sid)
            typer.echo(f"Started session daemon for {selected_udid} (pid={process.pid}, session={sid})")
            return
        time.sleep(0.5)

    process.terminate()
    typer.echo(f"ERROR: session daemon did not become ready. See {daemon_log_path(sid)}", err=True)
    raise typer.Exit(exit_codes.GENERAL_ERROR)


@app.command("stop")
def stop() -> None:
    """Stop the daemon-owned WebDriver session."""

    if not _daemon_running():
        typer.echo("Session daemon is not running.")
        return
    response = request("shutdown")
    if not response.get("ok"):
        typer.echo(f"ERROR: {response.get('error', 'shutdown failed')}", err=True)
        raise typer.Exit(response.get("exit_code", exit_codes.GENERAL_ERROR))

    deadline = time.time() + 15
    pid = _read_pid()
    while pid and time.time() < deadline:
        if not _pid_running(pid):
            break
        time.sleep(0.2)
    session_socket_path().unlink(missing_ok=True)
    session_pid_path().unlink(missing_ok=True)
    clear_current_session()
    typer.echo("Stopped session daemon.")
