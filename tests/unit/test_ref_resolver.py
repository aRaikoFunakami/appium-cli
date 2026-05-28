"""Tests for RefResolver bounds verification and multi-strategy resolution."""

import json
from unittest.mock import MagicMock

import pytest

from appium_cli.core.ref_resolver import (
    ElementNotFoundError,
    RefResolver,
    StaleSnapshotError,
    _CoordinateElement,
    parse_ref,
)
from appium_cli.core.snapshot import LocatorStrategy, RefEntry
from appium_cli.utils.paths import latest_snapshot_path, snapshot_artifact_path


def _make_entry(
    bounds=(100, 200, 300, 400),
    strategies=None,
) -> RefEntry:
    if strategies is None:
        strategies = [
            LocatorStrategy(by="id", value="com.example:id/btn"),
            LocatorStrategy(by="coordinates", value="200,300"),
        ]
    return RefEntry(
        strategies=strategies,
        expected_bounds=bounds,
        role="button",
        name="Test Button",
    )


def _mock_element(x=100, y=200, w=200, h=200):
    el = MagicMock()
    el.location = {"x": x, "y": y}
    el.size = {"width": w, "height": h}
    el.id = "fake-element-id"
    return el


def _refs_payload(snapshot_id="snap-1", ref="btn", context="NATIVE_APP"):
    entry = _make_entry()
    return {
        "snapshot_id": snapshot_id,
        "source": "native",
        "screen_id": "screen-1",
        "context": context,
        "refs": {
            ref: {
                "role": entry.role,
                "name": entry.name,
                "context": context,
                "source_type": "native",
                "expected_bounds": list(entry.expected_bounds),
                "strategies": [
                    {"by": strategy.by, "value": strategy.value}
                    for strategy in entry.strategies
                ],
            }
        },
    }


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestRefResolverBoundsVerification:
    def test_bounds_match_within_tolerance(self):
        resolver = RefResolver()
        el = _mock_element(x=105, y=195, w=200, h=200)
        assert resolver._verify_bounds(el, (100, 200, 300, 400)) is True

    def test_bounds_mismatch_beyond_tolerance(self):
        resolver = RefResolver()
        el = _mock_element(x=0, y=0, w=50, h=50)
        assert resolver._verify_bounds(el, (100, 200, 300, 400)) is False

    def test_coordinate_element_always_passes_bounds(self):
        resolver = RefResolver()
        coord_el = _CoordinateElement(200, 300, MagicMock())
        assert resolver._verify_bounds(coord_el, (100, 200, 300, 400)) is True


