"""Custom ReAct loop for mobile browser automation."""

from __future__ import annotations

import json
import logging
from typing import Any

from agent_browser.agent.brain import parse_agent_brain
from agent_browser.agent.history import HistoryItem, LoopDetector, OperationHistory
from agent_browser.agent.llm import ResponsesClient
from agent_browser.agent.prompt import SYSTEM_PROMPT, build_input_items
from agent_browser.agent.registry import get_response_tool_schemas
from agent_browser.agent.state import BrowserOperationState, clamp_text
from agent_browser.appium_tools import BrowserAgentContext, ToolExecutionResult, execute_appium_tool
from agent_browser.config import AgentBrowserConfig
from agent_browser.schemas import MemoryEvent, TaskResult

logger = logging.getLogger(__name__)


def _items_to_input(items: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        if hasattr(item, "model_dump"):
            payload = item.model_dump(exclude_none=True)
        elif isinstance(item, dict):
            payload = dict(item)
        else:
            continue
        payload.pop("id", None)
        normalized.append(payload)
    return normalized


def _output_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text:
        return text
    # Conservative fallback for SDK object variations.
    for item in getattr(response, "output", []) or []:
        payload = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
        if not isinstance(payload, dict):
            continue
        if payload.get("type") == "message":
            content = payload.get("content")
            if isinstance(content, list):
                parts = []
                for c in content:
                    if isinstance(c, dict):
                        parts.append(str(c.get("text") or c.get("content") or ""))
                return "\n".join(p for p in parts if p)
    return ""


def _function_calls(response: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in getattr(response, "output", []) or []:
        payload = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
        if isinstance(payload, dict) and payload.get("type") == "function_call":
            calls.append(payload)
    return calls


def _parse_args(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _tool_output_item(call: dict[str, Any], result: ToolExecutionResult, cfg: AgentBrowserConfig) -> dict[str, Any]:
    return {
        "type": "function_call_output",
        "call_id": call.get("call_id"),
        "output": result.short_output(
            max_error_chars=cfg.max_error_chars,
            max_result_chars=cfg.max_action_result_chars,
        ),
    }


def _latest_observation_from_result(result: ToolExecutionResult, cfg: AgentBrowserConfig) -> str:
    return clamp_text(result.output, cfg.max_observation_chars)


async def run_react_loop(
    *,
    goal: str,
    cfg: AgentBrowserConfig,
    context: BrowserAgentContext,
) -> TaskResult:
    """Run one browser task using a token-bounded custom ReAct loop."""

    client = ResponsesClient(cfg)
    tools = get_response_tool_schemas()
    state = BrowserOperationState(goal=goal, working_state="No browser actions completed yet.")
    history = OperationHistory(recent_steps=cfg.recent_steps)
    loop_detector = LoopDetector()

    for step in range(1, cfg.max_turns + 1):
        loop_warning = loop_detector.detect()
        input_items = build_input_items(
            state,
            cfg,
            recent_steps=history.recent_lines(),
            compacted_history=history.compacted_history,
            loop_warning=loop_warning,
            reflection=state.consume_reflection(),
        )

        response = await client.create(
            input_items=input_items,
            instructions=SYSTEM_PROMPT,
            tools=tools,
        )
        calls = _function_calls(response)
        tool_results: list[ToolExecutionResult] = []

        if calls:
            # parallel_tool_calls=False, but execute defensively in returned order.
            output_items: list[dict[str, Any]] = []
            for call in calls:
                name = str(call.get("name") or "")
                args = _parse_args(call.get("arguments"))
                result = await execute_appium_tool(name, args, context)
                tool_results.append(result)
                output_items.append(_tool_output_item(call, result, cfg))

            continuation_input = input_items + _items_to_input(getattr(response, "output", []) or []) + output_items
            response = await client.create(
                input_items=continuation_input,
                instructions=SYSTEM_PROMPT,
                tools=None,
            )

        text = _output_text(response)
        try:
            brain = parse_agent_brain(text, working_state_cap=cfg.working_state_char_cap)
        except Exception as exc:
            logger.exception("[loop] failed to parse AgentBrain")
            context.memory.record_failure(f"brain_parse_error: {type(exc).__name__}: {exc}")
            state.reflection = "The last model output was invalid JSON. Return valid AgentBrain JSON after the next action."
            brain = None

        primary_result = tool_results[-1] if tool_results else None
        if primary_result is not None:
            state.latest_observation = _latest_observation_from_result(primary_result, cfg)
            item = HistoryItem(
                step=step,
                action_name=primary_result.name,
                args_summary=primary_result.args_summary,
                success=primary_result.ok,
                result_summary=primary_result.short_output(
                    max_error_chars=cfg.max_error_chars,
                    max_result_chars=cfg.max_action_result_chars,
                ).replace("\n", " "),
            )
            history.add(item)
            state.last_step = item.to_prompt_line()
            loop_detector.record(primary_result.name, primary_result.args_summary, state.latest_observation)
        else:
            item = HistoryItem(
                step=step,
                action_name=None,
                args_summary="",
                success=brain is not None,
                result_summary="no tool call",
            )
            history.add(item)
            state.last_step = item.to_prompt_line()
            loop_detector.record(None, "", state.latest_observation)

        if brain is not None:
            state.working_state = brain.working_state
            if brain.is_done:
                if context.episodic is not None:
                    context.episodic.record(
                        MemoryEvent(
                            event_type="task_complete",
                            detail=(brain.result or brain.evaluation)[:240],
                        )
                    )
                return TaskResult(
                    goal=goal,
                    success=brain.success,
                    url=context.memory.current_url,
                    summary=brain.result or brain.evaluation,
                    notes=brain.next_goal,
                    tool_calls=len(context.memory.tool_calls),
                    retries=context.memory.total_retries(),
                    artifacts=list(context.memory.artifacts),
                    failures=list(context.memory.failures),
                )

        if loop_warning and loop_detector.warning_count >= 3:
            state.reflection = loop_warning

    summary = f"Max turns ({cfg.max_turns}) exceeded before task completion."
    context.memory.record_failure(summary)
    if context.episodic is not None:
        context.episodic.record(MemoryEvent(event_type="task_failed", detail=summary))
    return TaskResult(
        goal=goal,
        success=False,
        url=context.memory.current_url,
        summary=summary,
        tool_calls=len(context.memory.tool_calls),
        retries=context.memory.total_retries(),
        artifacts=list(context.memory.artifacts),
        failures=list(context.memory.failures),
    )
