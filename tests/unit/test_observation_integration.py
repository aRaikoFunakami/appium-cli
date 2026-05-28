"""Integration tests for observation and container tools using NativeSnapshot."""

from __future__ import annotations

import json
import shutil
from contextlib import nullcontext
from pathlib import Path


import pytest

from appium_cli.core.native_snapshot import NativeSnapshot, NativeSnapshotNode
from appium_cli.core.snapshot import LocatorStrategy, RefEntry
from appium_cli.core.snapshot_artifacts import create_snapshot_bundle_payload
from appium_cli.core.web_snapshot import WebSnapshot, WebSnapshotNode
from appium_cli.core.web_snapshot_generator import WEB_DEFAULT_MAX_DEPTH, WEB_DEFAULT_MAX_NODES
from appium_cli.daemon import state
from appium_cli.tools import actions, container, observation
from appium_cli.utils.errors import AppiumCliError


def _build_native_snapshot() -> NativeSnapshot:
    """Programmatic small native tree."""
    button = NativeSnapshotNode(
        role="button",
        name="OK",
        ref="ok",
        bounds=(100, 100, 300, 200),
        strategies=[LocatorStrategy(by="id", value="com.x:id/ok")],
        state=["enabled"],
    )
    text = NativeSnapshotNode(role="text", name="Hello", bounds=(50, 50, 200, 80))
    row = NativeSnapshotNode(
        role="row",
        name="Storage",
        ref="storage_row",
        bounds=(0, 300, 1080, 400),
        children=[
            NativeSnapshotNode(
                role="text",
                name="Storage",
                bounds=(20, 320, 200, 360),
                action_target_ref="storage_row",
            ),
            NativeSnapshotNode(
                role="text",
                name="32 GB free",
                bounds=(20, 360, 200, 380),
                action_target_ref="storage_row",
            ),
        ],
    )
    list_container = NativeSnapshotNode(
        role="list",
        ref="recycler",
        container_kind="list",
        scrollable=True,
        scroll_direction="vertical",
        bounds=(0, 200, 1080, 1800),
        children=[row],
    )
    root = NativeSnapshotNode(
        role="container",
        bounds=(0, 0, 1080, 1920),
        children=[text, button, list_container],
    )
    snapshot = NativeSnapshot.from_root(root=root, app_info="com.x/.MainActivity")
    state.ref_resolver.register_all(snapshot.to_ref_map())
    return snapshot


def setup_function(_func) -> None:
    state.reset()


class _FakeWebTextDriver:
    current_context = "WEBVIEW_chrome"

    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute_script(self, script, *args):
        self.calls.append((script, args))
        return self.result


def _install_snapshot_artifacts(monkeypatch, request, snapshot_id: str = "native-fixed") -> Path:
    app_dir = Path.cwd() / ".appium-cli-test-artifact-navigation"
    shutil.rmtree(app_dir, ignore_errors=True)
    request.addfinalizer(lambda: shutil.rmtree(app_dir, ignore_errors=True))
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: app_dir)
    bundle = create_snapshot_bundle_payload(
        _build_native_snapshot(), snapshot_id=snapshot_id
    )
    observation._write_snapshot_bundle(bundle)
    return app_dir


def _install_snapshot_artifacts_for(
    monkeypatch,
    request,
    snapshot: NativeSnapshot,
    snapshot_id: str = "native-fixed",
) -> Path:
    app_dir = Path.cwd() / f".appium-cli-test-{snapshot_id}"
    shutil.rmtree(app_dir, ignore_errors=True)
    request.addfinalizer(lambda: shutil.rmtree(app_dir, ignore_errors=True))
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: app_dir)
    bundle = create_snapshot_bundle_payload(snapshot, snapshot_id=snapshot_id)
    observation._write_snapshot_bundle(bundle)
    return app_dir


def _build_web_snapshot() -> WebSnapshot:
    btn = WebSnapshotNode(
        role="button",
        name="OK",
        ref="web_ok",
        bounds=(100, 100, 300, 200),
    )
    link = WebSnapshotNode(
        role="link",
        name="Home",
        ref="web_home_link",
        bounds=(0, 0, 200, 40),
    )
    root = WebSnapshotNode(role="document", name="Test", children=[link, btn])
    return WebSnapshot.from_root(root=root, context="WEBVIEW_chrome", title="Test", url="https://example.com")


def _install_web_snapshot_artifacts(monkeypatch, request, snapshot_id: str = "web-fixed") -> Path:
    app_dir = Path.cwd() / ".appium-cli-test-web-refs"
    shutil.rmtree(app_dir, ignore_errors=True)
    request.addfinalizer(lambda: shutil.rmtree(app_dir, ignore_errors=True))
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: app_dir)
    bundle = create_snapshot_bundle_payload(_build_web_snapshot(), snapshot_id=snapshot_id)
    observation._write_snapshot_bundle(bundle)
    return app_dir


def _build_duplicate_app_tabs_snapshot() -> NativeSnapshot:
    main_tabs = NativeSnapshotNode(
        role="list",
        ref="rv_tab_menu",
        scrollable=True,
        scroll_direction="vertical",
        bounds=(62, 82, 2012, 242),
        children=[
            NativeSnapshotNode(
                role="row",
                ref="tabbackground",
                bounds=(62, 82, 362, 242),
                children=[NativeSnapshotNode(role="text", name="ホーム", action_target_ref="tabbackground")],
            ),
            NativeSnapshotNode(
                role="row",
                ref="tabbackground_4",
                bounds=(962, 82, 1262, 242),
                children=[NativeSnapshotNode(role="text", name="アプリ", action_target_ref="tabbackground_4")],
            ),
            NativeSnapshotNode(
                role="row",
                ref="tabbackground_7",
                bounds=(1862, 82, 2012, 242),
                children=[NativeSnapshotNode(role="text", name="最近の項目", action_target_ref="tabbackground_7")],
            ),
        ],
    )
    sub_tabs = NativeSnapshotNode(
        role="list",
        bounds=(160, 378, 2400, 494),
        children=[
            NativeSnapshotNode(role="button", name="映画", ref="tabbtn"),
            NativeSnapshotNode(role="button", name="アプリ", ref="tabbtn_2"),
        ],
    )
    root = NativeSnapshotNode(
        role="container",
        bounds=(0, 0, 2560, 1600),
        children=[
            main_tabs,
            NativeSnapshotNode(role="button", ref="ib_search"),
            NativeSnapshotNode(role="button", ref="ib_settings"),
            sub_tabs,
            NativeSnapshotNode(role="button", name="編集", ref="btn_edit"),
            NativeSnapshotNode(role="text", name="アプリはありません"),
        ],
    )
    return NativeSnapshot.from_root(root=root, app_info="com.example/.Main")