class TestRefResolverResolution:
    def test_resolve_unregistered_ref_raises(self):
        resolver = RefResolver()
        driver = MagicMock()
        with pytest.raises(ElementNotFoundError):
            resolver.resolve("nonexistent", driver)

    def test_resolve_first_strategy_match(self):
        resolver = RefResolver()
        entry = _make_entry()
        resolver.register_all({"btn": entry})

        driver = MagicMock()
        el = _mock_element()
        driver.find_elements.return_value = [el]
        driver.find_element.return_value = el

        result = resolver.resolve("btn", driver)
        assert result == el

    def test_resolve_falls_through_on_bounds_mismatch(self):
        resolver = RefResolver()
        entry = _make_entry(
            bounds=(100, 200, 300, 400),
            strategies=[
                LocatorStrategy(by="id", value="com.example:id/btn"),
                LocatorStrategy(by="coordinates", value="200,300"),
            ],
        )
        resolver.register_all({"btn": entry})

        driver = MagicMock()
        wrong_el = _mock_element(x=0, y=0, w=50, h=50)
        driver.find_elements.return_value = [wrong_el]
        driver.find_element.return_value = wrong_el

        result = resolver.resolve("btn", driver)
        # Falls through to coordinates strategy
        assert isinstance(result, _CoordinateElement)
        assert result.x == 200
        assert result.y == 300

    def test_resolve_strips_ref_prefix(self):
        resolver = RefResolver()
        entry = _make_entry()
        resolver.register_all({"btn": entry})

        driver = MagicMock()
        el = _mock_element()
        driver.find_elements.return_value = [el]
        driver.find_element.return_value = el

        result = resolver.resolve("[ref:btn]", driver)
        assert result == el

    def test_resolve_accepts_current_snapshot_qualified_ref(self):
        resolver = RefResolver()
        entry = _make_entry(
            bounds=(100, 200, 300, 400),
            strategies=[
                LocatorStrategy(by="id", value="com.example:id/btn"),
                LocatorStrategy(by="coordinates", value="200,300"),
            ],
        )
        resolver.register_all({"btn": entry}, snapshot_id="snap-current")

        driver = MagicMock()
        wrong_el = _mock_element(x=0, y=0, w=50, h=50)
        driver.find_elements.return_value = [wrong_el]
        driver.find_element.return_value = wrong_el

        result = resolver.resolve("snap-current:btn", driver)
        assert isinstance(result, _CoordinateElement)
        assert result.x == 200
        assert result.y == 300

    def test_resolve_loads_latest_qualified_ref_from_artifact(self, monkeypatch, tmp_path):
        monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
        payload = _refs_payload(snapshot_id="snap-latest", ref="btn")
        _write_json(snapshot_artifact_path("snap-latest", "refs"), payload)
        _write_json(latest_snapshot_path(), {"snapshot_id": "snap-latest"})

        resolver = RefResolver()
        driver = MagicMock()
        el = _mock_element()
        driver.find_elements.return_value = [el]
        driver.find_element.return_value = el

        result = resolver.resolve("snap-latest:btn", driver)

        assert result == el
        assert resolver.get_entry("snap-latest:btn") is not None
        assert resolver.get_entry("btn") is None

    def test_qualified_ref_rejects_stale_snapshot(self, monkeypatch, tmp_path):
        monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
        payload = _refs_payload(snapshot_id="snap-old", ref="btn")
        _write_json(snapshot_artifact_path("snap-old", "refs"), payload)
        _write_json(latest_snapshot_path(), {"snapshot_id": "snap-new"})

        resolver = RefResolver()
        with pytest.raises(ElementNotFoundError) as exc_info:
            resolver.resolve("snap-old:btn", MagicMock())

        message = str(exc_info.value)
        assert "snap-old:btn" in message
        assert "stale or not current" in message
        assert "snap-new" in message

    def test_short_unknown_ref_reports_latest_context_owner(self, monkeypatch, tmp_path):
        monkeypatch.setattr("appium_cli.utils.paths.get_app_dir", lambda: tmp_path)
        payload = _refs_payload(snapshot_id="snap-web", ref="web_btn", context="WEBVIEW_1")
        _write_json(snapshot_artifact_path("snap-web", "refs"), payload)
        _write_json(latest_snapshot_path(source="native"), {"snapshot_id": "snap-native"})
        _write_json(
            latest_snapshot_path(source="native", context="WEBVIEW_1"),
            {"snapshot_id": "snap-web", "context": "WEBVIEW_1"},
        )

        resolver = RefResolver()
        resolver.register_all({"native_btn": _make_entry()}, snapshot_id="snap-native")

        with pytest.raises(ElementNotFoundError) as exc_info:
            resolver.require_registered("web_btn")

        message = str(exc_info.value)
        assert "current in-memory snapshot" in message
        assert "snap-web:web_btn" in message
        assert "WEBVIEW_1" in message

    def test_resolve_or_none_returns_none_on_failure(self):
        resolver = RefResolver()
        driver = MagicMock()
        result = resolver.resolve_or_none("nonexistent", driver)
        assert result is None


class TestRefResolverRegistration:
    def test_register_all_replaces_map(self):
        resolver = RefResolver()
        resolver.register_all({"a": _make_entry()})
        assert resolver.has("a")

        resolver.register_all({"b": _make_entry()})
        assert not resolver.has("a")
        assert resolver.has("b")

    def test_list_refs(self):
        resolver = RefResolver()
        resolver.register_all({"x": _make_entry(), "y": _make_entry()})
        assert sorted(resolver.list_refs()) == ["x", "y"]

    def test_clear(self):
        resolver = RefResolver()
        resolver.register_all({"a": _make_entry()}, snapshot_id="snap")
        resolver.clear()
        assert not resolver.has("a")
        assert resolver._current_snapshot_id is None

    def test_register_context_replaces_only_same_context(self):
        resolver = RefResolver()
        native_entry = _make_entry()
        native_entry.context = "NATIVE_APP"
        web_entry = RefEntry(
            strategies=[LocatorStrategy(by="css selector", value="#btn")],
            expected_bounds=(0, 0, 0, 0),
            role="button",
            name="Web Button",
            context="CHROMIUM",
            source_type="web",
        )
        resolver.register_all({"native_btn": native_entry})
        resolver.register_context("CHROMIUM", {"web_btn": web_entry})

        assert resolver.has("native_btn")
        assert resolver.has("web_btn")

        # Replace web refs only
        web_entry2 = RefEntry(
            strategies=[LocatorStrategy(by="css selector", value="#btn2")],
            expected_bounds=(0, 0, 0, 0),
            role="button",
            name="Web Button 2",
            context="CHROMIUM",
            source_type="web",
        )
        resolver.register_context("CHROMIUM", {"web_btn2": web_entry2})

        assert resolver.has("native_btn")
        assert not resolver.has("web_btn")
        assert resolver.has("web_btn2")


