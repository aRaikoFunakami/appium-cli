import json
import subprocess

import pytest


pytestmark = pytest.mark.e2e


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["appium-cli", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _has_android_device() -> bool:
    result = _run("devices", "--platform=android", "--json", check=False)
    if result.returncode != 0:
        return False
    payload = json.loads(result.stdout)
    return any(device["status"] == "device" for device in payload["devices"])


def test_android_session_get_device_info_smoke() -> None:
    if not _has_android_device():
        pytest.skip("No connected Android device with status 'device'")

    doctor = _run("doctor", check=False)
    assert doctor.returncode in {0, 1}
    assert "Node.js" in doctor.stdout

    status = _run("server", "status", check=False)
    external_running = status.returncode == 0 and "ownership: external" in status.stdout

    try:
        start = _run("server", "start", "--port=4723", check=False)
        assert start.returncode == 0

        session_start = _run("session", "start", check=False)
        assert session_start.returncode == 0, session_start.stderr

        info = _run("get_device_info")
        assert "Device Information:" in info.stdout
        assert "Model:" in info.stdout
        assert "Android Version:" in info.stdout

        snapshot = _run("snapshot")
        assert "screen_id:" in snapshot.stdout
        assert "[ref:" in snapshot.stdout

        containers = _run("list_containers")
        assert "Containers on screen" in containers.stdout

        current = _run("get_current_app")
        assert "Current app package:" in current.stdout

        visible = _run("assert_visible", "--text", "Home", check=False)
        assert visible.returncode == 0
        assert "visible=" in visible.stdout

        found = _run("find_element", "xpath", "//*")
        assert "Successfully found element" in found.stdout

        key = _run("press_key", "enter")
        assert "OK" in key.stdout

        legacy_key = _run("press_keycode", "66")
        assert "Successfully pressed keycode 66" in legacy_key.stdout
    finally:
        _run("session", "stop", check=False)
        stop = _run("server", "stop", check=False)
        assert stop.returncode == 0

    if external_running:
        after = _run("server", "status", check=False)
        assert after.returncode == 0
        assert "ownership: external" in after.stdout