def test_snapshot_metadata_includes_stats(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    bundle = create_snapshot_bundle_payload(
        _build_native_snapshot(), snapshot_id="native-fixed"
    )

    out = observation._format_artifact_metadata(bundle)

    assert "stats: 7 nodes, 3 refs, 1 buttons, 1 containers" in out


def test_web_text_formats_selected_text_and_metadata():
    driver = _FakeWebTextDriver(
        {
            "title": "Article",
            "url": "https://example.com/a",
            "selector": "article",
            "explicit_selector": False,
            "chars": 12000,
            "offset": 0,
            "limit": 6000,
            "returned": 6000,
            "truncated": True,
            "text": "本文です",
        }
    )
    state.driver = driver

    out = observation.web_text()

    assert "title: Article" in out
    assert "url: https://example.com/a" in out
    assert "selector: article" in out
    assert "truncated: true" in out
    assert out.endswith("本文です")
    assert driver.calls[0][1] == ("", 0, 6000)


def test_web_text_clamps_limit_and_supports_offset():
    driver = _FakeWebTextDriver(
        {
            "selector": "body",
            "chars": 20000,
            "offset": 300,
            "limit": 12000,
            "returned": 12000,
            "truncated": True,
            "text": "continued",
        }
    )
    state.driver = driver

    observation.web_text(selector="body", offset=300, limit=999999)

    assert driver.calls[0][1] == ("body", 300, 12000)


def test_web_text_raw_returns_json():
    driver = _FakeWebTextDriver(
        {
            "title": "Article",
            "url": "https://example.com/a",
            "selector": "main",
            "chars": 4,
            "offset": 0,
            "limit": 6000,
            "returned": 4,
            "truncated": False,
            "text": "text",
        }
    )
    state.driver = driver

    payload = json.loads(observation.web_text(raw=True))

    assert payload["selector"] == "main"
    assert payload["text"] == "text"


def test_native_action_returns_ok_without_snapshot(monkeypatch):
    """After removing _ok_with_snapshot, actions return plain 'OK'."""

    class FakeDriver:
        def __init__(self):
            self.keycodes: list[int] = []

        def press_keycode(self, keycode: int) -> None:
            self.keycodes.append(keycode)

    driver = FakeDriver()
    state.driver = driver
    state.current_context = "NATIVE_APP"
    monkeypatch.setattr(actions.time, "sleep", lambda _seconds: None)

    out = actions.press_key("back")

    assert driver.keycodes == [4]
    assert out == "OK"


def test_web_action_returns_ok_without_snapshot(monkeypatch):
    """After removing _ok_with_snapshot, web actions return plain 'OK'."""

    class FakeElement:
        def __init__(self):
            self.clicked = False

        def click(self) -> None:
            self.clicked = True

    element = FakeElement()
    state.driver = object()
    state.current_context = "WEBVIEW_1"
    monkeypatch.setattr(actions.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(actions, "_is_web_ref", lambda _ref: True)
    monkeypatch.setattr(actions, "_resolve_element", lambda _ref: element)
    monkeypatch.setattr(actions, "_ref_context", lambda _ref: "WEBVIEW_1")

    out = actions.tap("submit")

    assert element.clicked is True
    assert out == "OK"
    assert "snapshot_id:" not in out


# ---------------------------------------------------------------------------
# observation.describe
# ---------------------------------------------------------------------------


def test_describe_no_snapshot():
    state.current_snapshot = None
    assert "ERROR" in observation.describe("ok")


def test_describe_existing_ref():
    state.current_snapshot = _build_native_snapshot()
    out = observation.describe("ok")
    assert "role: button" in out
    assert "name: OK" in out
    assert "[ref:ok]" in out


def test_describe_missing_ref():
    state.current_snapshot = _build_native_snapshot()
    out = observation.describe("nope")
    assert "ERROR" in out
    assert "nope" in out


def test_describe_with_brackets_and_prefix():
    state.current_snapshot = _build_native_snapshot()
    assert observation.describe("[ref:ok]").startswith("element:")
    assert observation.describe("ref:ok").startswith("element:")


def test_describe_container_includes_subtree():
    state.current_snapshot = _build_native_snapshot()
    out = observation.describe("recycler")
    assert "subtree:" in out
    assert "storage_row" in out


# ---------------------------------------------------------------------------
# observation.find_by_text
# ---------------------------------------------------------------------------


def test_find_by_text_no_snapshot():
    state.current_snapshot = None
    assert "ERROR" in observation.find_by_text("anything")


def test_find_by_text_no_match():
    state.current_snapshot = _build_native_snapshot()
    assert "No elements" in observation.find_by_text("nonexistent")


def test_find_by_text_returns_action_target_for_pure_text():
    state.current_snapshot = _build_native_snapshot()
    out = observation.find_by_text("Storage")
    assert "Search results for 'Storage'" in out
    # row itself appears with its own ref
    assert "[ref:storage_row]" in out
    # the text leaf maps to action target
    assert "action target [ref:storage_row]" in out


def test_find_by_text_exact_match_scores_higher():
    state.current_snapshot = _build_native_snapshot()
    out = observation.find_by_text("OK")
    # button "OK" should match
    assert "[ref:ok]" in out
    assert 'score=100' in out


def test_find_by_text_inputs_only_returns_no_match():
    state.current_snapshot = _build_native_snapshot()
    out = observation.find_by_text("OK", scope="inputs")
    # No textbox in our tree, so no matches
    assert "No elements" in out


def test_find_by_text_shows_up_to_100_matches():
    root = NativeSnapshotNode(
        role="container",
        children=[
            NativeSnapshotNode(role="button", name="Item", ref=f"item{i}")
            for i in range(105)
        ],
    )
    state.current_snapshot = NativeSnapshot.from_root(root=root)

    out = observation.find_by_text("Item")

    assert "Search results for 'Item' (total=105, shown=100):" in out
    assert "[ref:item99]" in out
    assert "[ref:item100]" not in out
    assert "... 5 more matches not shown." in out


def test_snapshot_show_reads_latest_compact_artifact(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)

    out = observation.snapshot_show("latest")

    assert "screen_id:" in out
    assert "[ref:ok]" in out
    assert "bounds=(100, 100, 300, 200)" not in out


def test_snapshot_show_can_return_ref_detail(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)

    out = observation.snapshot_show("latest", ref="ok")

    assert "[ref:ok] button \"OK\"" in out
    assert "strategies:" in out
    assert "id: com.x:id/ok" in out


def test_snapshot_actionable_tree_distinguishes_duplicate_app_tabs():
    state.current_snapshot = _build_duplicate_app_tabs_snapshot()

    out = observation.snapshot_actionable_tree()

    assert "container" in out
    assert '  list [ref:rv_tab_menu] [scrollable:vertical]' in out
    assert '    row [ref:tabbackground_4] "アプリ"' in out
    assert '  list' in out
    assert '    button [ref:tabbtn_2] "アプリ"' in out
    assert "アプリはありません" not in out


def test_snapshot_actionable_tree_requires_current_snapshot():
    state.current_snapshot = None

    out = observation.snapshot_actionable_tree()

    assert out == "ERROR: No snapshot available. Run snapshot() first."


def test_snapshot_actionable_tree_webview_message():
    state.current_snapshot = WebSnapshot.from_root(
        context="WEBVIEW_chrome",
        title="Example",
        url="https://example.com",
        root=WebSnapshotNode(role="document", name="Example"),
    )

    out = observation.snapshot_actionable_tree()

    assert "WebView snapshots use the DOM tree" in out


def test_snapshot_actionable_tree_warns_when_stale():
    state.current_snapshot = _build_duplicate_app_tabs_snapshot()
    state.ref_resolver.clear_stale()
    state.ref_resolver.mark_stale(
        getattr(state.current_snapshot, "context", state.current_context),
        "scroll_up",
        ref="movies_section",
    )
    try:
        out = observation.snapshot_actionable_tree()
        assert "WARNING:" in out
        assert "scroll_up" in out
        assert "snapshot()" in out
    finally:
        state.ref_resolver.clear_stale()


def test_snapshot_actionable_tree_no_warning_when_fresh():
    state.current_snapshot = _build_duplicate_app_tabs_snapshot()
    state.ref_resolver.clear_stale()

    out = observation.snapshot_actionable_tree()

    assert "WARNING:" not in out


def test_snapshot_search_uses_artifacts_without_current_snapshot(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)
    state.current_snapshot = None

    out = observation.snapshot_search("storage")

    assert "Snapshot search results for 'storage'" in out
    assert '1. [ref:storage_row] row "Storage"' in out
    assert "actionable=true" in out
    assert "editable=false" in out
    assert 'snippet="- row \\"Storage\\" [ref:storage_row]"' in out


def test_snapshot_search_role_filter(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)

    out = observation.snapshot_search("storage", role="button")

    assert "Snapshot search results for 'storage'" in out
    assert 'text "Storage"' in out
    assert "tap_target=[ref:storage_row]" in out
    assert "target_role=row" in out
    assert "target_bounds=[0,300,1080,400]" in out
    assert "requested_role=button" in out
    assert "role_mismatch=true" in out
    assert "Native text targets may be tappable rows/tabs/containers" in out


def test_snapshot_search_text_target_without_direct_ref(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)

    out = observation.snapshot_search("32 GB free")
    raw = observation.snapshot_search("32 GB free", raw=True)
    payload = json.loads(raw)

    assert 'text "32 GB free"' in out
    assert "bounds=[20,360,200,380]" in out
    assert "tap_target=[ref:storage_row]" in out
    assert payload[0]["match_type"] == "text_target"
    assert payload[0]["action_target_ref"] == "storage_row"
    assert payload[0]["tap_target_ref"] == "storage_row"
    assert payload[0]["target_role"] == "row"


def test_snapshot_search_duplicate_label_includes_paths_and_warning(monkeypatch, request):
    snapshot = _build_duplicate_app_tabs_snapshot()
    _install_snapshot_artifacts_for(monkeypatch, request, snapshot, "duplicate-tabs")
    state.current_snapshot = snapshot
    state.current_snapshot_id = "duplicate-tabs"

    out = observation.snapshot_search("アプリ")

    assert 'path="container > list[rv_tab_menu] > row[tabbackground_4]"' in out
    assert 'path="container > list > button[tabbtn_2]"' in out
    assert "Ambiguous native label" in out
    assert "snapshot_actionable_tree()" in out


def test_snapshot_search_webview_role_filter_remains_strict(monkeypatch, tmp_path):
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    snap = WebSnapshot.from_root(
        context="WEBVIEW_chrome",
        title="Example",
        url="https://example.com",
        root=WebSnapshotNode(
            role="document",
            children=[
                WebSnapshotNode(
                    role="button",
                    name="News",
                    ref="web_news_button",
                    bounds=(0, 0, 100, 40),
                )
            ],
        ),
    )
    bundle = create_snapshot_bundle_payload(snap, snapshot_id="web-fixed")
    observation._write_snapshot_bundle(bundle)

    out = observation.snapshot_search("News", role="link")

    assert out == "No snapshot refs matching 'News' found."


def test_snapshot_search_or_matches_alternate_term(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)

    # "nonexistent" won't match, but "storage" (via any_text) will
    out = observation.snapshot_search("nonexistent", any_text=["storage"])

    assert "Snapshot search results for" in out
    assert '[ref:storage_row]' in out


def test_snapshot_search_or_deduplicates(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)

    # Both "storage" and "Storage" normalize to the same needle — ref appears once in ref results
    out = observation.snapshot_search("storage", any_text=["Storage"])

    # The ref match itself should appear exactly once (compact line fallback may also match)
    ref_matches = [line for line in out.splitlines() if line.strip().startswith(("1.", "2.", "3.")) and "[ref:storage_row]" in line]
    assert len(ref_matches) == 1


def test_snapshot_search_or_label_in_header(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)

    out = observation.snapshot_search("storage", any_text=["Login"])

    assert '"storage" OR "Login"' in out


def test_snapshot_search_or_raw_includes_matched_text(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)

    raw = observation.snapshot_search("nonexistent", any_text=["storage"], raw=True)
    data = json.loads(raw)

    assert len(data) > 0
    assert data[0]["matched_text"] == "storage"


def test_find_by_text_or_matches_alternate_term():
    state.current_snapshot = _build_native_snapshot()

    out = observation.find_by_text("nonexistent", any_text=["OK"])

    assert "Search results for" in out
    assert "[ref:ok]" in out


def test_find_by_text_or_deduplicates_keeps_best_score():
    state.current_snapshot = _build_native_snapshot()

    # "OK" matches exactly (score=100), "ok" also matches — should appear once with score=100
    out = observation.find_by_text("OK", any_text=["ok"])

    assert out.count("[ref:ok]") == 1
    assert "score=100" in out


def test_find_by_text_or_with_scope_inputs():
    state.current_snapshot = _build_native_snapshot()

    out = observation.find_by_text("OK", scope="inputs", any_text=["Storage"])

    # No textbox in our tree
    assert "No elements" in out


def test_find_by_text_or_label_in_header():
    state.current_snapshot = _build_native_snapshot()

    out = observation.find_by_text("OK", any_text=["Storage"])

    assert '"OK" OR "Storage"' in out


def test_web_refs_rejects_native_snapshot(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)

    result = observation.web_refs("latest")
    assert "ERROR" in result
    assert "web_refs is for WebView snapshots only" in result
    assert "snapshot_actionable_tree" in result


def test_web_refs_lists_filters_and_returns_raw_json(monkeypatch, request):
    _install_web_snapshot_artifacts(monkeypatch, request)

    listed = observation.web_refs("latest", role="button")
    assert "web_ok" in listed
    assert "web_home_link" not in listed

    raw = observation.web_refs("latest", raw=True)
    payload = json.loads(raw)
    assert payload["offset"] == 0
    assert payload["limit"] == 50
    assert payload["returned"] == payload["total"]
    refs = payload["refs"]
    assert {item["ref"] for item in refs} >= {"web_ok", "web_home_link"}


def test_web_refs_paginates_list_output(monkeypatch, request):
    _install_web_snapshot_artifacts(monkeypatch, request)

    first = observation.web_refs("latest", limit=1)

    assert "total=2" in first
    assert "returned=1" in first
    assert "offset=0" in first
    assert "limit=1" in first
    assert "More refs available: next_offset=1." in first

    second = observation.web_refs("latest", limit=1, offset=1)

    assert "returned=1" in second
    assert "offset=1" in second
    assert "More refs available" not in second


def test_web_refs_paginates_raw_json(monkeypatch, request):
    _install_web_snapshot_artifacts(monkeypatch, request)

    payload = json.loads(observation.web_refs("latest", limit=1, raw=True))

    assert payload["total"] == 2
    assert payload["returned"] == 1
    assert payload["has_more"] is True
    assert payload["next_offset"] == 1
    assert len(payload["refs"]) == 1


def test_web_refs_can_show_single_ref_as_raw_json(monkeypatch, request):
    _install_web_snapshot_artifacts(monkeypatch, request)

    raw = observation.web_refs("latest", "web_ok", raw=True)

    payload = json.loads(raw)
    assert payload["ref"] == "web_ok"
    assert payload["role"] == "button"


def test_generate_locator_prefers_latest_artifact_strategy(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)
    state.current_ref_map = {
        "ok": RefEntry(
            strategies=[LocatorStrategy(by="accessibility_id", value="stale")],
            expected_bounds=(0, 0, 0, 0),
            role="button",
            name="Stale",
        )
    }

    out = observation.generate_locator("ok")
    raw = observation.generate_locator("ok", raw=True)

    assert "best: id: com.x:id/ok" in out
    assert "locator: com.x:id/ok" in out
    assert raw == "com.x:id/ok"


def test_generate_locator_prefers_accessibility_for_native_current_map():
    state.current_ref_map = {
        "login": RefEntry(
            strategies=[
                LocatorStrategy(by="id", value="com.x:id/login"),
                LocatorStrategy(by="accessibility_id", value="Login"),
            ],
            expected_bounds=(0, 0, 0, 0),
            role="button",
            name="Login",
        )
    }

    assert observation.generate_locator("login", raw=True) == "Login"


def test_generate_locator_prefers_css_for_web_current_map():
    state.current_ref_map = {
        "web_submit": RefEntry(
            strategies=[
                LocatorStrategy(by="xpath", value="//*[@role='button' and normalize-space()='Submit']"),
                LocatorStrategy(by="css selector", value="#submit"),
            ],
            expected_bounds=(0, 0, 0, 0),
            role="button",
            name="Submit",
            context="CHROMIUM",
            source_type="web",
        )
    }

    assert observation.generate_locator("web_submit", raw=True) == "#submit"


class _FakeWebQueryDriver:
    current_context = "CHROMIUM"

    def __init__(self):
        self.calls: list[tuple[str, str, list[str], int]] = []

    def execute_script(self, script: str, selector: str, attrs: list[str], limit: int):
        self.calls.append((script, selector, attrs, limit))
        rows = [
            {
                "tag": "input",
                "role": "textbox",
                "accessible_name": "Search",
                "id": "q",
                "name": "q",
                "type": "search",
                "placeholder": "Search",
                "aria_label": "Search",
                "data_testid": "search-box",
                "value": "",
                "text": "",
                "href": "",
                "selector": "#q",
                "attrs": {"data-testid": "search-box"},
            },
            {
                "tag": "button",
                "role": "button",
                "accessible_name": "Search Web",
                "id": "",
                "name": "btnK",
                "type": "submit",
                "placeholder": "",
                "aria_label": "Search Web",
                "data_testid": "submit-button",
                "value": "Search",
                "text": "Search",
                "href": "",
                "selector": 'button[name="btnK"]',
                "attrs": {},
            },
            {
                "tag": "a",
                "role": "link",
                "accessible_name": "News",
                "id": "",
                "name": "",
                "type": "",
                "placeholder": "",
                "aria_label": "",
                "data_testid": "",
                "value": "",
                "text": "News",
                "href": "/news",
                "selector": 'a[href="/news"]',
                "attrs": {},
            },
        ]
        if selector == "input":
            return rows[:1]
        if selector == "button":
            return rows[1:2]
        if selector == "a":
            return rows[2:]
        return rows[:limit]


def test_web_query_returns_compact_output_and_maps_refs():
    driver = _FakeWebQueryDriver()
    state.driver = driver
    state.current_ref_map = {
        "web_q": RefEntry(
            strategies=[LocatorStrategy(by="css selector", value="#q")],
            expected_bounds=(0, 0, 0, 0),
            role="textbox",
            name="Search",
            context="CHROMIUM",
            source_type="web",
        )
    }

    out = observation.web_query("input", attrs="data-testid", limit=5)

    assert driver.calls == [(observation.WEB_QUERY_SCRIPT, "input", ["data-testid"], 5)]
    assert "Web query results for 'input' (total=1):" in out
    assert (
        "1. ref=web_q tag=input role=textbox accessible_name=Search selector=#q "
        "id=q name=q type=search placeholder=Search aria-label=Search data-testid=search-box"
    ) in out
    assert "data-testid=search-box" in out


def test_web_query_compact_output_includes_button_and_link_details():
    driver = _FakeWebQueryDriver()
    state.driver = driver
    state.current_ref_map = {}

    button_out = observation.web_query("button")
    link_out = observation.web_query("a")

    assert 'tag=button role=button accessible_name="Search Web"' in button_out
    assert 'selector="button[name=\\"btnK\\"]"' in button_out
    assert "name=btnK" in button_out
    assert "type=submit" in button_out
    assert "aria-label=\"Search Web\"" in button_out
    assert "data-testid=submit-button" in button_out
    assert "value=Search" in button_out
    assert "tag=a role=link accessible_name=News text=News" in link_out
    assert 'selector="a[href=\\"/news\\"]"' in link_out
    assert "href=/news" in link_out


def test_web_query_raw_returns_json_array():
    driver = _FakeWebQueryDriver()
    state.driver = driver
    state.current_ref_map = {}

    raw = observation.web_query("input", raw=True)

    payload = json.loads(raw)
    assert payload[0]["selector"] == "#q"
    assert payload[0]["data_testid"] == "search-box"
    assert payload[0]["value"] == ""
    assert payload[0]["attrs"]["data-testid"] == "search-box"


def test_web_query_attrs_use_dom_properties(monkeypatch):
    """web_query --attrs=checked should return DOM property boolean, not getAttribute string."""
    state.reset()

    class FakeDriver:
        current_url = "https://example.com"
        current_context = "WEBVIEW_1"

        def execute_script(self, script, *args):
            if "querySelectorAll" in script or "roleOf" in script:
                return [
                    {
                        "tag": "input",
                        "role": "checkbox",
                        "accessible_name": "Accept",
                        "id": "accept",
                        "name": "accept",
                        "type": "checkbox",
                        "placeholder": "",
                        "aria_label": "",
                        "data_testid": "",
                        "value": "",
                        "text": "",
                        "href": "",
                        "selector": "input#accept",
                        "attrs": {"checked": True, "disabled": False},
                    }
                ]
            return None

    state.driver = FakeDriver()
    state.current_context = "WEBVIEW_1"
    state.current_ref_map = {}
    monkeypatch.setattr("appium_cli.tools.observation.is_web_context", lambda ctx: True)

    out = observation.web_query("input[type=checkbox]", attrs="checked,disabled")
    # Boolean true/false should appear, not empty string from getAttribute
    assert "checked=true" in out
    assert "disabled=false" in out

    # raw JSON should preserve booleans
    raw = observation.web_query("input[type=checkbox]", attrs="checked,disabled", raw=True)
    payload = json.loads(raw)
    assert payload[0]["attrs"]["checked"] is True
    assert payload[0]["attrs"]["disabled"] is False


def test_container_output_limit_constants_match_contract():
    assert container.LIST_CONTAINERS_SAMPLE_LIMIT == 20
    assert container.WITHIN_CONTAINER_CANDIDATE_LIMIT == 100
    assert container.ASSERT_VISIBLE_MATCH_LIMIT == 100


def test_get_page_source_native_raw_option(monkeypatch):
    xml = (
        '<hierarchy index="0">'
        '<node text="" enabled="true" clickable="false" resource-id="id" />'
        "</hierarchy>"
    )

    class FakeDriver:
        page_source = xml

    state.driver = FakeDriver()
    monkeypatch.setattr(observation, "resolve_context", lambda context, driver: "NATIVE_APP")
    monkeypatch.setattr(
        observation,
        "using_context",
        lambda target, driver, restore=True: nullcontext(),
    )

    compressed = observation.get_page_source()

    assert compressed != xml
    assert "index" not in compressed
    assert "enabled" not in compressed
    assert "clickable" not in compressed
    assert observation.get_page_source(raw=True) == xml


# ---------------------------------------------------------------------------
# container.list_containers
# ---------------------------------------------------------------------------


def test_list_containers_no_snapshot():
    state.current_snapshot = None
    assert "ERROR" in container.list_containers()


def test_list_containers_lists_known_container():
    state.current_snapshot = _build_native_snapshot()
    out = container.list_containers()
    assert "[ref:recycler]" in out
    assert "list" in out
    assert "scrollable: yes (vertical)" in out


def test_list_containers_empty():
    root = NativeSnapshotNode(role="container", bounds=(0, 0, 100, 100))
    state.current_snapshot = NativeSnapshot.from_root(root=root)
    assert "コンテナが検出されませんでした" in container.list_containers()


def test_list_containers_shows_20_sample_children_and_remaining_count():
    children = [
        NativeSnapshotNode(role="row", name=f"Item {index}", ref=f"item_{index}")
        for index in range(1, 23)
    ]
    list_container = NativeSnapshotNode(
        role="list",
        ref="recycler",
        container_kind="list",
        children=children,
    )
    root = NativeSnapshotNode(role="container", children=[list_container])
    state.current_snapshot = NativeSnapshot.from_root(root=root)

    out = container.list_containers()

    assert "Item 20" in out
    assert "Item 21" not in out
    assert "... 2 more children not shown." in out


# ---------------------------------------------------------------------------
# container.find_container
# ---------------------------------------------------------------------------


def test_find_container_no_snapshot():
    state.current_snapshot = None
    assert "ERROR" in container.find_container("Storage")


def test_find_container_match():
    state.current_snapshot = _build_native_snapshot()
    out = container.find_container("Storage")
    assert "[ref:recycler]" in out
    assert "list" in out


def test_find_container_no_match():
    state.current_snapshot = _build_native_snapshot()
    out = container.find_container("nonexistent")
    assert "見つかりません" in out


def test_find_container_role_hint_mismatch():
    state.current_snapshot = _build_native_snapshot()
    out = container.find_container("Storage", role_hint="grid")
    assert "見つかりません" in out


# ---------------------------------------------------------------------------
# container.within_container
# ---------------------------------------------------------------------------


def test_within_container_no_snapshot():
    state.current_snapshot = None
    assert "ERROR" in container.within_container("recycler")


def test_within_container_returns_children():
    state.current_snapshot = _build_native_snapshot()
    out = container.within_container("recycler")
    assert "storage_row" in out


def test_within_container_unknown_ref():
    state.current_snapshot = _build_native_snapshot()
    out = container.within_container("not_there")
    assert "ERROR" in out


def test_within_container_role_filter_no_match():
    state.current_snapshot = _build_native_snapshot()
    out = container.within_container("recycler", role="button")
    assert "見つかりません" in out


def test_within_container_accepts_bracket_form():
    state.current_snapshot = _build_native_snapshot()
    out = container.within_container("[ref:recycler]")
    assert "storage_row" in out


def test_within_container_shows_100_candidates_and_remaining_count():
    children = [
        NativeSnapshotNode(role="row", name=f"Item {index}", ref=f"item_{index}")
        for index in range(1, 102)
    ]
    list_container = NativeSnapshotNode(
        role="list",
        ref="recycler",
        container_kind="list",
        children=children,
    )
    root = NativeSnapshotNode(role="container", children=[list_container])
    state.current_snapshot = NativeSnapshot.from_root(root=root)

    out = container.within_container("recycler")

    assert "[ref:item_100]" in out
    assert "[ref:item_101]" not in out
    assert "... 1 more candidates not shown." in out
    assert "→ Use tap(ref) with the desired ref." in out


# ---------------------------------------------------------------------------
# container.assert_visible
# ---------------------------------------------------------------------------


def test_assert_visible_requires_arg():
    state.current_snapshot = _build_native_snapshot()
    out = container.assert_visible()
    assert "ERROR" in out


def test_assert_visible_no_snapshot():
    state.current_snapshot = None
    assert "ERROR" in container.assert_visible(ref="ok")


def test_assert_visible_by_ref_found():
    state.current_snapshot = _build_native_snapshot()
    out = container.assert_visible(ref="ok")
    assert out.startswith("visible=true")
    assert "[ref:ok]" in out


def test_assert_visible_by_ref_not_found():
    state.current_snapshot = _build_native_snapshot()
    out = container.assert_visible(ref="missing")
    assert out.startswith("visible=false")


def test_assert_visible_by_ref_with_brackets():
    state.current_snapshot = _build_native_snapshot()
    out = container.assert_visible(ref="[ref:ok]")
    assert out.startswith("visible=true")


def test_assert_visible_by_text_found():
    state.current_snapshot = _build_native_snapshot()
    out = container.assert_visible(text="OK")
    assert "visible=true" in out


def test_assert_visible_by_text_not_found():
    state.current_snapshot = _build_native_snapshot()
    out = container.assert_visible(text="nonexistent")
    assert out.startswith("visible=false")


def test_assert_visible_by_text_action_target_suffix():
    state.current_snapshot = _build_native_snapshot()
    # The leaf "32 GB free" text has action target = storage_row
    out = container.assert_visible(text="32 GB free")
    assert "visible=true" in out
    assert "action target [ref:storage_row]" in out


def test_assert_visible_native_shows_100_matches_and_remaining_count():
    children = [
        NativeSnapshotNode(role="button", name="Target", ref=f"target_{index}")
        for index in range(1, 102)
    ]
    root = NativeSnapshotNode(role="container", children=children)
    state.current_snapshot = NativeSnapshot.from_root(root=root)

    out = container.assert_visible(text="Target")

    assert "[ref:target_100]" in out
    assert "[ref:target_101]" not in out
    assert "... 1 more matches not shown." in out


def test_assert_visible_web_shows_100_matches_and_remaining_count():
    children = [
        WebSnapshotNode(role="button", name="Target", ref=f"target_{index}")
        for index in range(1, 102)
    ]
    root = WebSnapshotNode(role="document", children=children)
    state.current_snapshot = WebSnapshot.from_root(root=root, context="WEBVIEW_1")

    out = container.assert_visible(text="Target")

    assert "[ref:target_100]" in out
    assert "[ref:target_101]" not in out
    assert "... 1 more matches not shown." in out


# ---------------------------------------------------------------------------
# observation.snapshot via fake driver (refresh path)
# ---------------------------------------------------------------------------


class _FakeDriver:
    def __init__(self, xml: str, package: str = "com.x", activity: str = ".Main"):
        self.page_source = xml
        self.current_package = package
        self.current_activity = activity

    def get_window_size(self):
        return {"width": 1080, "height": 1920}


class _FakeWebDriver:
    page_source = "<html><body><button>Fallback</button></body></html>"
    current_url = "https://example.com"
    title = "Example"

    def __init__(self):
        self.execute_script_calls: list[tuple[str, int, int]] = []

    def execute_script(self, script: str, depth: int, max_nodes: int) -> str:
        self.execute_script_calls.append((script, depth, max_nodes))
        return '{"tag":"body","role":"document","name":"","children":[{"tag":"button","name":"OK","children":[]}]}'


def test_refresh_native_snapshot_via_fake_driver(monkeypatch, tmp_path):
    xml = (
        '<hierarchy rotation="0">'
        '<node index="0" class="android.widget.Button" package="com.x" '
        'text="OK" resource-id="com.x:id/ok" checkable="false" checked="false" '
        'clickable="true" enabled="true" focusable="true" focused="false" '
        'long-clickable="false" password="false" scrollable="false" '
        'selected="false" bounds="[100,100][300,200]"/>'
        "</hierarchy>"
    )
    state.reset()
    state.driver = _FakeDriver(xml)
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "appium_cli.tools.observation.resolve_context", lambda c, d: "NATIVE_APP"
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.is_web_context", lambda c: False
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.using_context",
        lambda *a, **k: nullcontext(),
    )
    out = observation.snapshot()
    assert "snapshot_id:" in out
    assert "artifacts:" in out
    assert "[ref:ok]" not in out
    assert "screen_id:" in out
    latest = json.loads((tmp_path / "snapshots" / "latest.json").read_text(encoding="utf-8"))
    compact = (tmp_path / "snapshots" / f"{latest['snapshot_id']}.compact.yml").read_text(encoding="utf-8")
    refs = json.loads((tmp_path / "snapshots" / f"{latest['snapshot_id']}.refs.json").read_text(encoding="utf-8"))
    assert "[ref:ok]" in compact
    assert refs["refs"]["ok"]["role"] == "button"
    # current_snapshot was registered
    assert isinstance(state.current_snapshot, NativeSnapshot)
    assert state.current_snapshot.find_ref("ok") is not None
    assert state.current_snapshot_id == latest["snapshot_id"]


def test_describe_accepts_current_snapshot_qualified_ref(monkeypatch, tmp_path):
    xml = (
        '<hierarchy rotation="0">'
        '<node index="0" class="android.widget.Button" package="com.x" '
        'text="OK" resource-id="com.x:id/ok" clickable="true" enabled="true" '
        'bounds="[100,100][300,200]"/>'
        "</hierarchy>"
    )
    state.reset()
    state.driver = _FakeDriver(xml)
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "appium_cli.tools.observation.resolve_context", lambda c, d: "NATIVE_APP"
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.is_web_context", lambda c: False
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.using_context",
        lambda *a, **k: nullcontext(),
    )

    observation.snapshot()
    out = observation.describe(f"{state.current_snapshot_id}:ok")

    assert "element:" in out
    assert "role: button" in out


