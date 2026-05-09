"""Tests for the browser-agent ReAct loop helpers."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agent_browser.agent.loop import (
    _build_billing_info,
    _extract_text_with_diagnostics,
    _items_to_input,
)
from agent_browser.token_counter import CallUsage


class DumpableItem:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self, *, exclude_none: bool) -> dict[str, Any]:
        assert exclude_none is True
        return dict(self._payload)


def test_items_to_input_strips_response_item_id_from_dumpable_items() -> None:
    items = [
        DumpableItem(
            {
                "id": "rs_123",
                "type": "function_call",
                "call_id": "call_123",
                "name": "snapshot",
                "arguments": "{}",
                "status": "completed",
            }
        )
    ]

    assert _items_to_input(items) == [
        {
            "type": "function_call",
            "call_id": "call_123",
            "name": "snapshot",
            "arguments": "{}",
            "status": "completed",
        }
    ]


def test_items_to_input_strips_response_item_id_from_dicts_without_mutating() -> None:
    item = {
        "id": "rs_456",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "ok"}],
    }

    assert _items_to_input([item]) == [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "ok"}],
        }
    ]
    assert item["id"] == "rs_456"


# --- Helpers for _extract_text_with_diagnostics tests ---


class FakeResponse:
    """Minimal fake response object for testing extraction."""

    def __init__(self, output_text: str | None, output: list[Any] | None = None) -> None:
        self.output_text = output_text
        self.output = output or []


# --- Tests for _extract_text_with_diagnostics ---

_test_logger = logging.getLogger("agent_browser.agent.loop")


def test_extract_text_returns_output_text_when_single_item() -> None:
    text = '{"valid": "json"}'
    response = FakeResponse(
        output_text=text,
        output=[DumpableItem({"type": "message", "content": [{"type": "output_text", "text": text}]})],
    )
    result = _extract_text_with_diagnostics(response, _test_logger)
    assert result == text


def test_extract_text_uses_first_item_when_multiple_text_outputs() -> None:
    first_text = '{"a":1}'
    second_text = '{"b":2}'
    response = FakeResponse(
        output_text=first_text + second_text,
        output=[
            DumpableItem({"type": "message", "content": [{"type": "output_text", "text": first_text}]}),
            DumpableItem({"type": "message", "content": [{"type": "output_text", "text": second_text}]}),
        ],
    )
    result = _extract_text_with_diagnostics(response, _test_logger)
    assert result == first_text


def test_extract_text_warns_on_multiple_text_items(caplog: pytest.LogCaptureFixture) -> None:
    first_text = '{"a":1}'
    second_text = '{"b":2}'
    response = FakeResponse(
        output_text=first_text + second_text,
        output=[
            DumpableItem({"type": "message", "content": [{"type": "output_text", "text": first_text}]}),
            DumpableItem({"type": "message", "content": [{"type": "output_text", "text": second_text}]}),
        ],
    )
    with caplog.at_level(logging.WARNING, logger="agent_browser.agent.loop"):
        _extract_text_with_diagnostics(response, _test_logger)
    assert any("multiple text items" in rec.message for rec in caplog.records)


def test_extract_text_fallback_from_message_content() -> None:
    response = FakeResponse(
        output_text=None,
        output=[DumpableItem({"type": "message", "content": [{"type": "text", "text": "fallback value"}]})],
    )
    result = _extract_text_with_diagnostics(response, _test_logger)
    assert result == "fallback value"


def test_extract_text_returns_empty_when_no_text() -> None:
    response = FakeResponse(
        output_text=None,
        output=[DumpableItem({"type": "function_call", "name": "tap", "arguments": "{}"})],
    )
    result = _extract_text_with_diagnostics(response, _test_logger)
    assert result == ""


def test_build_billing_info_includes_per_call_breakdown() -> None:
    usages = [
        CallUsage(input_tokens=1000, cached_tokens=200, output_tokens=100, call_type="action"),
        CallUsage(input_tokens=500, cached_tokens=0, output_tokens=50, call_type="brain"),
    ]

    billing = _build_billing_info(usages, "gpt-5.4")

    assert billing.api_calls == 2
    assert billing.input_tokens == 1500
    assert billing.cached_tokens == 200
    assert billing.output_tokens == 150
    assert len(billing.call_breakdown) == 2
    assert billing.call_breakdown[0].call_type == "action"
    assert billing.call_breakdown[1].call_type == "brain"
    assert billing.call_breakdown[0].total_tokens == 1100
    assert billing.call_breakdown[1].total_tokens == 550
