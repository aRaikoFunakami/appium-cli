"""Custom ReAct loop for mobile browser automation."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from agent_browser.agent.brain import parse_agent_brain
from agent_browser.agent.history import (
    HistoryItem, INFO_ONLY_TOOLS, LoopDetector, OperationHistory,
)
from agent_browser.agent.llm import ResponsesClient
from agent_browser.agent.prompt import build_input_items, build_system_prompt
from agent_browser.agent.registry import get_response_tool_schemas
from agent_browser.agent.state import BrowserOperationState
from agent_browser.agent.verifier import CompletionVerifier, LLMJudge, StructuralGuard
from agent_browser.appium_tools import BrowserAgentContext, ToolExecutionResult, execute_appium_tool
from agent_browser.appium_tools import _summarize_args as _args_summary
from agent_browser.config import AgentBrowserConfig
from agent_browser.schemas import BillingInfo, MemoryEvent, TaskResult
from agent_browser.token_counter import CallUsage, OpenAIPricingCalculator

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


def _extract_text_with_diagnostics(response: Any, _logger: logging.Logger) -> str:
    """Extract text from response with diagnostics for debugging parse failures."""
    output_items = getattr(response, "output", []) or []
    item_count = len(output_items)

    # Inspect each item's type
    item_types: list[str] = []
    text_items: list[str] = []
    for item in output_items:
        payload = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
        if isinstance(payload, dict):
            itype = payload.get("type", "unknown")
            item_types.append(itype)
            # Detect text-bearing items
            if "text" in itype or itype == "message":
                content = payload.get("content")
                if isinstance(content, list):
                    parts = []
                    for c in content:
                        if isinstance(c, dict):
                            parts.append(str(c.get("text") or c.get("content") or ""))
                    joined = "\n".join(p for p in parts if p)
                    if joined:
                        text_items.append(joined)
                elif isinstance(payload.get("text"), str) and payload["text"]:
                    text_items.append(payload["text"])
        else:
            item_types.append(type(item).__name__)

    # Determine text source and value
    if len(text_items) > 1:
        _logger.warning(
            "[loop] multiple text items detected (%d); using first item only. types=%s",
            len(text_items),
            item_types,
        )
        text = text_items[0]
        source = "first_of_multiple"
    else:
        raw_text = getattr(response, "output_text", None)
        if isinstance(raw_text, str) and raw_text:
            text = raw_text
            source = "output_text"
        elif text_items:
            text = text_items[0]
            source = "fallback_single"
        else:
            text = ""
            source = "empty"

    _logger.debug(
        "[loop] response diagnostics: items=%d types=%s source=%s len=%d first200=%.200s last200=%.200s",
        item_count,
        item_types,
        source,
        len(text),
        text[:200],
        text[-200:] if len(text) > 200 else text,
    )
    return text


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
    output = result.output if result.ok else result.short_output(
        max_error_chars=cfg.max_error_chars,
        max_result_chars=len(result.output),
    )
    return {
        "type": "function_call_output",
        "call_id": call.get("call_id"),
        "output": output,
    }


def _latest_observation_from_result(result: ToolExecutionResult, cfg: AgentBrowserConfig) -> str:
    return result.output


def _build_billing_info(call_usages: list[CallUsage], model: str) -> BillingInfo:
    """Aggregate per-call usages into a BillingInfo summary."""
    total_in = sum(c.input_tokens for c in call_usages)
    total_cached = sum(c.cached_tokens for c in call_usages)
    total_out = sum(c.output_tokens for c in call_usages)
    total_cost = 0.0
    billing_status = "ok"
    uncomputable_reason = None
    call_breakdown: list[BillingInfo.BillingCall] = []

    for idx, call in enumerate(call_usages, start=1):
        per_call_status = "ok"
        per_call_reason = None
        per_call_cost: float | None = None
        try:
            cost = OpenAIPricingCalculator.cost_for(
                model, call.input_tokens, call.cached_tokens, call.output_tokens
            )
            total_cost += cost["total_cost"]
            per_call_cost = round(cost["total_cost"], 6)
        except ValueError as exc:
            billing_status = "uncomputable"
            if uncomputable_reason is None:
                uncomputable_reason = str(exc)
            per_call_status = "uncomputable"
            per_call_reason = str(exc)
        call_breakdown.append(
            BillingInfo.BillingCall(
                index=idx,
                call_type=call.call_type if call.call_type in {"action", "brain"} else "unknown",
                input_tokens=call.input_tokens,
                cached_tokens=call.cached_tokens,
                output_tokens=call.output_tokens,
                total_tokens=call.total_tokens,
                cost_usd=per_call_cost,
                billing_status=per_call_status,
                uncomputable_reason=per_call_reason,
            )
        )

    return BillingInfo(
        model=model,
        api_calls=len(call_usages),
        input_tokens=total_in,
        cached_tokens=total_cached,
        output_tokens=total_out,
        total_tokens=total_in + total_out,
        total_cost_usd=round(total_cost, 6) if billing_status == "ok" else None,
        billing_status=billing_status,
        uncomputable_reason=uncomputable_reason,
        call_breakdown=call_breakdown,
    )


def _build_verifier(cfg: AgentBrowserConfig) -> CompletionVerifier:
    """Construct the two-layer completion verifier from config."""
    guard = StructuralGuard(min_result_chars=cfg.min_result_chars)
    judge: LLMJudge | None = None
    if cfg.verify_with_llm and cfg.openai_api_key:
        judge = LLMJudge(
            api_key=cfg.openai_api_key,
            model=cfg.judge_model,
            fail_open=cfg.judge_fail_open,
        )
    return CompletionVerifier(guard=guard, judge=judge)


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
    verifier = _build_verifier(cfg)

    verification_attempts = 0
    start_time = time.monotonic()
    last_progress_step = 0
    prev_observation_hash: int | None = None
    blocked_tools: set[str] = set()
    consecutive_no_tool_calls = 0

    for step in range(1, cfg.max_turns + 1):
        # --- Wall-time safeguard ---
        elapsed = time.monotonic() - start_time
        if elapsed > cfg.max_wall_seconds:
            summary = f"Wall-time limit ({cfg.max_wall_seconds}s) exceeded at step {step}."
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
                billing=_build_billing_info(client.call_usages, cfg.model),
                verification_passed=False,
                verification_reason="wall-time limit exceeded",
                verification_attempts=verification_attempts,
            )

        # --- No-progress safeguard ---
        if step - last_progress_step >= cfg.max_no_progress_steps:
            summary = f"No progress for {cfg.max_no_progress_steps} consecutive steps."
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
                billing=_build_billing_info(client.call_usages, cfg.model),
                verification_passed=False,
                verification_reason="no progress detected",
                verification_attempts=verification_attempts,
            )

        loop_warning = loop_detector.detect()
        input_items = build_input_items(
            state,
            cfg,
            recent_steps=history.recent_lines(),
            compacted_history=history.compacted_history,
            loop_warning=loop_warning,
            reflection=state.consume_reflection(),
            blocked_tools=blocked_tools or None,
        )

        response = await client.create(
            input_items=input_items,
            instructions=build_system_prompt(),
            tools=tools,
            call_type="action",
        )
        calls = _function_calls(response)
        tool_results: list[ToolExecutionResult] = []

        if not calls:
            consecutive_no_tool_calls += 1
            output_items = getattr(response, "output", []) or []
            item_types: list[str] = []
            for item in output_items:
                payload = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
                itype = payload.get("type", "unknown") if isinstance(payload, dict) else type(item).__name__
                item_types.append(str(itype))
            logger.warning(
                "[loop] action response contained no function calls despite required tool choice: items=%d types=%s",
                len(output_items),
                item_types,
            )
            item = HistoryItem(
                step=step,
                action_name=None,
                args_summary="",
                success=False,
                result_summary="action response contained no tool call",
            )
            history.add(item)
            state.last_step = item.to_prompt_line()
            loop_detector.record(None, "", state.latest_observation)
            state.reflection = (
                "The previous action response contained no browser tool call. "
                "Select exactly one available browser tool for the next action."
            )
            if consecutive_no_tool_calls >= 3:
                summary = f"Model produced {consecutive_no_tool_calls} consecutive action responses without tool calls."
                logger.warning("[loop] %s", summary)
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
                    billing=_build_billing_info(client.call_usages, cfg.model),
                    verification_passed=False,
                    verification_reason="action response missing tool call",
                    verification_attempts=verification_attempts,
                )
            continue

        # parallel_tool_calls=False, but execute defensively in returned order.
        output_items: list[dict[str, Any]] = []
        for call in calls:
            name = str(call.get("name") or "")
            args = _parse_args(call.get("arguments"))

            # Block tools that have exceeded max_retries (skip observation tools).
            if name in blocked_tools:
                result = ToolExecutionResult(
                    name, _args_summary(args),
                    f"BLOCKED: '{name}' reached retry limit ({cfg.max_retries}). Use a different tool.",
                    False, 0.0,
                )
            else:
                result = await execute_appium_tool(name, args, context)
                # Check if this tool just hit the retry limit.
                if (
                    not result.ok
                    and name not in INFO_ONLY_TOOLS
                    and context.memory.retry_counts.get(name, 0) >= cfg.max_retries
                ):
                    blocked_tools.add(name)
                    logger.info(
                        "[loop] tool '%s' blocked after %d retries (max_retries=%d)",
                        name, context.memory.retry_counts[name], cfg.max_retries,
                    )

            tool_results.append(result)
            output_items.append(_tool_output_item(call, result, cfg))

        continuation_input = input_items + _items_to_input(getattr(response, "output", []) or []) + output_items
        response = await client.create(
            input_items=continuation_input,
            instructions=build_system_prompt(),
            tools=None,
            call_type="brain",
        )

        text = _extract_text_with_diagnostics(response, logger)
        try:
            brain = parse_agent_brain(text, working_state_cap=cfg.working_state_char_cap)
        except Exception as exc:
            output_items = getattr(response, "output", []) or []
            item_types = []
            for item in output_items:
                payload = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
                itype = payload.get("type", "unknown") if isinstance(payload, dict) else type(item).__name__
                item_types.append(itype)
            logger.error(
                "[loop] AgentBrain parse failed: text_len=%d items=%d types=%s first300=%.300s last300=%.300s",
                len(text),
                len(output_items),
                item_types,
                text[:300],
                text[-300:] if len(text) > 300 else text,
            )
            logger.exception("[loop] failed to parse AgentBrain")
            diag = (
                f"brain_parse_error: {type(exc).__name__}: {exc} "
                f"| text_len={len(text)} items={len(output_items)} types={item_types}"
            )
            context.memory.record_failure(diag[:500])
            state.reflection = "The last model output was invalid JSON. Return valid AgentBrain JSON after the next action."
            brain = None

        primary_result = tool_results[-1] if tool_results else None
        if primary_result is not None:
            consecutive_no_tool_calls = 0
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

            # Track progress: only successful tool calls count as progress.
            # Failed tools must not reset the no-progress counter even if
            # their error text changes the observation hash.
            obs_hash = hash(state.latest_observation)
            if primary_result.ok:
                last_progress_step = step
                prev_observation_hash = obs_hash
            elif obs_hash != prev_observation_hash:
                prev_observation_hash = obs_hash

        if brain is not None:
            state.working_state = brain.working_state
            if brain.is_done:
                # --- Completion verification ---
                vr = await verifier.verify(goal, brain, context.memory)
                if vr.passed:
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
                        billing=_build_billing_info(client.call_usages, cfg.model),
                        verification_passed=True,
                        verification_reason=vr.reason,
                        verification_attempts=verification_attempts,
                    )
                else:
                    verification_attempts += 1
                    logger.info(
                        "[loop] verification FAILED (attempt %d/%d, layer=%s): %s",
                        verification_attempts,
                        cfg.max_verification_retries,
                        vr.layer,
                        vr.reason,
                    )
                    if verification_attempts >= cfg.max_verification_retries:
                        context.memory.record_failure(
                            f"verification_failed: {vr.reason}"
                        )
                        if context.episodic is not None:
                            context.episodic.record(
                                MemoryEvent(
                                    event_type="task_failed",
                                    detail=f"verification failed: {vr.reason}"[:240],
                                )
                            )
                        return TaskResult(
                            goal=goal,
                            success=False,
                            url=context.memory.current_url,
                            summary=brain.result or brain.evaluation or "Verification failed.",
                            notes=brain.next_goal,
                            tool_calls=len(context.memory.tool_calls),
                            retries=context.memory.total_retries(),
                            artifacts=list(context.memory.artifacts),
                            failures=list(context.memory.failures),
                            billing=_build_billing_info(client.call_usages, cfg.model),
                            verification_passed=False,
                            verification_reason=vr.reason,
                            verification_attempts=verification_attempts,
                        )
                    # Feed back to agent and continue
                    state.reflection = vr.feedback
                    brain.is_done = False

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
        billing=_build_billing_info(client.call_usages, cfg.model),
        verification_attempts=verification_attempts,
    )