def test_describe_unknown_ref_uses_stale_ref_message(monkeypatch, tmp_path):
    xml = (
        '<hierarchy rotation="0">'
        '<node index="0" class="android.widget.Button" package="com.x" '
        'text="OK" resource-id="com.x:id/ok" clickable="true" enabled="true" '
        'bounds="[100,100][300,200]"/>'
        "</hierarchy>"
    )
    state.reset()
    state.driver = _FakeDriver(xml)
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "appium_cli.tools.observation.resolve_context", lambda c, d: "NATIVE_APP"
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.is_web_context", lambda c: False
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.using_context",
        lambda *a, **k: nullcontext(),
    )

    observation.snapshot()
    out = observation.describe("missing")

    assert out.startswith("ERROR: ref 'missing' cannot be resolved.")
    assert "current in-memory snapshot" in out


def test_snapshot_raw_returns_tree_and_filename_writes_tree(monkeypatch, tmp_path):
    xml = (
        '<hierarchy rotation="0">'
        '<node index="0" class="android.widget.Button" package="com.x" '
        'text="OK" resource-id="com.x:id/ok" clickable="true" enabled="true" '
        'bounds="[100,100][300,200]"/>'
        "</hierarchy>"
    )
    state.reset()
    state.driver = _FakeDriver(xml)
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "appium_cli.tools.observation.resolve_context", lambda c, d: "NATIVE_APP"
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.is_web_context", lambda c: False
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.using_context",
        lambda *a, **k: nullcontext(),
    )
    filename = tmp_path / "before.yml"

    out = observation.snapshot(raw=True, filename=str(filename))

    assert out.startswith("screen:")
    assert "[ref:ok]" in out
    assert "artifacts:" not in out
    assert filename.read_text(encoding="utf-8") == out
    assert (tmp_path / "snapshots" / "latest.json").exists()


