"""Tests for positional gesture invalidation (stale snapshot detection)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from appium_cli.core.snapshot import LocatorStrategy, RefEntry
from appium_cli.daemon import state
from appium_cli.tools import actions
from appium_cli.utils.errors import AppiumCliError


def _make_native_entry(ref_id: str = "container") -> RefEntry:
    return RefEntry(
        strategies=[
            LocatorStrategy(by="id", value=f"com.example:id/{ref_id}"),
            LocatorStrategy(by="coordinates", value="500,500"),
        ],
        expected_bounds=(100, 200, 900, 1000),
        role="list",
        name="Scrollable Container",
        context="NATIVE_APP",
        source_type="native",
    )


def _make_coordinate_only_entry(ref_id: str = "container") -> RefEntry:
    return RefEntry(
        strategies=[LocatorStrategy(by="coordinates", value="500,500")],
        expected_bounds=(100, 200, 900, 1000),
        role="list",
        name="Scrollable Container",
        context="NATIVE_APP",
        source_type="native",
    )


def _setup_native_driver(monkeypatch, gesture_returns=True) -> MagicMock:
    """Wire a fake native driver into state. Returns the mock."""
    driver = MagicMock()
    driver.current_context = "NATIVE_APP"
    driver.execute_script.return_value = gesture_returns
    driver.get_window_size.return_value = {"width": 1080, "height": 1920}
    fake_el = MagicMock()
    fake_el.id = "element-1"
    fake_el.location = {"x": 100, "y": 200}
    fake_el.size = {"width": 800, "height": 800}
    driver.find_elements.return_value = [fake_el]
    driver.find_element.return_value = fake_el
    state.driver = driver
    state.current_context = "NATIVE_APP"
    state.ref_resolver.clear()
    state.ref_resolver.clear_stale()
    # Make _gesture_target() / _screen_rect() resolve without device IO
    monkeypatch.setattr(actions, "_screen_rect", lambda: {"left": 0, "top": 0, "width": 1080, "height": 1920})
    return driver


@pytest.fixture(autouse=True)
def _restore_state():
    yield
    state.ref_resolver.clear()
    state.ref_resolver.clear_stale()
    state.driver = None


class TestPositionalGesturesMarkStale:
    def test_scroll_without_ref_marks_current_context_stale(self, monkeypatch):
        _setup_native_driver(monkeypatch)
        out = actions.scroll("up")
        assert state.ref_resolver.is_stale("NATIVE_APP") is True
        assert "snapshot_stale: true" in out
        assert "can_scroll_more:" in out

    def test_scroll_with_ref_marks_ref_context_stale(self, monkeypatch):
        _setup_native_driver(monkeypatch)
        state.ref_resolver.register_all({"container": _make_native_entry()})
        out = actions.scroll("up", ref="container")
        assert state.ref_resolver.is_stale("NATIVE_APP") is True
        reason = state.ref_resolver.stale_reason("NATIVE_APP")
        assert "scroll" in reason
        assert "container" in reason
        assert "snapshot_stale: true" in out

    def test_swipe_marks_stale_and_returns_hint(self, monkeypatch):
        _setup_native_driver(monkeypatch)
        out = actions.swipe("up")
        assert state.ref_resolver.is_stale("NATIVE_APP") is True
        assert "snapshot_stale: true" in out

    def test_fling_marks_stale_and_returns_hint(self, monkeypatch):
        _setup_native_driver(monkeypatch)
        out = actions.fling("up")
        assert state.ref_resolver.is_stale("NATIVE_APP") is True
        assert "snapshot_stale: true" in out
        assert "can_scroll_more:" in out

    def test_drag_marks_stale_and_returns_hint(self, monkeypatch):
        _setup_native_driver(monkeypatch)
        state.ref_resolver.register_all({"container": _make_native_entry()})
        out = actions.drag("container", end_x=500, end_y=500)
        assert state.ref_resolver.is_stale("NATIVE_APP") is True
        assert "snapshot_stale: true" in out


class TestStateChangingActionsMarkStale:
    def test_tap_marks_stale_after_success(self, monkeypatch):
        driver = _setup_native_driver(monkeypatch)
        entry = _make_native_entry("btn")
        state.ref_resolver.register_all({"btn": entry})

        actions.tap("btn")
        assert state.ref_resolver.is_stale("NATIVE_APP") is True

    def test_press_key_marks_current_context_stale_after_success(self, monkeypatch):
        _setup_native_driver(monkeypatch)
        actions.press_key("back")
        assert state.ref_resolver.is_stale("NATIVE_APP") is True

    def test_press_key_allowed_when_context_is_already_stale(self, monkeypatch):
        _setup_native_driver(monkeypatch)
        state.ref_resolver.mark_stale("NATIVE_APP", "type_text", ref="field")
        actions.press_key("back")
        assert state.ref_resolver.is_stale("NATIVE_APP") is True
        assert "press_key" in state.ref_resolver.stale_reason("NATIVE_APP")

    def test_tap_then_ref_action_requires_snapshot(self, monkeypatch):
        _setup_native_driver(monkeypatch)
        state.ref_resolver.register_all({
            "tab": _make_native_entry("tab"),
            "list": _make_native_entry("list"),
        })

        actions.tap("tab")
        with pytest.raises(AppiumCliError) as exc:
            actions.scroll("up", ref="list")

        assert "snapshot_required" in str(exc.value)

    def test_coordinate_only_ref_rejected_for_scroll(self, monkeypatch):
        driver = _setup_native_driver(monkeypatch)
        state.ref_resolver.register_all({"container": _make_coordinate_only_entry()})

        with pytest.raises(AppiumCliError) as exc:
            actions.scroll("up", ref="container")

        assert "coordinates only" in str(exc.value)
        driver.execute_script.assert_not_called()


class TestScrollRegressionGuard:
    def test_scroll_does_not_call_snapshot_internally(self, monkeypatch):
        """Regression guard: scroll must NOT auto-refresh the snapshot.

        Auto-refresh was rejected because it would update daemon state without
        updating the agent's observed memory, causing a desync. This test pins
        that decision.
        """
        from appium_cli.tools import observation

        _setup_native_driver(monkeypatch)
        snapshot_called = MagicMock()
        monkeypatch.setattr(observation, "snapshot", snapshot_called)

        actions.scroll("up")
        snapshot_called.assert_not_called()


class TestWebScrollStaleIsolation:
    def test_web_scroll_marks_web_context_only(self, monkeypatch):
        driver = MagicMock()
        driver.current_context = "WEBVIEW_chrome"
        driver.execute_script.return_value = None
        driver.get_window_size.return_value = {"width": 1080, "height": 1920}
        state.driver = driver
        state.current_context = "WEBVIEW_chrome"
        state.ref_resolver.clear()
        state.ref_resolver.clear_stale()

        out = actions.scroll("up")

        assert state.ref_resolver.is_stale("WEBVIEW_chrome") is True
        assert state.ref_resolver.is_stale("NATIVE_APP") is False
        assert "snapshot_stale: true" in out
