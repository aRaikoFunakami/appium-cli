"""Completion gate: StructuralGuard + LLMJudge over result and tool trace."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from agent_browser.token_counter import UsageTracker

if TYPE_CHECKING:
    from agent_browser.agent.brain import AgentBrain
    from agent_browser.memory import WorkingMemory
    from agent_browser.schemas import ToolCallRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class VerificationResult:
    """Outcome of a single verification check."""

    passed: bool
    layer: Literal["structural", "llm_judge"]
    reason: str
    feedback: str
    missing: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Layer 1 — deterministic structural guards
# ---------------------------------------------------------------------------

class StructuralGuard:
    """Fast, zero-cost checks that catch obviously incomplete results."""

    # Patterns that indicate a deferred/placeholder result.
    # Extend this list as new placeholder idioms are discovered.
    PLACEHOLDER_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"以下を?まとめ", re.IGNORECASE),
        re.compile(r"まとめます", re.IGNORECASE),
        re.compile(r"報告します", re.IGNORECASE),
        re.compile(r"以下に報告", re.IGNORECASE),
        re.compile(r"will\s+summarize", re.IGNORECASE),
        re.compile(r"will\s+now\s+report", re.IGNORECASE),
        re.compile(r"here\s+is\s+what\s+I\s+(?:will|plan\s+to)", re.IGNORECASE),
        re.compile(r"let\s+me\s+compile", re.IGNORECASE),
        re.compile(r"I(?:'ll|\s+will)\s+(?:now\s+)?(?:provide|list|compile|gather)", re.IGNORECASE),
    ]

    # Tool names that count as "observations" for the observation-taken check.
    OBSERVATION_TOOLS: frozenset[str] = frozenset({
        "snapshot", "web_snapshot", "screenshot", "get_page_source",
        "snapshot_show", "snapshot_actionable_tree", "snapshot_search", "web_refs",
        "web_query", "webview_url", "webview_title",
        "describe", "find_by_text", "get_text",
    })

    def __init__(self, *, min_result_chars: int = 50) -> None:
        self._min_result_chars = min_result_chars

    def check(
        self,
        goal: str,
        brain: AgentBrain,
        memory: WorkingMemory,
    ) -> VerificationResult:
        """Run all structural checks. Short-circuits on first failure."""

        result_text = (brain.result or "").strip()

        # Check 1: result non-empty
        if not result_text:
            return VerificationResult(
                passed=False,
                layer="structural",
                reason="result is empty",
                feedback=(
                    "Your result field is empty. Put the actual data the user "
                    "requested into the result field before completing."
                ),
            )

        # Check 2: no placeholder phrases
        for pattern in self.PLACEHOLDER_PATTERNS:
            if pattern.search(result_text):
                return VerificationResult(
                    passed=False,
                    layer="structural",
                    reason=f"result contains placeholder phrase matching: {pattern.pattern}",
                    feedback=(
                        "Your result contains a placeholder or promise instead of "
                        "actual data. Include the real data in the result field, "
                        "not a statement that you will provide it later."
                    ),
                )

        # Check 3: minimum length
        if len(result_text) < self._min_result_chars:
            return VerificationResult(
                passed=False,
                layer="structural",
                reason=f"result too short ({len(result_text)} chars < {self._min_result_chars})",
                feedback=(
                    f"Your result is only {len(result_text)} characters. "
                    f"The goal appears to require more detail. Include all "
                    f"requested data in the result."
                ),
            )

        # Check 4: at least one observation taken
        observation_taken = any(
            tc.tool_name in self.OBSERVATION_TOOLS
            for tc in memory.tool_calls
        )
        if not observation_taken:
            return VerificationResult(
                passed=False,
                layer="structural",
                reason="no observation taken during the run",
                feedback=(
                    "No observation (snapshot/screenshot) was taken during this "
                    "run. Take a snapshot to verify the current state before "
                    "completing."
                ),
            )

        # Check 5: no unrecovered failures with success=True
        if brain.success and memory.tool_calls:
            recent_n = min(5, len(memory.tool_calls))
            recent_calls = memory.tool_calls[-recent_n:]
            all_failed = all(tc.ok is False for tc in recent_calls)
            if all_failed and recent_n >= 2:
                return VerificationResult(
                    passed=False,
                    layer="structural",
                    reason=f"last {recent_n} tool calls all failed but success=True",
                    feedback=(
                        f"The last {recent_n} tool calls all failed. You cannot "
                        f"report success when recent actions are failing. "
                        f"Either fix the failures or set success=false."
                    ),
                )

        return VerificationResult(
            passed=True,
            layer="structural",
            reason="all structural checks passed",
            feedback="",
        )


# ---------------------------------------------------------------------------
# Layer 2 — LLM-as-judge semantic verification
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM_PROMPT = """\
You are a completion gate, not a quality grader. Given a user's goal, the \
agent's final result, and the tool trace, decide only whether the agent appears \
to have completed the user's explicit instructions.

