"""Runtime CLI option state shared by command wrappers."""

from __future__ import annotations

from contextvars import ContextVar


_raw_output: ContextVar[bool] = ContextVar("appium_cli_raw_output", default=False)


def set_raw_output(value: bool) -> None:
    _raw_output.set(value)


def get_raw_output() -> bool:
    return _raw_output.get()
