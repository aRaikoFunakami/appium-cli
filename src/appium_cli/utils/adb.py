"""ADB command helpers."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from shutil import which


@dataclass(frozen=True)
class AndroidDevice:
    udid: str
    status: str
    model: str = ""
    device: str = ""
    product: str = ""
    transport_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "platform": "android",
            "udid": self.udid,
            "status": self.status,
            "model": self.model,
            "device": self.device,
            "product": self.product,
            "transport_id": self.transport_id,
        }


def adb_available() -> bool:
    return which("adb") is not None


def build_adb_base_cmd() -> list[str]:
    """Build adb command prefix, adding ``-L`` when ADB_SERVER_SOCKET is set.

    In devcontainer environments the env var is typically set to
    ``unix:/host-services/adb.socket`` so the adb client connects to the
    host's adb server. Modern adb honours the env var automatically, but
    older versions may ignore it; passing ``-L`` explicitly is reliable
    across all versions.
    """
    cmd = ["adb"]
    socket = os.environ.get("ADB_SERVER_SOCKET")
    if socket:
        cmd += ["-L", socket]
    return cmd


def parse_adb_devices(output: str) -> list[AndroidDevice]:
    devices: list[AndroidDevice] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices attached"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        udid, status = parts[0], parts[1]
        attrs: dict[str, str] = {}
        for token in parts[2:]:
            if ":" in token:
                key, value = token.split(":", 1)
                attrs[key] = value
        devices.append(
            AndroidDevice(
                udid=udid,
                status=status,
                model=attrs.get("model", ""),
                device=attrs.get("device", ""),
                product=attrs.get("product", ""),
                transport_id=attrs.get("transport_id", ""),
            )
        )
    return devices


def list_android_devices(timeout: float = 10.0) -> list[AndroidDevice]:
    if not adb_available():
        raise FileNotFoundError("adb was not found on PATH")
    result = subprocess.run(
        build_adb_base_cmd() + ["devices", "-l"],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "adb devices failed"
        raise RuntimeError(message)
    return parse_adb_devices(result.stdout)
