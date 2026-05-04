"""Best-effort iOS device observation helpers."""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass
from shutil import which


@dataclass(frozen=True)
class IOSDevice:
    udid: str
    name: str
    status: str
    model: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "platform": "ios",
            "udid": self.udid,
            "name": self.name,
            "status": self.status,
            "model": self.model,
        }


def xcrun_available() -> bool:
    return platform.system() == "Darwin" and which("xcrun") is not None


def list_ios_devices(timeout: float = 10.0) -> list[IOSDevice]:
    if platform.system() != "Darwin":
        return []
    if not xcrun_available():
        raise FileNotFoundError("xcrun was not found on PATH")

    result = subprocess.run(
        ["xcrun", "simctl", "list", "devices", "--json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "xcrun simctl failed"
        raise RuntimeError(message)

    payload = json.loads(result.stdout)
    devices: list[IOSDevice] = []
    for runtime_devices in payload.get("devices", {}).values():
        for item in runtime_devices:
            devices.append(
                IOSDevice(
                    udid=item.get("udid", ""),
                    name=item.get("name", ""),
                    status=item.get("state", ""),
                    model=item.get("deviceTypeIdentifier", ""),
                )
            )
    return devices
