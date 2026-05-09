"""Thin OpenAI Responses API client with usage tracking."""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from agent_browser.agent.brain import build_agent_brain_schema
from agent_browser.config import AgentBrowserConfig
from agent_browser.token_counter import CallUsage, OpenAIPricingCalculator

logger = logging.getLogger(__name__)


class ResponsesClient:
    def __init__(self, cfg: AgentBrowserConfig) -> None:
        self._cfg = cfg
        self._client = AsyncOpenAI(api_key=cfg.openai_api_key)
        self.call_usages: list[CallUsage] = []

    def _record_usage(self, response: Any, *, call_type: str) -> None:
        """Extract and accumulate usage from a Responses API response."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        details = getattr(usage, "input_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) if details else 0
        call = CallUsage(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            cached_tokens=int(cached or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            call_type=call_type,
        )
        self.call_usages.append(call)
        call_idx = len(self.call_usages)

        try:
            cost = OpenAIPricingCalculator.cost_for(
                self._cfg.model, call.input_tokens, call.cached_tokens, call.output_tokens
            )
            cost_str = f"${cost['total_cost']:.6f}"
        except ValueError as exc:
            cost_str = f"uncomputable ({exc})"

        logger.info(
            "[token] call #%d type=%s model=%s in=%d cached=%d out=%d total=%d cost=%s",
            call_idx,
            call_type,
            self._cfg.model,
            call.input_tokens,
            call.cached_tokens,
            call.output_tokens,
            call.total_tokens,
            cost_str,
        )

    async def create(
        self,
        *,
        input_items: list[dict[str, Any]],
        instructions: str,
        tools: list[dict[str, Any]] | None = None,
        call_type: str = "unknown",
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
        response = await self._client.responses.create(**request)
        self._record_usage(response, call_type=call_type)
        return response
