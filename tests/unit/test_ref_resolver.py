"""Tests for RefResolver bounds verification and multi-strategy resolution."""

from unittest.mock import MagicMock, patch

import pytest

from appium_cli.core.ref_resolver import ElementNotFoundError, RefResolver, _CoordinateElement
from appium_cli.core.snapshot import LocatorStrategy, RefEntry


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
        driver.find_element.return_value = el

        result = resolver.resolve("[ref:btn]", driver)
        assert result == el

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
        resolver.register_all({"a": _make_entry()})
        resolver.clear()
        assert not resolver.has("a")
