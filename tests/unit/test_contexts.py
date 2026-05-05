"""Tests for context inspection and switching tools."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from appium_cli.tools.contexts import (
    CHROMIUM_CONTEXT,
    NATIVE_CONTEXT,
    WEB_CONTEXT_PREFIX,
    available_contexts,
    current_context,
    is_web_context,
    resolve_context,
    switch_to_context,
    using_context,
    list_contexts,
    get_context,
    switch_context,
    native_switch,
    webview_switch,
    webview_status,
)
from appium_cli.utils.errors import AppiumCliError


@pytest.fixture(autouse=True)
def _reset_state():
    from appium_cli.daemon import state
    state.current_context = NATIVE_CONTEXT
    state.driver = None
    yield
    state.current_context = NATIVE_CONTEXT
    state.driver = None


def _mock_driver(context="NATIVE_APP", contexts=None):
    driver = MagicMock()
    driver.current_context = context
    driver.contexts = contexts or ["NATIVE_APP"]
    return driver


class TestIsWebContext:
    def test_native(self):
        assert is_web_context("NATIVE_APP") is False

    def test_webview_prefix(self):
        assert is_web_context("WEBVIEW_com.example") is True

    def test_chromium(self):
        assert is_web_context("CHROMIUM") is True

    def test_random_string(self):
        assert is_web_context("SOME_OTHER") is False

    def test_webview_chrome(self):
        assert is_web_context("WEBVIEW_chrome") is True


class TestCurrentContext:
    def test_syncs_state(self):
        from appium_cli.daemon import state
        driver = _mock_driver("CHROMIUM")
        result = current_context(driver)
        assert result == "CHROMIUM"
        assert state.current_context == "CHROMIUM"

    def test_none_defaults_to_native(self):
        from appium_cli.daemon import state
        driver = MagicMock()
        driver.current_context = None
        result = current_context(driver)
        assert result == NATIVE_CONTEXT
        assert state.current_context == NATIVE_CONTEXT


class TestAvailableContexts:
    def test_includes_native(self):
        driver = _mock_driver(contexts=["WEBVIEW_com.example"])
        result = available_contexts(driver)
        assert NATIVE_CONTEXT in result
        assert "WEBVIEW_com.example" in result

    def test_native_already_present(self):
        driver = _mock_driver(contexts=["NATIVE_APP", "CHROMIUM"])
        result = available_contexts(driver)
        assert result.count("NATIVE_APP") == 1


class TestResolveContext:
    def test_native(self):
        driver = _mock_driver()
        assert resolve_context("native", driver) == NATIVE_CONTEXT

    def test_current(self):
        driver = _mock_driver("CHROMIUM")
        assert resolve_context("current", driver) == "CHROMIUM"

    def test_webview_found(self):
        driver = _mock_driver(contexts=["NATIVE_APP", "WEBVIEW_com.example"])
        assert resolve_context("webview", driver) == "WEBVIEW_com.example"

    def test_webview_not_available(self):
        driver = _mock_driver(contexts=["NATIVE_APP"])
        with pytest.raises(AppiumCliError, match="No WebView context"):
            resolve_context("webview", driver)

    def test_auto_returns_current_web(self):
        driver = _mock_driver("CHROMIUM", contexts=["NATIVE_APP", "CHROMIUM"])
        assert resolve_context("auto", driver) == "CHROMIUM"

    def test_auto_returns_first_web(self):
        driver = _mock_driver("NATIVE_APP", contexts=["NATIVE_APP", "WEBVIEW_x"])
        assert resolve_context("auto", driver) == "WEBVIEW_x"

    def test_auto_returns_native_when_no_web(self):
        driver = _mock_driver("NATIVE_APP", contexts=["NATIVE_APP"])
        assert resolve_context("auto", driver) == NATIVE_CONTEXT

    def test_exact_name(self):
        driver = _mock_driver(contexts=["NATIVE_APP", "WEBVIEW_com.example"])
        assert resolve_context("WEBVIEW_com.example", driver) == "WEBVIEW_com.example"

    def test_case_insensitive_fallback(self):
        driver = _mock_driver(contexts=["NATIVE_APP", "CHROMIUM"])
        assert resolve_context("chromium", driver) == "CHROMIUM"

    def test_unknown_context_raises(self):
        driver = _mock_driver(contexts=["NATIVE_APP"])
        with pytest.raises(AppiumCliError, match="not found"):
            resolve_context("UNKNOWN_CTX", driver)


class TestSwitchToContext:
    def test_switches_when_different(self):
        driver = _mock_driver("NATIVE_APP", contexts=["NATIVE_APP", "CHROMIUM"])
        result = switch_to_context("chromium", driver)
        assert result == "CHROMIUM"
        driver.switch_to.context.assert_called_once_with("CHROMIUM")

    def test_no_switch_when_same(self):
        driver = _mock_driver("NATIVE_APP")
        switch_to_context("native", driver)
        driver.switch_to.context.assert_not_called()


class TestUsingContext:
    def test_restores_context(self):
        driver = _mock_driver("NATIVE_APP", contexts=["NATIVE_APP", "CHROMIUM"])
        with using_context("chromium", driver, restore=True) as ctx:
            assert ctx == "CHROMIUM"
            # Simulate being in CHROMIUM now
            driver.current_context = "CHROMIUM"
        driver.switch_to.context.assert_any_call("CHROMIUM")
        # Restore call
        assert driver.switch_to.context.call_count == 2

    def test_no_restore(self):
        driver = _mock_driver("NATIVE_APP", contexts=["NATIVE_APP", "CHROMIUM"])
        with using_context("chromium", driver, restore=False):
            driver.current_context = "CHROMIUM"
        # Only the switch call, no restore
        driver.switch_to.context.assert_called_once_with("CHROMIUM")


class TestToolFunctions:
    def test_list_contexts(self):
        from appium_cli.daemon import state
        driver = _mock_driver("NATIVE_APP", contexts=["NATIVE_APP", "CHROMIUM"])
        state.driver = driver
        result = list_contexts()
        assert "NATIVE_APP" in result
        assert "CHROMIUM" in result
        assert "(current)" in result
        assert "[native]" in result
        assert "[web]" in result

    def test_get_context(self):
        from appium_cli.daemon import state
        driver = _mock_driver("CHROMIUM")
        state.driver = driver
        assert get_context() == "CHROMIUM"

    def test_switch_context(self):
        from appium_cli.daemon import state
        driver = _mock_driver("NATIVE_APP", contexts=["NATIVE_APP", "CHROMIUM"])
        state.driver = driver
        result = switch_context("chromium")
        assert "CHROMIUM" in result

    def test_native_switch(self):
        from appium_cli.daemon import state
        driver = _mock_driver("CHROMIUM", contexts=["NATIVE_APP", "CHROMIUM"])
        state.driver = driver
        result = native_switch()
        assert "NATIVE_APP" in result

    def test_webview_switch_auto(self):
        from appium_cli.daemon import state
        driver = _mock_driver("NATIVE_APP", contexts=["NATIVE_APP", "WEBVIEW_com.example"])
        state.driver = driver
        result = webview_switch()
        assert "WEBVIEW_com.example" in result

    def test_webview_switch_explicit(self):
        from appium_cli.daemon import state
        driver = _mock_driver("NATIVE_APP", contexts=["NATIVE_APP", "CHROMIUM"])
        state.driver = driver
        result = webview_switch("CHROMIUM")
        assert "CHROMIUM" in result

    def test_webview_switch_not_web_raises(self):
        from appium_cli.daemon import state
        driver = _mock_driver("NATIVE_APP", contexts=["NATIVE_APP"])
        state.driver = driver
        with pytest.raises(AppiumCliError, match="not a WebView"):
            webview_switch("NATIVE_APP")

    def test_webview_status_available(self):
        from appium_cli.daemon import state
        driver = _mock_driver("NATIVE_APP", contexts=["NATIVE_APP", "CHROMIUM"])
        state.driver = driver
        result = webview_status()
        assert "webview_available: true" in result

    def test_webview_status_unavailable(self):
        from appium_cli.daemon import state
        driver = _mock_driver("NATIVE_APP", contexts=["NATIVE_APP"])
        state.driver = driver
        result = webview_status()
        assert "webview_available: false" in result
        assert "hints:" in result

    def test_driver_not_initialized_raises(self):
        with pytest.raises(ValueError, match="not initialized"):
            list_contexts()
