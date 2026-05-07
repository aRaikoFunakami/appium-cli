"""Thin OpenAI Responses API client."""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from agent_browser.agent.brain import build_agent_brain_schema
from agent_browser.config import AgentBrowserConfig


class ResponsesClient:
    def __init__(self, cfg: AgentBrowserConfig) -> None:
        self._cfg = cfg
        self._client = AsyncOpenAI(api_key=cfg.openai_api_key)

    async def create(
        self,
        *,
        input_items: list[dict[str, Any]],
        instructions: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        request: dict[str, Any] = {
            "model": self._cfg.model,
            "instructions": instructions,
            "input": input_items,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "AgentBrain",
                    "schema": build_agent_brain_schema(),
                    "strict": True,
                }
            },
            "store": False,
            "max_output_tokens": self._cfg.max_output_tokens,
        }
        if tools is not None:
            request["tools"] = tools
            request["tool_choice"] = "auto"
            request["parallel_tool_calls"] = False
        if self._cfg.reasoning_effort:
            request["reasoning"] = {"effort": self._cfg.reasoning_effort}
        if not self._cfg.model.startswith("gpt-5"):
            request["temperature"] = self._cfg.temperature
        return await self._client.responses.create(**request)