Respond with JSON only:
{"satisfied": bool, "reason": "str", "missing": ["str", ...]}

Rules:
- Use the tool trace to verify actions, navigation, data retrieval, and recovery \
from failures.
- If a failed action was later successfully retried, or an equivalent successful \
action appears later in the trace, treat it as recovered.
- Use the final result to verify that the requested deliverable was produced.
- Do not require the final result to restate actions that are already proven by \
the tool trace.
- Do not add requirements that are not explicitly stated in the user's goal.
- Do not fail for missing helpful metadata, citations, titles, URLs, source labels, \
proof statements, or explicit constraint declarations unless the user explicitly \
requested them.
- Do not grade writing quality, ideal formatting, or completeness beyond the \
explicit goal.
- Judge constraints by substance, not self-attestation. For example, if the result \
visibly contains the requested number of items or is visibly within a requested \
length, do not require it to explicitly say so.
- Fail only when there is a clear unmet explicit requirement, such as a required \
action not shown in the trace or result, a requested number of items not present, \
a missing/empty deliverable, a final result that contradicts the trace, or an \
unrecovered tool failure that prevents completion.
- If the result is a promise or preview (e.g. "I will summarize..."), mark as not satisfied.
"""


def _compact_trace_text(value: object, *, max_chars: int) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        return text[: max_chars - 14].rstrip() + "... [trimmed]"
    return text


def format_tool_trace(
    tool_calls: list["ToolCallRecord"],
    *,
    max_calls: int = 40,
    max_chars: int = 6000,
) -> str:
    """Return a bounded, deterministic tool trace for completion verification."""

    if not tool_calls:
        return "(no tool calls recorded)"

    selected = tool_calls[-max_calls:]
    omitted = len(tool_calls) - len(selected)
    lines: list[str] = []

    start_index = omitted + 1
    for offset, call in enumerate(selected):
        index = start_index + offset
        status = "ok" if call.ok is True else "fail" if call.ok is False else "unknown"
        args = _compact_trace_text(call.arguments_summary, max_chars=500)
        duration = ""
        if call.duration_ms is not None:
            duration = f" {call.duration_ms:.0f}ms"
        error = ""
        if call.error:
            error = f" error={_compact_trace_text(call.error, max_chars=240)}"
        artifact = ""
        if call.artifact_path:
            artifact = f" artifact={_compact_trace_text(call.artifact_path, max_chars=160)}"
        lines.append(
            f"{index}. {call.tool_name} {args} -> {status}{duration}{error}{artifact}"
        )

    def build_trace(omitted_count: int, visible_lines: list[str]) -> str:
        prefix = []
        if omitted_count > 0:
            prefix.append(f"... {omitted_count} earlier tool call(s) omitted ...")
        return "\n".join(prefix + visible_lines)

    trace = build_trace(omitted, lines)
    while len(lines) > 1 and len(trace) > max_chars:
        lines.pop(0)
        omitted += 1
        trace = build_trace(omitted, lines)

    if len(trace) > max_chars:
        prefix = f"... {omitted} earlier tool call(s) omitted ...\n" if omitted > 0 else ""
        available = max_chars - len(prefix)
        if available > 20 and lines:
            lines[-1] = lines[-1][: available - 14].rstrip() + "... [trimmed]"
            return build_trace(omitted, lines)
        return trace[: max_chars - 24].rstrip() + "\n... [trace trimmed]"
    return trace


class LLMJudge:
    """LLM completion gate using the goal, final result, and compact tool trace."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4.1",
        max_tokens: int = 512,
        fail_open: bool = True,
        usage_tracker: UsageTracker | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._fail_open = fail_open
        self._usage_tracker = usage_tracker

    async def verify(
        self,
        goal: str,
        result_text: str,
        tool_trace: str = "",
    ) -> VerificationResult:
        """Call the judge model and return a VerificationResult."""
        import json as _json

        from openai import AsyncOpenAI

        user_msg = (
            f"## Goal\n{goal}\n\n"
            f"## Agent Result\n{result_text}\n\n"
            f"## Tool Trace\n{tool_trace or '(no tool trace provided)'}"
        )

        try:
            client = AsyncOpenAI(api_key=self._api_key)
            response = await client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=self._max_tokens,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            if self._usage_tracker is not None:
                self._usage_tracker.record_chat_completion_response(
                    response,
                    model=self._model,
                    call_type="judge",
                    phase="verification",
                )
            raw = (response.choices[0].message.content or "").strip()
            verdict = _json.loads(raw)
        except Exception as exc:
            logger.warning("[verifier] LLM judge call failed: %s: %s", type(exc).__name__, exc)
            if self._fail_open:
                return VerificationResult(
                    passed=True,
                    layer="llm_judge",
                    reason=f"judge error (fail-open): {type(exc).__name__}: {exc}",
                    feedback="",
                )
            return VerificationResult(
                passed=False,
                layer="llm_judge",
                reason=f"judge error: {type(exc).__name__}: {exc}",
                feedback="Verification could not be completed due to an error.",
                missing=[],
            )

        satisfied = bool(verdict.get("satisfied", False))
        reason = str(verdict.get("reason", ""))
        missing = verdict.get("missing", [])
        if not isinstance(missing, list):
            missing = []
        missing = [str(m) for m in missing]

        if satisfied:
            return VerificationResult(
                passed=True,
                layer="llm_judge",
                reason=reason or "goal satisfied",
                feedback="",
                missing=[],
            )

        feedback_parts = [f"Verification failed: {reason}"]
        if missing:
            feedback_parts.append("Missing: " + ", ".join(missing))
        feedback_parts.append(
            "Fix only clear unmet explicit requirements. If the trace already proves "
            "an action or a failed action was later recovered, do not repeat it solely "
            "to satisfy verification."
        )

        return VerificationResult(
            passed=False,
            layer="llm_judge",
            reason=reason,
            feedback=" ".join(feedback_parts),
            missing=missing,
        )


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------

class CompletionVerifier:
    """Completion gate: structural guard first, then optional LLM judge."""

    def __init__(
        self,
        guard: StructuralGuard,
        judge: LLMJudge | None = None,
    ) -> None:
        self._guard = guard
        self._judge = judge

    async def verify(
        self,
        goal: str,
        brain: AgentBrain,
        memory: WorkingMemory,
    ) -> VerificationResult:
        """Run Layer 1 then Layer 2. Return first failure, or a pass."""
        # Layer 1: structural
        result = self._guard.check(goal, brain, memory)
        if not result.passed:
            logger.info(
                "[verifier] structural guard FAILED: %s", result.reason,
            )
            return result

        # Layer 2: LLM judge (if enabled)
        if self._judge is not None:
            result_text = (brain.result or "").strip()
            tool_trace = format_tool_trace(memory.tool_calls)
            result = await self._judge.verify(goal, result_text, tool_trace)
            if not result.passed:
                logger.info(
                    "[verifier] LLM judge FAILED: %s (missing=%s)",
                    result.reason,
                    result.missing,
                )
            else:
                logger.info("[verifier] LLM judge PASSED")
            return result

        # No judge — structural pass is sufficient
        return result
