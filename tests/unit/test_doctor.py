from pathlib import Path

from appium_cli.cli.doctor import _env_dir_check


def test_env_dir_check_passes_for_existing_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path))
    check = _env_dir_check("ANDROID_HOME", "ANDROID_HOME")
    assert check.status == "PASS"


def test_env_dir_check_fails_for_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    check = _env_dir_check("ANDROID_HOME", "ANDROID_HOME")
    assert check.status == "FAIL"
    assert "not set" in check.message
