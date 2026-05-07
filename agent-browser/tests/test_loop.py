"""Tests for the browser-agent ReAct loop helpers."""

from __future__ import annotations

from typing import Any

from agent_browser.agent.loop import _items_to_input


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
