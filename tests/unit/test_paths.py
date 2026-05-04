"""Tests for appium_cli.utils.paths helpers."""

import json
import re

from appium_cli.utils.paths import (
    clear_current_session,
    generate_session_id,
    read_current_session,
    screenshot_path,
    session_artifact_dir,
    session_log_path,
    write_current_session,
)


def test_generate_session_id_format():
    sid = generate_session_id()
    assert sid.startswith("session-")
    # e.g. session-2026-05-04T02-18-02-171Z
    assert re.match(r"session-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z$", sid)


def test_session_artifact_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    sid = "session-2026-05-04T02-18-02-171Z"
    d = session_artifact_dir(sid)
    assert d == tmp_path / sid


def test_session_log_path(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    sid = "session-2026-05-04T02-18-02-171Z"
    p = session_log_path(sid)
    assert p == tmp_path / f"{sid}.log"


def test_screenshot_path_format(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    sid = "session-test"
    p = screenshot_path(sid)
    assert str(p).startswith(str(tmp_path / sid / "screenshot-"))
    assert str(p).endswith(".png")


def test_current_session_read_write_clear(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    assert read_current_session() is None

    write_current_session("session-abc")
    assert read_current_session() == "session-abc"

    clear_current_session()
    assert read_current_session() is None
