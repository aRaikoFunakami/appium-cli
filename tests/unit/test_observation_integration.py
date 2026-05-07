"""Integration tests for observation and container tools using NativeSnapshot."""

from __future__ import annotations

import json
import shutil
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from appium_cli.core.native_snapshot import NativeSnapshot, NativeSnapshotNode
from appium_cli.core.snapshot import LocatorStrategy, RefEntry
from appium_cli.core.snapshot_artifacts import create_snapshot_bundle_payload
from appium_cli.core.web_snapshot import WebSnapshot, WebSnapshotNode
from appium_cli.core.web_snapshot_generator import WEB_DEFAULT_MAX_DEPTH, WEB_DEFAULT_MAX_NODES
from appium_cli.daemon import state
from appium_cli.tools import actions, container, observation


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


def _snapshot_metadata_text(snapshot_id: str = "snap-1") -> str:
    return (
        f"snapshot_id: {snapshot_id}\n"
        "source: native\n"
        "screen_id: screen-1\n"
        "artifacts:\n"
        f"  meta: .appium-cli/snapshots/{snapshot_id}.meta.json"
    )


def test_native_action_appends_post_action_snapshot_metadata(monkeypatch):
    calls: list[dict] = []

    class FakeDriver:
        def __init__(self):
            self.keycodes: list[int] = []

        def press_keycode(self, keycode: int) -> None:
            self.keycodes.append(keycode)

    def fake_refresh_snapshot(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=_snapshot_metadata_text("native-after"), data={})

    driver = FakeDriver()
    state.driver = driver
    state.current_context = "NATIVE_APP"
    monkeypatch.setattr(actions.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(actions, "refresh_snapshot", fake_refresh_snapshot)

    out = actions.press_key("back")

    assert driver.keycodes == [4]
    assert out.startswith("OK\nsnapshot_id: native-after")
    assert "artifacts:" in out
    assert calls == [{"context": "native", "raw": False}]


def test_web_action_appends_web_snapshot_metadata_and_raw_hides_link(monkeypatch):
    calls: list[dict] = []

    class FakeElement:
        def __init__(self):
            self.clicked = False

        def click(self) -> None:
            self.clicked = True

    def fake_refresh_snapshot(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=_snapshot_metadata_text("web-after"), data={})

    element = FakeElement()
    state.driver = object()
    state.current_context = "WEBVIEW_1"
    monkeypatch.setattr(actions.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(actions, "_is_web_ref", lambda _ref: True)
    monkeypatch.setattr(actions, "_resolve_element", lambda _ref: element)
    monkeypatch.setattr(actions, "_ref_context", lambda _ref: "WEBVIEW_1")
    monkeypatch.setattr(actions, "refresh_snapshot", fake_refresh_snapshot)

    out = actions.tap("submit")

    assert element.clicked is True
    assert out.startswith("OK\nsnapshot_id: web-after")
    assert calls[-1] == {"context": "webview", "raw": False}

    state.action_raw_output = True
    raw_out = actions.tap("submit")

    assert raw_out == "OK"
    assert "snapshot_id:" not in raw_out
    assert calls[-1] == {"context": "webview", "raw": False}


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


def test_snapshot_search_uses_artifacts_without_current_snapshot(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)
    state.current_snapshot = None

    out = observation.snapshot_search("storage")

    assert "Snapshot search results for 'storage'" in out
    assert "[ref:storage_row] row \"Storage\"" in out


def test_snapshot_search_role_filter(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)

    out = observation.snapshot_search("storage", role="button")

    assert "No snapshot refs matching 'storage' found." in out


def test_snapshot_refs_lists_filters_and_returns_raw_json(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)

    listed = observation.snapshot_refs("latest", role="button")
    assert "[ref:ok] button \"OK\"" in listed
    assert "storage_row" not in listed

    raw = observation.snapshot_refs("latest", raw=True)
    refs = json.loads(raw)
    assert {item["ref"] for item in refs} >= {"ok", "recycler", "storage_row"}


def test_snapshot_refs_can_show_single_ref_as_raw_json(monkeypatch, request):
    _install_snapshot_artifacts(monkeypatch, request)

    raw = observation.snapshot_refs("latest", "ok", raw=True)

    payload = json.loads(raw)
    assert payload["ref"] == "ok"
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
    assert '1. [ref:web_q] input textbox "Search" selector=#q' in out
    assert "   id=q name=q type=search placeholder=Search aria-label=Search data-testid=search-box" in out
    assert "data-testid=search-box" in out


def test_web_query_compact_output_includes_button_and_link_details():
    driver = _FakeWebQueryDriver()
    state.driver = driver
    state.current_ref_map = {}

    button_out = observation.web_query("button")
    link_out = observation.web_query("a")

    assert '1. button button "Search Web"' in button_out
    assert 'selector="button[name=\\"btnK\\"]"' in button_out
    assert "name=btnK" in button_out
    assert "type=submit" in button_out
    assert "aria-label=\"Search Web\"" in button_out
    assert '1. a link "News"' in link_out
    assert 'selector="a[href=\\"/news\\"]"' in link_out
    assert "href=/news" in link_out


def test_web_query_raw_returns_json_array():
    driver = _FakeWebQueryDriver()
    state.driver = driver
    state.current_ref_map = {}

    raw = observation.web_query("input", raw=True)

    payload = json.loads(raw)
    assert payload[0]["selector"] == "#q"
    assert payload[0]["attrs"]["data-testid"] == "search-box"


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
    assert depth == WEB_DEFAULT_MAX_DEPTH == 15
    assert max_nodes == WEB_DEFAULT_MAX_NODES == 300


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
