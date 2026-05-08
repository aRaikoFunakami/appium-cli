"""Async context manager around the appium-cli session daemon.

This module never starts an Appium server itself and never installs
prerequisites. It only orchestrates the existing ``appium-cli session``
sub-commands, reusing a healthy daemon when available.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass

from agent_browser.config import AgentBrowserConfig

logger = logging.getLogger(__name__)


class AppiumSessionError(RuntimeError):
    """Raised when the appium-cli session cannot be brought to a usable state."""


@dataclass(slots=True)
class SessionInfo:
    """Captured information about the active session daemon."""

    running: bool
    udid: str | None = None
    server_url: str | None = None
    session_id: str | None = None
    started_by_us: bool = False
    raw: dict | None = None


async def _run_cli(*args: str, timeout: float = 60.0) -> tuple[int, str, str]:
    """Run an ``appium-cli`` command and return ``(returncode, stdout, stderr)``."""
    binary = shutil.which("appium-cli") or "appium-cli"
    proc = await asyncio.create_subprocess_exec(
        binary,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise AppiumSessionError(
            f"appium-cli {' '.join(args)} timed out after {timeout:.0f}s"
        ) from exc
    return proc.returncode or 0, stdout_b.decode("utf-8", errors="replace"), stderr_b.decode("utf-8", errors="replace")


def _parse_json(stdout: str) -> dict:
    stdout = stdout.strip()
    if not stdout:
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        # Fall back: locate first/last brace.
        first = stdout.find("{")
        last = stdout.rfind("}")
        if first >= 0 and last > first:
            try:
                return json.loads(stdout[first : last + 1])
            except json.JSONDecodeError:
                return {}
        return {}


class AppiumSessionManager:
    """Async context manager that ensures a healthy appium-cli session daemon."""

    def __init__(self, config: AgentBrowserConfig) -> None:
        self._config = config
        self._info: SessionInfo | None = None

    @property
    def info(self) -> SessionInfo | None:
        return self._info

    async def __aenter__(self) -> SessionInfo:
        self._info = await self._ensure_running()
        return self._info

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._info is None:
            return
        if not self._info.started_by_us:
            logger.debug("Leaving externally-owned appium-cli session running")
            return
        logger.info("Stopping appium-cli session daemon (started by us)")
        try:
            await self._stop()
        except AppiumSessionError as exc:
            logger.warning("Failed to stop appium-cli session: %s", exc)

    async def _status(self) -> SessionInfo:
        rc, stdout, stderr = await _run_cli("session", "status", "--json", timeout=15.0)
        payload = _parse_json(stdout)
        running = bool(payload.get("running"))
        return SessionInfo(
            running=running,
            udid=payload.get("udid"),
            server_url=payload.get("server_url"),
            session_id=payload.get("session_id"),
            raw=payload,
        )

    async def _start(self) -> SessionInfo:
        args: list[str] = ["session", "start", "--json", "--port", str(self._config.appium_port)]
        if self._config.udid:
            args.extend(["--udid", self._config.udid])
        rc, stdout, stderr = await _run_cli(*args, timeout=120.0)
        payload = _parse_json(stdout)
        if rc != 0 or not payload.get("ok"):
            error = payload.get("error") or stderr.strip() or stdout.strip() or f"appium-cli exited with {rc}"
            raise AppiumSessionError(f"Failed to start appium-cli session: {error}")

        # If the daemon was already running, the response may lack session
        # details.  Fall back to _status() to populate them.
        udid = payload.get("udid") or self._config.udid
        server_url = payload.get("server_url")
        session_id = payload.get("session_id")
        if not udid or not server_url:
            logger.debug("[session] start response missing fields, querying status")
            info = await self._status()
            if info.running:
                info.started_by_us = not payload.get("already_running", False)
                return info
            raise AppiumSessionError(
                "appium-cli session start reported ok but session is not ready "
                f"(udid={udid!r}, server_url={server_url!r})"
            )

        return SessionInfo(
            running=True,
            udid=udid,
            server_url=server_url,
            session_id=session_id,
            started_by_us=not payload.get("already_running", False),
            raw=payload,
        )

    async def _stop(self) -> None:
        rc, stdout, stderr = await _run_cli("session", "stop", "--json", timeout=30.0)
        payload = _parse_json(stdout)
        if rc != 0 and not payload.get("ok"):
            error = payload.get("error") or stderr.strip() or f"appium-cli exited with {rc}"
            raise AppiumSessionError(f"Failed to stop appium-cli session: {error}")

    async def _ensure_running(self) -> SessionInfo:
        info = await self._status()
        if info.running:
            logger.info(
                "Reusing existing appium-cli session: udid=%s server=%s",
                info.udid,
                info.server_url,
            )
            return info

        logger.info("Starting appium-cli session daemon (port=%d)", self._config.appium_port)
        return await self._start()
