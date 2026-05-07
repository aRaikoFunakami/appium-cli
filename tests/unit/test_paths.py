"""Tests for appium_cli.utils.paths helpers."""

import json
import re

from appium_cli.utils.paths import (
    clear_current_session,
    generate_snapshot_id,
    generate_session_id,
    latest_snapshot_path,
    read_current_session,
    screenshot_path,
    session_artifact_dir,
    session_log_path,
    snapshot_artifact_dir,
    snapshot_artifact_path,
    snapshot_bundle_paths,
    write_json_artifact,
    write_latest_snapshot_pointer,
    write_text_artifact,
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


def test_generate_snapshot_id_format():
    snapshot_id = generate_snapshot_id("web", "a3f2c1")
    assert re.match(
        r"web-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z-a3f2c1$",
        snapshot_id,
    )


def test_snapshot_artifact_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    assert snapshot_artifact_dir() == tmp_path / "snapshots"


def test_snapshot_artifact_path(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    assert snapshot_artifact_path("web-123", "meta") == (
        tmp_path / "snapshots" / "web-123.meta.json"
    )
    assert snapshot_artifact_path("web-123", "compact") == (
        tmp_path / "snapshots" / "web-123.compact.yml"
    )
    assert snapshot_artifact_path("web-123", "full") == (
        tmp_path / "snapshots" / "web-123.full.yml"
    )
    assert snapshot_artifact_path("web-123", "refs") == (
        tmp_path / "snapshots" / "web-123.refs.json"
    )
    assert snapshot_artifact_path("web-123", "index") == (
        tmp_path / "snapshots" / "web-123.index.json"
    )


def test_snapshot_artifact_path_rejects_unknown_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    try:
        snapshot_artifact_path("web-123", "unknown")
    except ValueError as exc:
        assert "Unknown snapshot artifact" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_snapshot_bundle_paths(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    paths = snapshot_bundle_paths("native-123")
    assert set(paths) == {"meta", "compact", "full", "refs", "index"}
    assert paths["meta"] == tmp_path / "snapshots" / "native-123.meta.json"


def test_latest_snapshot_paths(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    assert latest_snapshot_path() == tmp_path / "snapshots" / "latest.json"
    assert latest_snapshot_path(source="native") == (
        tmp_path / "snapshots" / "latest-native.json"
    )
    assert latest_snapshot_path(source="web", context="WEBVIEW_chrome") == (
        tmp_path / "snapshots" / "latest-web-WEBVIEW_chrome.json"
    )


def test_write_snapshot_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    json_path = tmp_path / "snapshots" / "sample.json"
    text_path = tmp_path / "snapshots" / "sample.yml"

    write_json_artifact(json_path, {"z": 1, "name": "検索"})
    write_text_artifact(text_path, "screen: sample\n")

    assert json.loads(json_path.read_text(encoding="utf-8")) == {"name": "検索", "z": 1}
    assert text_path.read_text(encoding="utf-8") == "screen: sample\n"


def test_write_latest_snapshot_pointer(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    metadata = {"snapshot_id": "web-123", "context": "WEBVIEW_chrome"}

    write_latest_snapshot_pointer(metadata, source="web", context="WEBVIEW_chrome")

    assert json.loads((tmp_path / "snapshots" / "latest.json").read_text()) == metadata
    assert json.loads(
        (tmp_path / "snapshots" / "latest-web-WEBVIEW_chrome.json").read_text()
    ) == metadata


def test_current_session_read_write_clear(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    assert read_current_session() is None

    write_current_session("session-abc")
    assert read_current_session() == "session-abc"

    clear_current_session()
    assert read_current_session() is None