def test_snapshot_target_raw_filename_and_artifacts_are_scoped(monkeypatch, tmp_path):
    xml = (
        '<hierarchy rotation="0">'
        '<node index="0" class="android.widget.Button" package="com.x" '
        'text="OK" resource-id="com.x:id/ok" clickable="true" enabled="true" '
        'bounds="[100,100][300,200]"/>'
        '<node index="1" class="android.widget.Button" package="com.x" '
        'text="Cancel" resource-id="com.x:id/cancel" clickable="true" enabled="true" '
        'bounds="[300,100][500,200]"/>'
        "</hierarchy>"
    )
    state.reset()
    state.driver = _FakeDriver(xml)
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "appium_cli.tools.observation.resolve_context", lambda c, d: "NATIVE_APP"
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.is_web_context", lambda c: False
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.using_context",
        lambda *a, **k: nullcontext(),
    )
    filename = tmp_path / "scoped.yml"

    out = observation.snapshot(target="ok", raw=True, filename=str(filename))

    assert "[ref:ok]" in out
    assert "Cancel" not in out
    assert filename.read_text(encoding="utf-8") == out
    latest = json.loads((tmp_path / "snapshots" / "latest.json").read_text(encoding="utf-8"))
    assert latest["scope"] == "ref:ok"
    compact = (tmp_path / "snapshots" / f"{latest['snapshot_id']}.compact.yml").read_text(encoding="utf-8")
    full = (tmp_path / "snapshots" / f"{latest['snapshot_id']}.full.yml").read_text(encoding="utf-8")
    assert "[ref:ok]" in compact
    assert "Cancel" not in compact
    assert "Cancel" not in full


