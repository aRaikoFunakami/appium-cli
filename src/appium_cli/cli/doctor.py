"""Read-only environment diagnostics."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Annotated, Literal
from urllib.parse import urlparse

import typer

from appium_cli.utils import exit_codes


Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    message: str
    hint: str = ""


def _run(command: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str] | None:
    if shutil.which(command[0]) is None:
        return None
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _binary_check(name: str, command: str, version_args: list[str] | None = None) -> Check:
    path = shutil.which(command)
    if not path:
        return Check(name, "FAIL", f"{command} was not found on PATH", f"Install {command} and update PATH.")
    if not version_args:
        return Check(name, "PASS", path)
    try:
        result = _run([command, *version_args])
    except Exception as exc:
        return Check(name, "WARN", f"{command} exists at {path}, but version check failed: {exc}")
    if result and result.returncode == 0:
        version = (result.stdout or result.stderr).strip().splitlines()
        suffix = f" ({version[0]})" if version else ""
        return Check(name, "PASS", f"{path}{suffix}")
    return Check(name, "WARN", f"{command} exists at {path}, but version check failed")


def _env_dir_check(name: str, env_name: str) -> Check:
    value = os.environ.get(env_name)
    if not value:
        return Check(name, "FAIL", f"{env_name} is not set", f"Export {env_name} before using appium-cli.")
    if not os.path.isdir(value):
        return Check(name, "FAIL", f"{env_name} points to a missing directory: {value}")
    return Check(name, "PASS", f"{env_name}={value}")


def _appium_driver_checks() -> list[Check]:
    if shutil.which("appium") is None:
        return [
            Check("Appium driver uiautomator2", "FAIL", "appium command is unavailable"),
            Check("Appium driver xcuitest", "WARN", "appium command is unavailable"),
        ]
    try:
        result = _run(["appium", "driver", "list", "--installed"], timeout=20.0)
    except Exception as exc:
        return [Check("Appium drivers", "WARN", f"Could not list Appium drivers: {exc}")]
    if not result or result.returncode != 0:
        detail = result.stderr.strip() if result else "appium driver list failed"
        return [Check("Appium drivers", "WARN", detail)]
    output = result.stdout + result.stderr
    checks = []
    checks.append(
        Check(
            "Appium driver uiautomator2",
            "PASS" if "uiautomator2" in output else "FAIL",
            "uiautomator2 installed" if "uiautomator2" in output else "uiautomator2 is not installed",
            "Run appium driver install uiautomator2 outside appium-cli.",
        )
    )
    checks.append(
        Check(
            "Appium driver xcuitest",
            "PASS" if "xcuitest" in output else "WARN",
            "xcuitest installed" if "xcuitest" in output else "xcuitest is not installed (needed only for iOS)",
            "Run appium driver install xcuitest outside appium-cli if you need iOS.",
        )
    )
    return checks


def _xcrun_check() -> Check:
    if platform.system() != "Darwin":
        return Check("xcrun", "WARN", "xcrun is only available on macOS; iOS device listing is disabled")
    return _binary_check("xcrun", "xcrun", ["--version"])


def _resolve_external_url() -> str | None:
    """Return a normalized external Appium URL from APPIUM_SERVER_URL, if set."""
    raw = os.environ.get("APPIUM_SERVER_URL", "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return raw.rstrip("/")


def _external_appium_check(url: str) -> Check:
    status_url = url.rstrip("/") + "/status"
    try:
        with urllib.request.urlopen(status_url, timeout=3.0) as resp:
            reachable = 200 <= resp.status < 500
    except (OSError, urllib.error.URLError):
        reachable = False
    if reachable:
        return Check("Appium (external)", "PASS", f"External Appium server reachable at {url}")
    return Check(
        "Appium (external)",
        "FAIL",
        f"External Appium server at {url} is not reachable",
        "Start Appium on the host with: appium --allow-insecure uiautomator2:adb_shell",
    )


def _checks() -> list[Check]:
    external_url = _resolve_external_url()
    if external_url is not None:
        # Host/external Appium mode: Appium, Android SDK, and Java live on the
        # host machine, not in this container.  Only verify reachability.
        return [
            _binary_check("Node.js", "node", ["--version"]),
            _binary_check("npm", "npm", ["--version"]),
            _external_appium_check(external_url),
            _binary_check("adb", "adb", ["version"]),
            _xcrun_check(),
        ]
    return [
        _binary_check("Node.js", "node", ["--version"]),
        _binary_check("npm", "npm", ["--version"]),
        _binary_check("Appium", "appium", ["--version"]),
        *_appium_driver_checks(),
        _env_dir_check("ANDROID_HOME", "ANDROID_HOME"),
        _env_dir_check("JAVA_HOME", "JAVA_HOME"),
        _binary_check("adb", "adb", ["version"]),
        _xcrun_check(),
    ]


def doctor(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON output."),
    ] = False,
) -> None:
    """Inspect the local Appium environment without changing it."""

    checks = _checks()
    ok = not any(check.status == "FAIL" for check in checks)
    if json_output:
        payload = {
            "ok": ok,
            "checks": [asdict(check) for check in checks],
        }
        if not ok:
            payload["exit_code"] = exit_codes.GENERAL_ERROR
        typer.echo(json.dumps(payload, indent=2))
        if not ok:
            raise typer.Exit(exit_codes.GENERAL_ERROR)
        return

    for check in checks:
        typer.echo(f"{check.status}: {check.name}: {check.message}")
        if check.hint and check.status in ("WARN", "FAIL"):
            typer.echo(f"  Hint: {check.hint}")

    if not ok:
        raise typer.Exit(exit_codes.GENERAL_ERROR)
