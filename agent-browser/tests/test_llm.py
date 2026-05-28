"""Tests for Responses API request construction."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_browser.agent.llm import ResponsesClient
from agent_browser.config import AgentBrowserConfig


class FakeResponses:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.next_usage: Any = None

    async def create(self, **request: Any) -> Any:
        self.requests.append(request)
        return SimpleNamespace(usage=self.next_usage)


class FakeAsyncOpenAI:
    instances: list["FakeAsyncOpenAI"] = []

    def __init__(self, *, api_key: str | None) -> None:
        self.api_key = api_key
        self.responses = FakeResponses()
        self.instances.append(self)


@pytest.fixture(autouse=True)
def clear_fake_clients() -> None:
    FakeAsyncOpenAI.instances.clear()


@pytest.mark.asyncio
async def test_action_call_requires_tool_and_omits_agent_brain_text_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_browser.agent.llm.AsyncOpenAI", FakeAsyncOpenAI)
    cfg = AgentBrowserConfig(model="gpt-4.1", openai_api_key="test-key")
    client = ResponsesClient(cfg)

    await client.create(
        input_items=[{"role": "user", "content": [{"type": "input_text", "text": "go"}]}],
        instructions="instructions",
        tools=[{"type": "function", "name": "snapshot", "parameters": {"type": "object"}}],
        call_type="action",
    )

    request = FakeAsyncOpenAI.instances[0].responses.requests[0]
    assert request["tool_choice"] == "required"
    assert request["parallel_tool_calls"] is False
    assert "tools" in request
    assert "text" not in request


@pytest.mark.asyncio
async def test_brain_call_uses_agent_brain_text_format_without_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_browser.agent.llm.AsyncOpenAI", FakeAsyncOpenAI)
    cfg = AgentBrowserConfig(model="gpt-4.1", openai_api_key="test-key")
    client = ResponsesClient(cfg)

    await client.create(
        input_items=[{"role": "user", "content": [{"type": "input_text", "text": "think"}]}],
        instructions="instructions",
        tools=None,
        call_type="brain",
    )

    request = FakeAsyncOpenAI.instances[0].responses.requests[0]
    assert "tools" not in request
    assert "tool_choice" not in request
    assert request["text"]["format"]["name"] == "AgentBrain"
    assert request["text"]["format"]["strict"] is True


@pytest.mark.asyncio
async def test_records_response_usage_with_step_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_browser.agent.llm.AsyncOpenAI", FakeAsyncOpenAI)
    cfg = AgentBrowserConfig(model="gpt-4.1", openai_api_key="test-key")
    client = ResponsesClient(cfg)
    FakeAsyncOpenAI.instances[0].responses.next_usage = SimpleNamespace(
        input_tokens=111,
        input_tokens_details=SimpleNamespace(cached_tokens=11),
        output_tokens=22,
        output_tokens_details=SimpleNamespace(reasoning_tokens=5),
    )

    await client.create(
        input_items=[{"role": "user", "content": [{"type": "input_text", "text": "think"}]}],
        instructions="instructions",
        tools=None,
        call_type="brain",
        step_index=3,
        phase="brain",
    )

    assert len(client.call_usages) == 1
    call = client.call_usages[0]
    assert call.model == "gpt-4.1"
    assert call.call_type == "brain"
    assert call.step_index == 3
    assert call.input_tokens == 111
    assert call.cached_tokens == 11
    assert call.output_tokens == 22
    assert call.reasoning_tokens == 5