def test_refresh_web_snapshot_uses_generator_default_limits(monkeypatch, tmp_path):
    driver = _FakeWebDriver()
    state.reset()
    state.driver = driver
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "appium_cli.tools.observation.resolve_context", lambda c, d: "WEBVIEW_1"
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.is_web_context", lambda c: True
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.using_context",
        lambda *a, **k: nullcontext(),
    )

    out = observation.snapshot(context="webview")

    assert "snapshot_id:" in out
    assert "artifacts:" in out
    latest = json.loads((tmp_path / "snapshots" / "latest-web-WEBVIEW_1.json").read_text(encoding="utf-8"))
    compact = (tmp_path / "snapshots" / f"{latest['snapshot_id']}.compact.yml").read_text(encoding="utf-8")
    assert "[ref:web_btn_ok]" in compact
    assert len(driver.execute_script_calls) == 1
    _script, depth, max_nodes = driver.execute_script_calls[0]
    assert depth == WEB_DEFAULT_MAX_DEPTH == 999
    assert max_nodes == WEB_DEFAULT_MAX_NODES == 999999


def test_refresh_web_snapshot_preserves_explicit_expanded_limits(monkeypatch, tmp_path):
    driver = _FakeWebDriver()
    state.reset()
    state.driver = driver
    monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "appium_cli.tools.observation.resolve_context", lambda c, d: "WEBVIEW_1"
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.is_web_context", lambda c: True
    )
    monkeypatch.setattr(
        "appium_cli.tools.observation.using_context",
        lambda *a, **k: nullcontext(),
    )

    out = observation.snapshot(context="webview", depth=50, max_nodes=2000)

    assert "snapshot_id:" in out
    assert "artifacts:" in out
    assert len(driver.execute_script_calls) == 1
    _script, depth, max_nodes = driver.execute_script_calls[0]
    assert depth == 50
    assert max_nodes == 2000


