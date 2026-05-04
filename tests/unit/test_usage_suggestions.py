from __future__ import annotations

from shlex import quote

import pytest

from appium_cli.__main__ import main
from appium_cli.cli.usage_suggestions import format_suggestion, suggest_usage


def test_suggests_scroll_ref_direction_order() -> None:
    suggestion = suggest_usage(["scroll", "recycler_view", "up"])

    assert suggestion is not None
    assert suggestion.suggestion == "appium-cli scroll up --ref=recycler_view"
    assert "direction first" in suggestion.message


def test_suggests_swipe_ref_direction_order() -> None:
    suggestion = suggest_usage(["swipe", "recycler_view", "left"])

    assert suggestion is not None
    assert suggestion.suggestion == "appium-cli swipe left --ref=recycler_view"


def test_suggests_fling_ref_direction_order() -> None:
    suggestion = suggest_usage(["fling", "recycler_view", "down"])

    assert suggestion is not None
    assert suggestion.suggestion == "appium-cli fling down --ref=recycler_view"


def test_suggests_scroll_element_direction_option() -> None:
    value = "//*[@scrollable='true']"
    suggestion = suggest_usage(["scroll_element", "xpath", "//*[@scrollable='true']", "up"])

    assert suggestion is not None
    assert suggestion.suggestion == f"appium-cli scroll_element xpath {quote(value)} --direction=up"


def test_valid_and_unknown_commands_do_not_suggest() -> None:
    assert suggest_usage(["scroll", "up", "--ref=recycler_view"]) is None
    assert suggest_usage(["tap", "btn_7"]) is None
    assert suggest_usage(["unknown", "recycler_view", "up"]) is None


def test_format_suggestion_mentions_help() -> None:
    suggestion = suggest_usage(["scroll", "recycler_view", "up"])

    assert suggestion is not None
    message = format_suggestion(suggestion)
    assert "Did you mean: appium-cli scroll up --ref=recycler_view" in message
    assert "appium-cli scroll --help" in message


def test_main_preflight_exits_before_typer(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.argv", ["appium-cli", "scroll", "recycler_view", "up"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Did you mean: appium-cli scroll up --ref=recycler_view" in captured.err