class TestRefResolverWebStrategies:
    def test_css_selector_strategy(self):
        resolver = RefResolver()
        entry = RefEntry(
            strategies=[LocatorStrategy(by="css selector", value="#submit-btn")],
            expected_bounds=(0, 0, 0, 0),
            role="button",
            name="Submit",
            context="CHROMIUM",
            source_type="web",
        )
        resolver.register_all({"web_submit": entry})

        driver = MagicMock()
        driver.current_context = "CHROMIUM"
        el = _mock_element()
        driver.find_elements.return_value = [el]

        result = resolver.resolve("web_submit", driver)
        assert result == el

    def test_zero_bounds_skip_verification(self):
        resolver = RefResolver()
        el = _mock_element(x=500, y=600, w=100, h=50)
        # (0,0,0,0) bounds should skip verification
        assert resolver._verify_bounds(el, (0, 0, 0, 0)) is True

    def test_ensure_context_switches(self):
        resolver = RefResolver()
        entry = RefEntry(
            strategies=[LocatorStrategy(by="css selector", value="#btn")],
            expected_bounds=(0, 0, 0, 0),
            role="button",
            name="Btn",
            context="CHROMIUM",
            source_type="web",
        )
        resolver.register_all({"web_btn": entry})

        driver = MagicMock()
        driver.current_context = "NATIVE_APP"
        el = _mock_element()
        driver.find_elements.return_value = [el]

        resolver.resolve("web_btn", driver)
        driver.switch_to.context.assert_called_with("CHROMIUM")