def test_tap_webview_click_intercepted_recovery_succeeds(monkeypatch):
    """tap should scrollIntoView and retry when click is intercepted."""
    state.reset()
    click_count = [0]
    scrolled = [False]

    class FakeElement:
        def click(self):
            click_count[0] += 1
            if click_count[0] == 1:
                raise Exception("element click intercepted")

    class FakeDriver:
        def execute_script(self, script, *args):
            if "scrollIntoView" in script:
                scrolled[0] = True

    element = FakeElement()
    state.driver = FakeDriver()
    state.current_context = "WEBVIEW_1"
    monkeypatch.setattr(actions.time, "sleep", lambda _: None)
    monkeypatch.setattr(actions, "_is_web_target", lambda _ref: True)
    monkeypatch.setattr(actions, "_is_web_ref", lambda _ref: True)
    monkeypatch.setattr(actions, "_resolve_element", lambda _ref: element)

    result = actions.tap("submit_btn")
    assert result == "OK"
    assert scrolled[0] is True
    assert click_count[0] == 2


def test_tap_webview_click_intercepted_reports_blocker(monkeypatch):
    """tap should report blocking element info after retry failure."""
    state.reset()

    class FakeElement:
        def click(self):
            raise Exception("element click intercepted by overlay")

    class FakeDriver:
        def execute_script(self, script, *args):
            if "scrollIntoView" in script:
                return None
            if "elementFromPoint" in script:
                return "div#cookie-banner.overlay"
            return None

    element = FakeElement()
    state.driver = FakeDriver()
    state.current_context = "WEBVIEW_1"
    monkeypatch.setattr(actions.time, "sleep", lambda _: None)
    monkeypatch.setattr(actions, "_is_web_target", lambda _ref: True)
    monkeypatch.setattr(actions, "_is_web_ref", lambda _ref: True)
    monkeypatch.setattr(actions, "_resolve_element", lambda _ref: element)

    with pytest.raises(AppiumCliError, match="intercepted.*cookie-banner"):
        actions.tap("submit_btn")


