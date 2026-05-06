"""SDK FunctionTool adapters for appium-cli plus custom completion/approval tools.

This module is the single bridge between the OpenAI Agents SDK and the
appium-cli OpenAI tool surface. The Browser Agent must never bypass these
adapters and never touch WebDriver directly.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents import FunctionTool, RunContextWrapper, function_tool
from agents.tool_context import ToolContext

from appium_cli.openai_tools import call_tool, get_openai_tools

from agent_browser.config import AgentBrowserConfig
from agent_browser.guardrails import (
    classify_tool_call,
    is_approved,
    requires_approval,
)
from agent_browser.memory import WorkingMemory, domain_of
from agent_browser.schemas import (
    ApprovalRecord,
    BrowserResultPayload,
    MemoryEvent,
    ObservationSummary,
    SafetyCategory,
    ToolCallRecord,
)

logger = logging.getLogger(__name__)


# Maximum number of characters returned to the model per tool call. Snapshots
# of large pages (e.g. yahoo.co.jp) easily exceed 6KB; truncating too early
# causes the agent to loop on increasing snapshot depth without ever seeing
# the target element. gpt-4.1 has a 1M context window, so 30KB per call is
# safe and avoids that failure mode.
MAX_TOOL_RESULT_CHARS = 30000

# appium-cli tool functions return "FAILED: ..." strings on error (not
# exceptions). The daemon wraps these as ok=True. We detect and flip.
_FAILED_PREFIX = "FAILED"

# Action tools whose results contain an embedded snapshot that should be
# stripped to reduce LLM context size. The agent can call snapshot separately.
_ACTION_TOOLS = frozenset({
    "tap", "click", "fill", "type_text", "scroll", "scroll_up",
    "scroll_down", "scroll_left", "scroll_right", "swipe", "swipe_up",
    "swipe_down", "swipe_left", "swipe_right", "long_press", "double_tap",
    "drag", "fling", "fling_up", "fling_down", "fling_left", "fling_right",
    "pinch_open", "pinch_close", "press_key", "press_keycode", "select",
    "send_keys", "scroll_element", "scroll_to_element", "click_element",
    "activate_app", "set_orientation", "clear", "reload", "go_back",
    "go_forward",
})

# Tools whose textual output is an observation we should record for
# self-correction / verification.
_OBSERVATION_PRODUCING = frozenset({
    "snapshot",
    "web_snapshot",
    "webview_url",
    "webview_title",
    "get_page_source",
    "describe",
    "find_by_text",
    "get_text",
})


class BrowserAgentContext:
    """Container injected into RunContextWrapper.context.

    Aggregates everything the agent or tools need to access during a run:
    config, working memory, episodic memory backend, and pending approvals.
    """

    def __init__(
        self,
        config: AgentBrowserConfig,
        memory: WorkingMemory,
        episodic: "EpisodicMemoryProtocol | None" = None,
    ) -> None:
        self.config = config
        self.memory = memory
        self.episodic = episodic


# Light protocol to avoid circular import with memory module
class EpisodicMemoryProtocol:
    def record(self, event: MemoryEvent) -> None: ...  # pragma: no cover


def _summarize_args(args: dict[str, Any] | None, *, limit: int = 240) -> str:
    """Build a compact, log-safe arguments summary.

    Long string values are truncated but their content is preserved for
    debugging. Real secrets (passwords, tokens) must be protected by the
    safety policy / human_approval gate, not by hiding tool args from logs -
    silently hidden args make every failure impossible to diagnose.
    """
    if not args:
        return "{}"
    safe: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            if len(value) > 120:
                safe[key] = value[:120] + f"...<+{len(value) - 120}>"
            else:
                safe[key] = value
        else:
            safe[key] = value
    rendered = json.dumps(safe, ensure_ascii=False, default=str)
    if len(rendered) > limit:
        rendered = rendered[:limit] + "..."
    return rendered


def _truncate(value: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(value) <= limit:
        return value
    head = value[: limit - 200]
    return head + f"\n\n... [truncated {len(value) - len(head)} chars]"


def _save_screenshot_artifact(text: str, artifacts_dir: Path) -> str | None:
    """Detect a screenshot JSON payload and save the base64 image to disk.

    Returns the artifact path if saved, otherwise None. The original text
    returned to the LLM is replaced with a reference (the caller does that).
    """
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("type") != "screenshot":
        return None
    b64 = payload.get("image_base64")
    if not isinstance(b64, str) or not b64:
        return None
    try:
        raw = base64.b64decode(b64, validate=False)
    except (ValueError, TypeError):
        return None
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
    region = str(payload.get("region", "full")).replace(":", "_").replace("/", "_")
    filename = f"screenshot_{timestamp}_{region}.png"
    full_path = artifacts_dir / filename
    full_path.write_bytes(raw)
    return str(full_path)


def _extract_observation(tool_name: str, text: str) -> ObservationSummary | None:
    """Build an ObservationSummary from the textual result of a tool, if any."""
    if tool_name == "webview_url":
        url = text.strip().splitlines()[0] if text.strip() else None
        return ObservationSummary(source="webview_url", url=url, summary=url)
    if tool_name == "webview_title":
        title = text.strip().splitlines()[0] if text.strip() else None
        return ObservationSummary(source="webview_title", title=title, summary=title)
    if tool_name in {"snapshot", "web_snapshot"}:
        first_lines = "\n".join(text.splitlines()[:6])
        source: Any = "snapshot" if tool_name == "snapshot" else "web_snapshot"
        return ObservationSummary(source=source, summary=first_lines)
    if tool_name == "get_page_source":
        return ObservationSummary(source="other", summary=f"<page_source: {len(text)} chars>")
    return None


def _strip_embedded_snapshot(text: str) -> str:
    """Remove the embedded snapshot from an action tool result.

    Keeps the status prefix (e.g. "OK") and any trailing metadata
    (e.g. "can_scroll_more: True") but drops the snapshot tree body.
    """
    lines = text.split("\n")
    # Find the snapshot header
    snap_start = None
    for i, line in enumerate(lines):
        if line.startswith("screen:") or line.startswith("screen_id:"):
            snap_start = i
            break
    if snap_start is None:
        return text

    # Keep prefix lines before snapshot
    prefix = "\n".join(lines[:snap_start]).rstrip()

    # Scan from end for trailing metadata (after the snapshot body)
    trailing: list[str] = []
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("can_scroll_more:"):
            trailing.insert(0, stripped)
            break
        if stripped.startswith("screen:") or stripped.startswith("screen_id:"):
            break
        if stripped:
            # Could be other trailing metadata in the future
            if ":" in stripped and len(stripped) < 80:
                trailing.insert(0, stripped)
            else:
                break

    result = prefix
    if trailing:
        result += "\n" + "\n".join(trailing)
    return result if result else "OK"


def _serialize_response(name: str, response: dict[str, Any]) -> str:
    """Render the daemon response as a string suitable for the LLM."""
    if response.get("ok"):
        text = response.get("text") or ""
        if not text and response.get("data") is not None:
            text = json.dumps(response.get("data"), ensure_ascii=False)
        if not text:
            return "OK"
        text = str(text)
        # Strip embedded snapshots from action tools to reduce context size.
        # The agent can always call web_snapshot/snapshot for fresh state.
        if name in _ACTION_TOOLS:
            text = _strip_embedded_snapshot(text)
            if len(text) > 400:
                text = text[:400] + "..."
        return _truncate(text)
    error = response.get("error") or "tool failed"
    detail = response.get("detail")
    rendered = f"ERROR: {error}"
    if detail:
        rendered += f" ({detail})"
    return rendered


async def _invoke_appium_tool(
    name: str,
    args_json: str,
    ctx: ToolContext[BrowserAgentContext],
) -> str:
    """Shared async handler that dispatches a single appium-cli tool call."""
    context = ctx.context if ctx else None
    config = context.config if context else AgentBrowserConfig()
    memory = context.memory if context else None

    # Parse arguments
    try:
        parsed_args: dict[str, Any] = json.loads(args_json) if args_json and args_json.strip() else {}
    except json.JSONDecodeError as exc:
        return f"ERROR: invalid arguments JSON: {exc}"

    # Safety check - happens locally, before talking to the daemon.
    decision = classify_tool_call(name, parsed_args)
    args_summary = _summarize_args(parsed_args)

    if decision.category == SafetyCategory.BLOCKED:
        message = f"REFUSED: {decision.reason}"
        logger.warning("[guardrail] BLOCKED %s args=%s reason=%s", name, args_summary, decision.reason)
        if memory is not None:
            memory.tool_calls.append(
                ToolCallRecord(
                    tool_name=name,
                    arguments_summary=args_summary,
                    duration_ms=0.0,
                    ok=False,
                    error=message,
                )
            )
            memory.record_failure(message)
            if context and context.episodic is not None:
                context.episodic.record(
                    MemoryEvent(
                        event_type="tool_failure",
                        tool_name=name,
                        domain=domain_of(memory.current_url),
                        detail=message,
                    )
                )
        return message

    if requires_approval(decision):
        approved = memory is not None and is_approved(memory, decision)
        if not approved:
            key = decision.approval_key or f"{name}:sensitive"
            message = (
                f"APPROVAL_REQUIRED: action '{name}' is sensitive ({decision.matched_pattern}). "
                f"Call human_approval(approval_key='{key}', description=...) before retrying."
            )
            logger.info("[guardrail] sensitive %s pattern=%s key=%s", name, decision.matched_pattern, key)
            if memory is not None:
                memory.tool_calls.append(
                    ToolCallRecord(
                        tool_name=name,
                        arguments_summary=args_summary,
                        duration_ms=0.0,
                        ok=False,
                        error="approval_required",
                    )
                )
            return message

    # Execute via appium-cli daemon. call_tool() is synchronous; offload it.
    started = time.perf_counter()
    logger.info("[tool] -> %s %s", name, args_summary)
    try:
        response: dict[str, Any] = await asyncio.to_thread(call_tool, name, parsed_args)
    except Exception as exc:  # surface unexpected errors to the model
        duration_ms = (time.perf_counter() - started) * 1000
        message = f"ERROR: tool dispatch raised: {type(exc).__name__}: {exc}"
        logger.exception("[tool] !! %s failed", name)
        if memory is not None:
            memory.tool_calls.append(
                ToolCallRecord(
                    tool_name=name,
                    arguments_summary=args_summary,
                    duration_ms=duration_ms,
                    ok=False,
                    error=message,
                )
            )
            memory.record_failure(message)
        return message

    duration_ms = (time.perf_counter() - started) * 1000
    rendered = _serialize_response(name, response)
    ok = bool(response.get("ok"))

    # Detect string-style failures wrapped as ok=True by the daemon.
    raw_text = str(response.get("text") or "")
    if ok and raw_text.lstrip().startswith(_FAILED_PREFIX):
        ok = False

    artifact_path: str | None = None
    if ok and name == "screenshot":
        artifact_path = _save_screenshot_artifact(response.get("text") or "", config.artifacts_dir)
        if artifact_path:
            if memory is not None:
                memory.record_artifact(artifact_path)
            # Replace the noisy base64 with a short reference so the LLM
            # context does not balloon.
            rendered = json.dumps(
                {
                    "type": "screenshot",
                    "artifact_path": artifact_path,
                    "region": json.loads(response.get("text") or "{}").get("region", "full"),
                },
                ensure_ascii=False,
            )

    logger.info(
        "[tool] <- %s ok=%s duration_ms=%.0f result_chars=%d",
        name,
        ok,
        duration_ms,
        len(rendered),
    )

    if memory is not None:
        memory.tool_calls.append(
            ToolCallRecord(
                tool_name=name,
                arguments_summary=args_summary,
                duration_ms=duration_ms,
                ok=ok,
                error=None if ok else rendered[:200],
                artifact_path=artifact_path,
            )
        )
        if not ok:
            memory.record_failure(f"{name}: {rendered[:160]}")
            memory.increment_retry(name)

        # Update working memory observation/url based on tool output.
        if ok and name in _OBSERVATION_PRODUCING:
            observation = _extract_observation(name, response.get("text") or "")
            if observation is not None:
                memory.latest_observation = observation
                if observation.url:
                    memory.current_url = observation.url

        if context and context.episodic is not None:
            event_type = "tool_success" if ok else "tool_failure"
            context.episodic.record(
                MemoryEvent(
                    event_type=event_type,  # type: ignore[arg-type]
                    tool_name=name,
                    domain=domain_of(memory.current_url),
                    selector_ref=parsed_args.get("ref"),
                    retry_count=memory.retry_counts.get(name),
                    detail=rendered[:240] if not ok else None,
                )
            )

    return rendered


def _make_appium_function_tool(schema: dict[str, Any]) -> FunctionTool:
    """Convert an appium-cli OpenAI tool schema into an SDK ``FunctionTool``."""
    func = schema["function"]
    name: str = func["name"]
    description: str = func.get("description", "")
    params: dict[str, Any] = func.get("parameters") or {"type": "object", "properties": {}}

    async def on_invoke(ctx: ToolContext[BrowserAgentContext], args_json: str) -> str:
        return await _invoke_appium_tool(name, args_json, ctx)

    return FunctionTool(
        name=name,
        description=description,
        params_json_schema=params,
        on_invoke_tool=on_invoke,
        # appium-cli schemas use defaults and partial required lists, which
        # OpenAI strict-mode does not allow. We disable strict mode for these.
        strict_json_schema=False,
    )


def make_appium_tools() -> list[FunctionTool]:
    """Build the full set of SDK FunctionTools backed by appium-cli."""
    return [_make_appium_function_tool(schema) for schema in get_openai_tools()]


# ----------------------------------------------------------------------------
# Custom tools: human_approval and browser_result
# ----------------------------------------------------------------------------


@function_tool
async def human_approval(
    ctx: RunContextWrapper[BrowserAgentContext],
    approval_key: str,
    description: str,
) -> str:
    """Request explicit human approval for a sensitive action.

    Args:
        approval_key: Stable identifier returned by an earlier APPROVAL_REQUIRED
            response (for example 'tap:login' or 'fill:payment').
        description: Brief, non-secret description of what will happen if
            approval is granted.

    Returns:
        A short confirmation string. The agent must retry the original tool
        call after the approval is granted.
    """
    memory = ctx.context.memory
    print(
        f"\n[approval] Sensitive action requires confirmation:\n"
        f"  key:   {approval_key}\n"
        f"  what:  {description}\n"
        f"Type 'yes' to approve, anything else to deny: ",
        end="",
        flush=True,
    )
    try:
        response = await asyncio.to_thread(input)
    except EOFError:
        response = ""
    granted = response.strip().lower() in {"y", "yes"}
    record = ApprovalRecord(approval_key=approval_key, granted=granted, note=description)
    memory.record_approval(record)
    if ctx.context.episodic is not None:
        ctx.context.episodic.record(
            MemoryEvent(
                event_type="approval",
                detail=f"key={approval_key} granted={granted} desc={description}",
            )
        )
    if granted:
        logger.info("[approval] GRANTED %s", approval_key)
        return f"APPROVED: {approval_key}. Retry the original tool call now."
    logger.info("[approval] DENIED %s", approval_key)
    return f"DENIED: {approval_key}. Do not proceed with this action."


@function_tool
async def browser_result(
    ctx: RunContextWrapper[BrowserAgentContext],
    success: bool,
    summary: str,
    title: str | None = None,
    url: str | None = None,
    notes: str | None = None,
) -> str:
    """Signal task completion and provide the final structured result.

    Call this tool exactly once when the user's goal has been satisfied
    (success=True) or when you have determined the goal cannot be completed
    (success=False). The agent run will stop after this tool returns.
    """
    payload = BrowserResultPayload(
        success=success,
        summary=summary,
        title=title,
        url=url,
        notes=notes,
    )
    memory = ctx.context.memory
    memory.final_result = payload.model_dump()
    logger.info(
        "[result] success=%s title=%s url=%s",
        payload.success,
        payload.title,
        payload.url,
    )
    if ctx.context.episodic is not None:
        ctx.context.episodic.record(
            MemoryEvent(
                event_type="task_complete" if success else "task_failed",
                detail=summary[:240],
                domain=domain_of(payload.url),
            )
        )
    return f"RESULT_RECORDED success={success}"


def all_tools() -> list[FunctionTool]:
    """Build the full tool set for the Browser Agent."""
    return [*make_appium_tools(), human_approval, browser_result]