class TestRefResolverDuplicateIdCandidates:
    """Tests for resolving Web refs when CSS selector matches multiple elements.

    Simulates the Yahoo Transit scenario: 3 inputs all with id=query_input
    but distinct bounds. RefResolver must use find_elements and pick the
    candidate whose bounds match expected_bounds.
    """

    def test_css_selector_picks_second_candidate_by_bounds(self):
        """web_query_input_2 should resolve to the 2nd input, not fall to coordinates."""
        resolver = RefResolver()
        # Second input: bounds (552, 468, 780, 504)
        entry = RefEntry(
            strategies=[
                LocatorStrategy(by="css selector", value="#query_input"),
                LocatorStrategy(by="coordinates", value="666,486"),
            ],
            expected_bounds=(552, 468, 780, 504),
            role="textbox",
            name="",
            context="WEBVIEW_chrome",
            source_type="web",
        )
        resolver.register_all({"web_query_input_2": entry})

        driver = MagicMock()
        driver.current_context = "WEBVIEW_chrome"

        # Simulate 3 elements matching #query_input with different bounds
        el1 = _mock_element(x=237, y=468, w=228, h=36)  # from
        el2 = _mock_element(x=552, y=468, w=228, h=36)  # to  <-- target
        el3 = _mock_element(x=394, y=514, w=229, h=26)  # via01

        driver.find_elements.return_value = [el1, el2, el3]

        result = resolver.resolve("web_query_input_2", driver)
        # Should resolve to the SECOND element (el2), NOT coordinates fallback
        assert result == el2
        assert not isinstance(result, _CoordinateElement)

    def test_css_selector_picks_third_candidate_by_bounds(self):
        """web_query_input_3 should resolve to the 3rd input."""
        resolver = RefResolver()
        entry = RefEntry(
            strategies=[
                LocatorStrategy(by="css selector", value="#query_input"),
                LocatorStrategy(by="coordinates", value="508,527"),
            ],
            expected_bounds=(394, 514, 623, 540),
            role="textbox",
            name="",
            context="WEBVIEW_chrome",
            source_type="web",
        )
        resolver.register_all({"web_query_input_3": entry})

        driver = MagicMock()
        driver.current_context = "WEBVIEW_chrome"

        el1 = _mock_element(x=237, y=468, w=228, h=36)
        el2 = _mock_element(x=552, y=468, w=228, h=36)
        el3 = _mock_element(x=394, y=514, w=229, h=26)  # <-- target

        driver.find_elements.return_value = [el1, el2, el3]

        result = resolver.resolve("web_query_input_3", driver)
        assert result == el3
        assert not isinstance(result, _CoordinateElement)

    def test_first_candidate_still_resolves_normally(self):
        """web_query_input (first) should still work via find_elements."""
        resolver = RefResolver()
        entry = RefEntry(
            strategies=[
                LocatorStrategy(by="css selector", value="#query_input"),
                LocatorStrategy(by="coordinates", value="351,486"),
            ],
            expected_bounds=(237, 468, 465, 504),
            role="textbox",
            name="",
            context="WEBVIEW_chrome",
            source_type="web",
        )
        resolver.register_all({"web_query_input": entry})

        driver = MagicMock()
        driver.current_context = "WEBVIEW_chrome"

        el1 = _mock_element(x=237, y=468, w=228, h=36)  # <-- target
        el2 = _mock_element(x=552, y=468, w=228, h=36)
        el3 = _mock_element(x=394, y=514, w=229, h=26)

        driver.find_elements.return_value = [el1, el2, el3]

        result = resolver.resolve("web_query_input", driver)
        assert result == el1
        assert not isinstance(result, _CoordinateElement)

    def test_xpath_strategy_also_uses_candidate_enumeration(self):
        """XPath strategies should also enumerate candidates by bounds."""
        resolver = RefResolver()
        entry = RefEntry(
            strategies=[
                LocatorStrategy(by="xpath", value="//input[@id='query_input']"),
                LocatorStrategy(by="coordinates", value="666,486"),
            ],
            expected_bounds=(552, 468, 780, 504),
            role="textbox",
            name="",
            context="WEBVIEW_chrome",
            source_type="web",
        )
        resolver.register_all({"web_query_input_2": entry})

        driver = MagicMock()
        driver.current_context = "WEBVIEW_chrome"

        el1 = _mock_element(x=237, y=468, w=228, h=36)
        el2 = _mock_element(x=552, y=468, w=228, h=36)  # <-- target

        driver.find_elements.return_value = [el1, el2]

        result = resolver.resolve("web_query_input_2", driver)
        assert result == el2
        assert not isinstance(result, _CoordinateElement)


