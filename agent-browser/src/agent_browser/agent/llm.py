"""Thin OpenAI Responses API client with usage tracking."""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from agent_browser.agent.brain import build_agent_brain_schema
from agent_browser.config import AgentBrowserConfig
from agent_browser.token_counter import (
    CallUsage,
    OpenAIPricingCalculator,
    ToolTokenAttribution,
    UsageTracker,
)

logger = logging.getLogger(__name__)


def _agent_brain_text_config() -> dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "name": "AgentBrain",
            "schema": build_agent_brain_schema(),
            "strict": True,
        }
    }


class ResponsesClient:
    def __init__(self, cfg: AgentBrowserConfig, usage_tracker: UsageTracker | None = None) -> None:
        self._cfg = cfg
        self._client = AsyncOpenAI(api_key=cfg.openai_api_key)
        self._usage_tracker = usage_tracker or UsageTracker(primary_model=cfg.model)

    @property
    def call_usages(self) -> list[CallUsage]:
        return self._usage_tracker.calls

    def _record_usage(
        self,
        response: Any,
        *,
        call_type: str,
        step_index: int | None = None,
        phase: str | None = None,
        tool_attributions: list[ToolTokenAttribution] | None = None,
    ) -> None:
        """Extract and accumulate usage from a Responses API response."""
        call = self._usage_tracker.record_responses_response(
            response,
            model=self._cfg.model,
            call_type=call_type,
            step_index=step_index,
            phase=phase,
            tool_attributions=tool_attributions,
        )
        if call is None:
            return
        call_idx = len(self.call_usages)

        try:
            cost = OpenAIPricingCalculator.cost_for(
                self._cfg.model, call.input_tokens, call.cached_tokens, call.output_tokens
            )
            cost_str = f"${cost['total_cost']:.6f}"
        except ValueError as exc:
            cost_str = f"uncomputable ({exc})"

        logger.info(
            "[token] call #%d type=%s model=%s step=%s in=%d cached=%d out=%d reasoning=%d total=%d cost=%s",
            call_idx,
            call_type,
            self._cfg.model,
            step_index,
            call.input_tokens,
            call.cached_tokens,
            call.output_tokens,
            call.reasoning_tokens,
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
        step_index: int | None = None,
        phase: str | None = None,
        tool_attributions: list[ToolTokenAttribution] | None = None,
    ) -> Any:
        request: dict[str, Any] = {
            "model": self._cfg.model,
            "instructions": instructions,
            "input": input_items,
            "store": False,
            "max_output_tokens": self._cfg.max_output_tokens,
        }
        if tools is not None:
            request["tools"] = tools
            request["tool_choice"] = "required"
            request["parallel_tool_calls"] = False
        else:
            request["text"] = _agent_brain_text_config()
        if self._cfg.reasoning_effort:
            request["reasoning"] = {"effort": self._cfg.reasoning_effort}
        if not self._cfg.model.startswith("gpt-5"):
            request["temperature"] = self._cfg.temperature
        response = await self._client.responses.create(**request)
        self._record_usage(
            response,
            call_type=call_type,
            step_index=step_index,
            phase=phase,
            tool_attributions=tool_attributions,
        )
        return response
