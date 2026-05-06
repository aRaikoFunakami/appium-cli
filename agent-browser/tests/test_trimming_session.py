"""Tests for TrimmingSession."""
from __future__ import annotations

import pytest

from agent_browser.trimming_session import TrimmingSession


@pytest.mark.asyncio
async def test_keeps_recent_outputs_verbatim() -> None:
    s = TrimmingSession(keep_recent=2, size_threshold=10)
    big = "x" * 100
    await s.add_items(
        [
            {"type": "function_call", "name": "snapshot", "call_id": "1", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "1", "output": big},
            {"type": "function_call", "name": "snapshot", "call_id": "2", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "2", "output": big},
            {"type": "function_call", "name": "snapshot", "call_id": "3", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "3", "output": big},
        ]
    )
    items = await s.get_items()
    outputs = [it for it in items if it.get("type") == "function_call_output"]
    assert outputs[0]["output"].startswith("[earlier tool output omitted")
    assert outputs[1]["output"] == big
    assert outputs[2]["output"] == big


@pytest.mark.asyncio
async def test_small_outputs_not_trimmed() -> None:
    s = TrimmingSession(keep_recent=1, size_threshold=100)
    await s.add_items(
        [
            {"type": "function_call_output", "call_id": "1", "output": "short"},
            {"type": "function_call_output", "call_id": "2", "output": "x" * 200},
        ]
    )
    items = await s.get_items()
    assert items[0]["output"] == "short"
    assert items[1]["output"] == "x" * 200


@pytest.mark.asyncio
async def test_function_calls_preserved() -> None:
    s = TrimmingSession(keep_recent=1, size_threshold=10)
    await s.add_items(
        [
            {"type": "function_call", "name": "tap", "call_id": "1", "arguments": '{"ref":"x"}'},
            {"type": "function_call_output", "call_id": "1", "output": "x" * 100},
            {"type": "function_call_output", "call_id": "2", "output": "x" * 100},
        ]
    )
    items = await s.get_items()
    assert items[0]["type"] == "function_call"
    assert items[0]["arguments"] == '{"ref":"x"}'


@pytest.mark.asyncio
async def test_pop_and_clear() -> None:
    s = TrimmingSession()
    await s.add_items([{"type": "message", "role": "user", "content": "hi"}])
    popped = await s.pop_item()
    assert popped is not None
    await s.clear_session()
    assert await s.get_items() == []