def test_tap_native_not_affected_by_recovery(monkeypatch):
    """Native tap should not trigger click intercepted recovery."""
    state.reset()
    gesture_called = [False]

    class FakeDriver:
        def execute_script(self, script, *args):
            if "clickGesture" in script:
                gesture_called[0] = True

    state.driver = FakeDriver()
    state.current_context = "NATIVE_APP"
    monkeypatch.setattr(actions.time, "sleep", lambda _: None)
    monkeypatch.setattr(actions, "_is_web_target", lambda _ref: False)
    monkeypatch.setattr(actions, "_gesture_target", lambda _ref: {"x": 100, "y": 200})

    result = actions.tap("button")
    assert result == "OK"
    assert gesture_called[0] is True


def test_type_text_web_submit_uses_enter_key(monkeypatch):
    """Web submit should use Keys.ENTER, not element.submit()."""
    state.reset()
    calls = []

    class FakeElement:
        def click(self):
            pass
        def clear(self):
            pass
        def send_keys(self, *args):
            calls.append(("send_keys", args))
        def submit(self):
            calls.append(("submit",))
            raise AssertionError("submit() should not be called")

    element = FakeElement()
    state.driver = object()
    state.current_context = "WEBVIEW_1"
    monkeypatch.setattr(actions.time, "sleep", lambda _: None)
    monkeypatch.setattr(actions, "_is_web_target", lambda _ref: True)
    monkeypatch.setattr(actions, "_resolve_element", lambda _ref: element)

    result = actions.type_text("input", "hello", submit=True)
    assert result == "OK"
    # Should have send_keys("hello") and send_keys(Keys.ENTER)
    assert len(calls) == 2
    assert calls[0] == ("send_keys", ("hello",))
    # Second call should be Keys.ENTER
    assert calls[1][0] == "send_keys"
    assert len(calls[1][1]) == 1  # one argument


