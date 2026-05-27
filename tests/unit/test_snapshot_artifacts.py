"""Tests for snapshot artifact bundle serialization."""

from __future__ import annotations

import json

from appium_cli.core.native_snapshot import NativeSnapshot, NativeSnapshotNode
from appium_cli.core.snapshot import LocatorStrategy
from appium_cli.core.snapshot_artifacts import (
    compute_snapshot_stats,
    create_snapshot_bundle_payload,
)
from appium_cli.core.web_snapshot import WebSnapshot, WebSnapshotNode


def test_native_snapshot_bundle_serializes_metadata_refs_and_index(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    button = NativeSnapshotNode(
        role="button",
        name="OK",
        ref="ok",
        bounds=(1, 2, 3, 4),
        strategies=[LocatorStrategy(by="id", value="com.example:id/ok")],
        state=["enabled"],
    )
    list_node = NativeSnapshotNode(
        role="list",
        ref="recycler",
        container_kind="list",
        scrollable=True,
        scroll_direction="vertical",
        bounds=(0, 10, 100, 200),
        children=[button],
    )
    snap = NativeSnapshot.from_root(
        root=NativeSnapshotNode(role="container", children=[list_node]),
        app_info="com.example/.MainActivity",
    )

    bundle = create_snapshot_bundle_payload(snap, snapshot_id="native-fixed")

    assert bundle.snapshot_id == "native-fixed"
    assert bundle.paths["meta"] == tmp_path / "snapshots" / "native-fixed.meta.json"
    assert bundle.meta_json["source"] == "native"
    assert bundle.meta_json["context"] == "NATIVE_APP"
    assert bundle.meta_json["screen_id"] == snap.screen_id
    assert set(bundle.artifacts()) == {"meta", "compact", "full", "refs", "index"}
    assert "screen_id:" in bundle.compact_yml
    assert "bounds=(1, 2, 3, 4)" not in bundle.compact_yml
    assert "bounds=(1, 2, 3, 4)" in bundle.full_yml

    refs = bundle.refs_json["refs"]
    assert refs["ok"]["strategies"] == [
        {"by": "id", "value": "com.example:id/ok"}
    ]
    assert refs["ok"]["expected_bounds"] == [1, 2, 3, 4]
    assert refs["ok"]["source_type"] == "native"
    json.dumps(bundle.refs_json)

    assert bundle.index_json["node_count"] == 3
    assert bundle.index_json["ref_count"] == 2
    assert bundle.index_json["roles"]["button"] == 1
    assert bundle.index_json["refs"][0]["ref"] == "recycler"
    assert bundle.index_json["refs"][1]["primary_strategy"] == {
        "by": "id",
        "value": "com.example:id/ok",
    }
    assert bundle.index_json["containers"][0]["container_kind"] == "list"
    assert bundle.index_json["containers"][0]["scroll_direction"] == "vertical"


def test_web_snapshot_bundle_includes_title_url_and_textbox_index(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    snap = WebSnapshot.from_root(
        context="WEBVIEW_chrome",
        title="Example",
        url="https://example.com",
        root=WebSnapshotNode(
            role="document",
            name="Example",
            children=[
                WebSnapshotNode(
                    role="textbox",
                    name="Search",
                    ref="web_search",
                    value="query",
                    bounds=(10, 20, 110, 60),
                    strategies=[LocatorStrategy(by="css selector", value="#search")],
                )
            ],
        ),
    )

    bundle = create_snapshot_bundle_payload(snap, snapshot_id="web-fixed")

    assert bundle.meta_json["source"] == "web"
    assert bundle.meta_json["context"] == "WEBVIEW_chrome"
    assert bundle.meta_json["title"] == "Example"
    assert bundle.meta_json["url"] == "https://example.com"
    assert bundle.refs_json["refs"]["web_search"]["context"] == "WEBVIEW_chrome"
    assert bundle.refs_json["refs"]["web_search"]["strategies"] == [
        {"by": "css selector", "value": "#search"}
    ]
    assert bundle.index_json["title"] == "Example"
    assert bundle.index_json["url"] == "https://example.com"
    assert bundle.index_json["inputs"] == [
        {
            "ref": "web_search",
            "role": "textbox",
            "name": "Search",
            "bounds": [10, 20, 110, 60],
            "actionable": True,
            "editable": True,
            "value": "query",
        }
    ]
    assert "title: Example" in bundle.compact_yml
    json.dumps(bundle.index_json)


def test_compute_snapshot_stats_counts_index_roles() -> None:
    stats = compute_snapshot_stats(
        {
            "node_count": 12,
            "ref_count": 5,
            "roles": {"link": 3, "heading": 2, "button": 1, "textbox": 4},
            "inputs": [{"ref": "search"}, {"ref": "email"}],
            "containers": [{"ref": "list"}],
        }
    )

    assert stats == {
        "nodes": 12,
        "refs": 5,
        "links": 3,
        "headings": 2,
        "buttons": 1,
        "textboxes": 2,
        "containers": 1,
    }
