"""Direct appium-cli tool bridge for the custom browser agent."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from appium_cli.openai_tools import call_tool

from agent_browser.config import AgentBrowserConfig
from agent_browser.guardrails import classify_tool_call, is_approved, requires_approval
from agent_browser.memory import WorkingMemory, domain_of
from agent_browser.schemas import MemoryEvent, ObservationSummary, SafetyCategory, ToolCallRecord

logger = logging.getLogger(__name__)

_FAILED_PREFIX = "FAILED"

_OBSERVATION_PRODUCING = frozenset({
    "snapshot",
    "web_snapshot",
    "snapshot_show",
    "snapshot_actionable_tree",
    "webview_url",
    "webview_title",
    "get_page_source",
    "describe",
    "find_by_text",
    "get_text",
    "snapshot_search",
    "snapshot_refs",
    "web_query",
    "web_text",
    "web_eval",
})


class EpisodicMemoryProtocol:
    def record(self, event: MemoryEvent) -> None: ...  # pragma: no cover


class BrowserAgentContext:
    """Run context shared by the custom loop and tool executor."""

    def __init__(
        self,
        config: AgentBrowserConfig,
        memory: WorkingMemory,
        episodic: EpisodicMemoryProtocol | None = None,
    ) -> None:
        self.config = config
        self.memory = memory
        self.episodic = episodic


@dataclass(slots=True)
class ToolExecutionResult:
    name: str
    args_summary: str
    output: str
    ok: bool
    duration_ms: float
    artifact_path: str | None = None

    def short_output(self, *, max_error_chars: int, max_result_chars: int) -> str:
        limit = max_result_chars if self.ok else max_error_chars
        if len(self.output) <= limit:
            return self.output
        if not self.ok and limit >= 20:
            half = max(1, (limit - 5) // 2)
            return self.output[:half] + " ... " + self.output[-half:]
        return self.output[: limit - 20] + "... [trimmed]"


def _summarize_args(args: dict[str, Any] | None, *, limit: int = 240) -> str:
    if not args:
        return "{}"
    safe: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            safe[key] = value if len(value) <= 120 else value[:120] + f"...<+{len(value) - 120}>"
        else:
            safe[key] = value
    rendered = json.dumps(safe, ensure_ascii=False, default=str)
    return rendered if len(rendered) <= limit else rendered[:limit] + "..."


def _normalize_snapshot_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name not in {"snapshot", "web_snapshot"}:
        return args

    needs_normalize = "depth" in args or "filename" in args
    if not needs_normalize:
        return args

    scope = args.get("scope")
    target = args.get("target")
    ref = args.get("ref")
    positional_target = target or ref

    normalized = dict(args)

    # Strip depth for full-page observations (keep for scoped snapshots)
    if "depth" in normalized:
        if not positional_target and scope in (None, "", "full"):
            normalized.pop("depth", None)

    # Strip filename: agent workflows should not write arbitrary files to cwd.
    # Snapshot bundles are already persisted under .appium-cli/snapshots/.
    normalized.pop("filename", None)

    return normalized


def _parse_screenshot_payload(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("type") != "screenshot":
        return None
    return payload


def _save_screenshot_fallback(payload: dict[str, Any], artifacts_dir: Path) -> str | None:
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
    full_path = artifacts_dir / f"screenshot_{timestamp}_{region}.png"
    full_path.write_bytes(raw)
    return str(full_path)


def _prepare_screenshot_result(text: str, artifacts_dir: Path) -> tuple[str | None, str] | None:
    payload = _parse_screenshot_payload(text)
    if payload is None:
        return None

    artifact_path = payload.get("path")
    if not isinstance(artifact_path, str) or not artifact_path:
        artifact_path = _save_screenshot_fallback(payload, artifacts_dir)

    compact: dict[str, Any] = {
        "type": "screenshot",
        "region": payload.get("region", "full"),
    }
    if artifact_path:
        compact["artifact_path"] = artifact_path
    for key in ("size_bytes", "mime_type"):
        if key in payload:
            compact[key] = payload[key]

    return artifact_path, json.dumps(compact, ensure_ascii=False)


def _extract_observation(tool_name: str, text: str) -> ObservationSummary | None:
    if tool_name == "webview_url":
        url = text.strip().splitlines()[0] if text.strip() else None
        return ObservationSummary(source="webview_url", url=url, summary=url)
    if tool_name == "webview_title":
        title = text.strip().splitlines()[0] if text.strip() else None
        return ObservationSummary(source="webview_title", title=title, summary=title)
    if tool_name in {"snapshot", "web_snapshot"}:
        first_lines = "\n".join(text.splitlines()[:80])
        source: Any = "snapshot" if tool_name == "snapshot" else "web_snapshot"
        return ObservationSummary(source=source, summary=first_lines)
    if tool_name == "get_page_source":
        return ObservationSummary(source="other", summary=f"<page_source: {len(text)} chars>")
    return None

def _record_artifacts_from_data(data: dict[str, Any] | None, memory: WorkingMemory | None) -> None:
    if not data or memory is None:
        return
    artifacts = data.get("artifacts")
    if isinstance(artifacts, dict):
        for path in artifacts.values():
            if isinstance(path, str):
                memory.record_artifact(path)


def _serialize_response(name: str, response: dict[str, Any]) -> str:
    if not response.get("ok"):
        error = response.get("error") or "tool failed"
        detail = response.get("detail")
        rendered = f"ERROR: {error}"
        return rendered + (f" ({detail})" if detail else "")

    text = response.get("text") or ""
    if not text and response.get("data") is not None:
        text = json.dumps(response.get("data"), ensure_ascii=False)
    if not text:
        return "OK"
    text = str(text)
    return text


async def execute_appium_tool(
    name: str,
    args: dict[str, Any],
    context: BrowserAgentContext,
) -> ToolExecutionResult:
    """Dispatch one appium-cli tool call through guardrails and memory logging."""

    args = _normalize_snapshot_args(name, args)
    cfg = context.config
    memory = context.memory
    decision = classify_tool_call(name, args)
    args_summary = _summarize_args(args)

    if decision.category == SafetyCategory.BLOCKED:
        message = f"REFUSED: {decision.reason}"
        memory.tool_calls.append(ToolCallRecord(tool_name=name, arguments_summary=args_summary, duration_ms=0.0, ok=False, error=message))
        memory.record_failure(message)
        return ToolExecutionResult(name, args_summary, message, False, 0.0)

    if requires_approval(decision) and not is_approved(memory, decision):
        key = decision.approval_key or f"{name}:sensitive"
        message = (
            f"APPROVAL_REQUIRED: action '{name}' is sensitive ({decision.matched_pattern}). "
            f"Approval key: {key}."
        )
        memory.tool_calls.append(ToolCallRecord(tool_name=name, arguments_summary=args_summary, duration_ms=0.0, ok=False, error="approval_required"))
        return ToolExecutionResult(name, args_summary, message, False, 0.0)

    started = time.perf_counter()
    logger.info("[tool] -> %s %s", name, args_summary)
    try:
        response: dict[str, Any] = await asyncio.to_thread(call_tool, name, args)
    except Exception as exc:
        duration_ms = (time.perf_counter() - started) * 1000
        message = f"ERROR: tool dispatch raised: {type(exc).__name__}: {exc}"
        logger.exception("[tool] !! %s failed", name)
        memory.tool_calls.append(ToolCallRecord(tool_name=name, arguments_summary=args_summary, duration_ms=duration_ms, ok=False, error=message))
        memory.record_failure(message)
        return ToolExecutionResult(name, args_summary, message, False, duration_ms)

    duration_ms = (time.perf_counter() - started) * 1000
    rendered = _serialize_response(name, response)
    ok = bool(response.get("ok"))
    raw_text = str(response.get("text") or "")
    if ok and raw_text.lstrip().startswith(_FAILED_PREFIX):
        ok = False

    artifact_path: str | None = None
    if ok and name == "screenshot":
        screenshot_result = _prepare_screenshot_result(response.get("text") or "", cfg.artifacts_dir)
        if screenshot_result is not None:
            artifact_path, rendered = screenshot_result
        if artifact_path:
            memory.record_artifact(artifact_path)

    if ok:
        _record_artifacts_from_data(response.get("data"), memory)

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

    if ok and name in _OBSERVATION_PRODUCING:
        observation = _extract_observation(name, response.get("text") or "")
        if observation is not None:
            memory.latest_observation = observation
            if observation.url:
                memory.current_url = observation.url

    if context.episodic is not None:
        context.episodic.record(
            MemoryEvent(
                event_type="tool_success" if ok else "tool_failure",  # type: ignore[arg-type]
                tool_name=name,
                domain=domain_of(memory.current_url),
                selector_ref=args.get("ref"),
                retry_count=memory.retry_counts.get(name),
                detail=rendered[:240] if not ok else None,
            )
        )

    logger.info("[tool] <- %s ok=%s duration_ms=%.0f result_chars=%d", name, ok, duration_ms, len(rendered))
    return ToolExecutionResult(name, args_summary, rendered, ok, duration_ms, artifact_path)
