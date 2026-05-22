from pathlib import Path
from unittest.mock import patch

from appium_cli.cli.doctor import _checks, _env_dir_check, _external_appium_check


def test_env_dir_check_passes_for_existing_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path))
    check = _env_dir_check("ANDROID_HOME", "ANDROID_HOME")
    assert check.status == "PASS"


def test_env_dir_check_fails_for_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    check = _env_dir_check("ANDROID_HOME", "ANDROID_HOME")
    assert check.status == "FAIL"
    assert "not set" in check.message


def test_external_appium_check_pass_when_reachable() -> None:
    import urllib.request
    from unittest.mock import MagicMock

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__ = lambda s: mock_response
    mock_response.__exit__ = MagicMock(return_value=False)
    with patch.object(urllib.request, "urlopen", return_value=mock_response):
        check = _external_appium_check("http://host.docker.internal:4723")
    assert check.status == "PASS"
    assert "reachable" in check.message


def test_external_appium_check_fail_when_unreachable() -> None:
    import urllib.error

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        check = _external_appium_check("http://host.docker.internal:4723")
    assert check.status == "FAIL"
    assert "not reachable" in check.message


def test_checks_host_mode_skips_android_java(monkeypatch) -> None:
    """In host mode (APPIUM_SERVER_URL set) no ANDROID_HOME/JAVA_HOME checks."""
    monkeypatch.setenv("APPIUM_SERVER_URL", "http://host.docker.internal:4723")
    import urllib.error

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        checks = _checks()
    names = [c.name for c in checks]
    assert "ANDROID_HOME" not in names
    assert "JAVA_HOME" not in names
    assert "Appium (external)" in names
    assert "Appium" not in [n for n in names if n != "Appium (external)"]


def test_checks_local_mode_includes_android_java(monkeypatch) -> None:
    """In local mode (no APPIUM_SERVER_URL) all standard checks are present."""
    monkeypatch.delenv("APPIUM_SERVER_URL", raising=False)
    checks = _checks()
    names = [c.name for c in checks]
    assert "ANDROID_HOME" in names
    assert "JAVA_HOME" in names
    assert "Appium" in names