class TestRefResolverStaleBehavior:
    def _make_native_entry_with_id(self):
        entry = _make_entry(
            bounds=(100, 200, 300, 400),
            strategies=[
                LocatorStrategy(by="id", value="com.example:id/btn"),
                LocatorStrategy(by="coordinates", value="200,300"),
            ],
        )
        entry.context = "NATIVE_APP"
        return entry

    def test_mark_stale_and_is_stale(self):
        resolver = RefResolver()
        assert not resolver.is_stale("NATIVE_APP")
        resolver.mark_stale("NATIVE_APP", "scroll_up", ref="container")
        assert resolver.is_stale("NATIVE_APP")
        assert "scroll_up" in resolver.stale_reason("NATIVE_APP")
        assert "container" in resolver.stale_reason("NATIVE_APP")

    def test_register_all_clears_stale(self):
        resolver = RefResolver()
        resolver.mark_stale("NATIVE_APP", "scroll_up")
        resolver.register_all({"btn": _make_entry()})
        assert not resolver.is_stale("NATIVE_APP")

    def test_register_all_can_preserve_stale_for_context_scoped_refresh(self):
        resolver = RefResolver()
        resolver.mark_stale("NATIVE_APP", "scroll_up")
        resolver.register_all({"btn": _make_entry()}, clear_stale=False)
        assert resolver.is_stale("NATIVE_APP")

    def test_register_context_clears_only_that_context(self):
        resolver = RefResolver()
        resolver.mark_stale("NATIVE_APP", "scroll_up")
        resolver.mark_stale("CHROMIUM", "scroll_up")
        resolver.register_context("CHROMIUM", {})
        assert resolver.is_stale("NATIVE_APP")
        assert not resolver.is_stale("CHROMIUM")

    def test_clear_resets_stale(self):
        resolver = RefResolver()
        resolver.mark_stale("NATIVE_APP", "scroll_up")
        resolver.clear()
        assert not resolver.is_stale("NATIVE_APP")

    def test_resolve_requires_snapshot_when_stale(self):
        resolver = RefResolver()
        entry = self._make_native_entry_with_id()
        resolver.register_all({"favoriteicon": entry})
        resolver.mark_stale("NATIVE_APP", "scroll_up", ref="movies_section")

        driver = MagicMock()
        # id strategy returns a wrong-bounds element (post-scroll, the element
        # at this resource-id is now somewhere else)
        wrong = _mock_element(x=0, y=0, w=10, h=10)
        driver.find_elements.return_value = [wrong]
        driver.find_element.return_value = wrong

        with pytest.raises(StaleSnapshotError) as exc:
            resolver.resolve("favoriteicon", driver)

        msg = str(exc.value)
        assert "snapshot_required" in msg
        assert "scroll_up" in msg
        assert exc.value.ref == "favoriteicon"
        assert exc.value.context == "NATIVE_APP"
        assert exc.value.reason == "scroll_up(movies_section)"
        driver.find_elements.assert_not_called()

    def test_verify_bounds_rejects_coordinate_element_when_stale(self):
        resolver = RefResolver()
        coord = _CoordinateElement(200, 300, MagicMock())
        assert resolver._verify_bounds(coord, (100, 200, 300, 400), stale=False) is True
        assert resolver._verify_bounds(coord, (100, 200, 300, 400), stale=True) is False

    def test_verify_bounds_returns_false_on_exception(self):
        resolver = RefResolver()
        broken = MagicMock()
        # accessing .location raises
        type(broken).location = property(lambda self: (_ for _ in ()).throw(RuntimeError("stale element")))
        assert resolver._verify_bounds(broken, (100, 200, 300, 400)) is False


class TestRefResolverNativeIdEnumeration:
    def test_native_id_enumerates_and_picks_by_bounds(self):
        from appium.webdriver.common.appiumby import AppiumBy

        resolver = RefResolver()
        # Multiple elements share the same resource-id (e.g. RecyclerView rows)
        entry = _make_entry(
            bounds=(434, 628, 508, 702),
            strategies=[
                LocatorStrategy(by="id", value="com.example:id/favoriteicon"),
            ],
        )
        resolver.register_all({"favoriteicon": entry})

        driver = MagicMock()
        wrong1 = _mock_element(x=434, y=1372, w=74, h=74)  # first match, but wrong bounds
        right = _mock_element(x=434, y=628, w=74, h=74)
        wrong2 = _mock_element(x=434, y=2116, w=74, h=74)
        driver.find_elements.return_value = [wrong1, right, wrong2]

        result = resolver.resolve("favoriteicon", driver)
        assert result is right
        # find_elements should be called with id strategy
        driver.find_elements.assert_called()
        called_by = driver.find_elements.call_args[0][0]
        assert called_by == AppiumBy.ID

    def test_native_accessibility_id_enumerates(self):
        from appium.webdriver.common.appiumby import AppiumBy

        resolver = RefResolver()
        entry = _make_entry(
            bounds=(434, 628, 508, 702),
            strategies=[
                LocatorStrategy(by="accessibility_id", value="お気に入り"),
            ],
        )
        resolver.register_all({"favoriteicon": entry})

        driver = MagicMock()
        wrong = _mock_element(x=0, y=0, w=10, h=10)
        right = _mock_element(x=434, y=628, w=74, h=74)
        driver.find_elements.return_value = [wrong, right]

        result = resolver.resolve("favoriteicon", driver)
        assert result is right
        driver.find_elements.assert_called()
        called_by = driver.find_elements.call_args[0][0]
        assert called_by == AppiumBy.ACCESSIBILITY_ID


class TestRefParsing:
    def test_parse_short_ref_forms(self):
        assert parse_ref("btn").ref == "btn"
        assert parse_ref("[ref:btn]").ref == "btn"
        assert parse_ref("ref:btn").ref == "btn"

    def test_parse_snapshot_qualified_ref(self):
        parsed = parse_ref("[ref:snap-1:btn]")
        assert parsed.snapshot_id == "snap-1"
        assert parsed.ref == "btn"
        assert parsed.display == "snap-1:btn"
