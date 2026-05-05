"""Integration tests for observation and container tools using NativeSnapshot."""

from __future__ import annotations

from contextlib import nullcontext

from appium_cli.core.native_snapshot import NativeSnapshot, NativeSnapshotNode
from appium_cli.core.snapshot import LocatorStrategy
from appium_cli.daemon import state
from appium_cli.tools import container, observation


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
    return NativeSnapshot.from_root(root=root, app_info="com.x/.MainActivity")


def setup_function(_func) -> None:
    state.reset()


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


def test_refresh_native_snapshot_via_fake_driver(monkeypatch):
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
    assert "[ref:ok]" in out
    assert "screen_id:" in out
    # current_snapshot was registered
    assert isinstance(state.current_snapshot, NativeSnapshot)
    assert state.current_snapshot.find_ref("ok") is not None
