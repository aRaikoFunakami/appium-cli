"""Tests for the browser-agent ReAct loop helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from agent_browser.agent.loop import (
    _build_billing_info,
    _extract_text_with_diagnostics,
    _latest_observation_from_result,
    _items_to_input,
    _tool_output_item,
    run_react_loop,
)
from agent_browser.appium_tools import BrowserAgentContext, ToolExecutionResult
from agent_browser.config import AgentBrowserConfig
from agent_browser.memory import WorkingMemory
from agent_browser.token_counter import CallUsage, UsageTracker


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


def test_tool_output_item_does_not_truncate_successful_output() -> None:
    cfg = AgentBrowserConfig(max_action_result_chars=10)
    result = ToolExecutionResult(
        name="web_query",
        args_summary='{"selector":"a"}',
        output="x" * 1000,
        ok=True,
        duration_ms=1.0,
    )

    item = _tool_output_item({"call_id": "call_1"}, result, cfg)

    assert item["output"] == "x" * 1000


def test_tool_output_item_still_truncates_errors() -> None:
    cfg = AgentBrowserConfig(max_error_chars=40)
    result = ToolExecutionResult(
        name="click",
        args_summary='{"ref":"missing"}',
        output="ERROR: " + "x" * 1000,
        ok=False,
        duration_ms=1.0,
    )

    item = _tool_output_item({"call_id": "call_1"}, result, cfg)

    assert len(str(item["output"])) <= 40
    assert "..." in str(item["output"])


def test_latest_observation_from_result_does_not_truncate() -> None:
    cfg = AgentBrowserConfig(max_observation_chars=10)
    result = ToolExecutionResult(
        name="web_query",
        args_summary='{"selector":"a"}',
        output="y" * 1000,
        ok=True,
        duration_ms=1.0,
    )

    assert _latest_observation_from_result(result, cfg) == "y" * 1000


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


@pytest.mark.asyncio
async def test_run_react_loop_treats_action_text_without_tool_call_as_protocol_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_brain_json = json.dumps(
        {
            "evaluation": "premature text response",
            "working_state": "one article captured",
            "next_goal": "navigate to the next article",
            "is_done": False,
            "success": False,
            "result": None,
        }
    )

    class TextOnlyActionResponse:
        output_text = valid_brain_json
        output = [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": valid_brain_json}],
            }
        ]
        usage = None

    class FakeResponsesClient:
        def __init__(
            self,
            cfg: AgentBrowserConfig,
            usage_tracker: UsageTracker | None = None,
        ) -> None:
            self.call_usages: list[CallUsage] = []

        async def create(self, **kwargs: Any) -> Any:
            assert kwargs["call_type"] == "action"
            return TextOnlyActionResponse()

    monkeypatch.setattr("agent_browser.agent.loop.ResponsesClient", FakeResponsesClient)
    monkeypatch.setattr(
        "agent_browser.agent.loop.get_response_tool_schemas",
        lambda: [{"type": "function", "name": "snapshot", "parameters": {"type": "object"}}],
    )

    cfg = AgentBrowserConfig(max_turns=5, max_no_progress_steps=10, verify_with_llm=False)
    memory = WorkingMemory(goal="collect three articles")
    context = BrowserAgentContext(config=cfg, memory=memory)

    result = await run_react_loop(goal=memory.goal, cfg=cfg, context=context)

    assert result.success is False
    assert result.verification_reason == "action response missing tool call"
    assert result.tool_calls == 0
    assert "without tool calls" in result.summary