def test_type_text_web_slowly_with_submit(monkeypatch):
    """slowly=True with submit=True should type chars then send Enter."""
    state.reset()
    calls = []

    class FakeElement:
        def click(self):
            pass
        def send_keys(self, *args):
            calls.append(("send_keys", args))
        def submit(self):
            raise AssertionError("submit() should not be called")

    element = FakeElement()
    state.driver = object()
    state.current_context = "WEBVIEW_1"
    monkeypatch.setattr(actions.time, "sleep", lambda _: None)
    monkeypatch.setattr(actions, "_is_web_target", lambda _ref: True)
    monkeypatch.setattr(actions, "_resolve_element", lambda _ref: element)

    result = actions.type_text("input", "ab", submit=True, slowly=True)
    assert result == "OK"
    # Should have: send_keys("a"), send_keys("b"), send_keys(ENTER)
    assert len(calls) == 3
    assert calls[0] == ("send_keys", ("a",))
    assert calls[1] == ("send_keys", ("b",))
    assert calls[2][0] == "send_keys"


# ---------------------------------------------------------------------------
# select_option polling / timeout tests
# ---------------------------------------------------------------------------

def test_select_option_polls_until_found(monkeypatch):
    """select_option should poll for options within timeout."""
    state.reset()
    call_count = [0]

    class FakeElement:
        def click(self):
            pass

    class FakeDriver:
        def execute_script(self, script, *args):
            if "tagName" in script:
                return "div"  # not a native <select>
            call_count[0] += 1
            if call_count[0] < 3:
                return {"found": False, "available": ["Other Option"]}
            return {"found": True}

    state.driver = FakeDriver()
    state.current_context = "WEBVIEW_1"
    monkeypatch.setattr(actions.time, "sleep", lambda _: None)
    monkeypatch.setattr(actions, "_resolve_element", lambda _ref: FakeElement())
    monkeypatch.setattr(actions, "_is_web_target", lambda _ref: True)

    result = actions.select_option("dropdown", "Target Option", timeout=5.0)
    assert result == "OK"
    assert call_count[0] >= 3


def test_select_option_timeout_raises(monkeypatch):
    """select_option should raise AppiumCliError after timeout."""
    state.reset()

    class FakeElement:
        def click(self):
            pass

    class FakeDriver:
        def execute_script(self, script, *args):
            if "tagName" in script:
                return "div"
            return {"found": False, "available": ["A", "B"]}

    state.driver = FakeDriver()
    state.current_context = "WEBVIEW_1"
    monkeypatch.setattr(actions.time, "sleep", lambda _: None)
    # Make time.monotonic advance past deadline immediately
    counter = [0]

    def fake_monotonic():
        counter[0] += 1
        return float(counter[0] * 10)  # jumps 10s each call

    monkeypatch.setattr(actions.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(actions, "_resolve_element", lambda _ref: FakeElement())
    monkeypatch.setattr(actions, "_is_web_target", lambda _ref: True)

    import pytest
    with pytest.raises(AppiumCliError, match="not found in dropdown"):
        actions.select_option("dropdown", "Missing", timeout=1.0)
