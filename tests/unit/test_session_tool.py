from __future__ import annotations

import pytest
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

from appium_cli.daemon import state
from appium_cli.tools.session import get_driver_status, is_driver_alive


@pytest.fixture(autouse=True)
def reset_state():
    state.reset()
    yield
    state.reset()


class AliveDriver:
    @property
    def current_package(self) -> str:
        return "com.example"


class InvalidSessionDriver:
    @property
    def current_package(self) -> str:
        raise InvalidSessionIdException("session is gone")


class WebDriverErrorDriver:
    @property
    def current_package(self) -> str:
        raise WebDriverException("server is gone")


def test_get_driver_status_ready_only_after_webdriver_probe() -> None:
    state.driver = AliveDriver()

    assert is_driver_alive() is True
    assert get_driver_status() == "Driver is initialized and ready"


@pytest.mark.parametrize("driver", [InvalidSessionDriver(), WebDriverErrorDriver()])
def test_get_driver_status_not_ready_when_webdriver_session_is_dead(driver) -> None:
    state.driver = driver

    assert is_driver_alive() is False
    assert get_driver_status() == "Driver is not initialized"


def test_get_driver_status_not_ready_without_driver() -> None:
    assert is_driver_alive() is False
    assert get_driver_status() == "Driver is not initialized"
