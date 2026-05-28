"""Tests for the two-layer completion verifier."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_browser.agent.brain import AgentBrain
from agent_browser.agent.verifier import (
    CompletionVerifier,
    LLMJudge,
    StructuralGuard,
    VerificationResult,
    format_tool_trace,
)
from agent_browser.memory import WorkingMemory
from agent_browser.schemas import ToolCallRecord
from agent_browser.token_counter import UsageTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _brain(
    *,
    is_done: bool = True,
    success: bool = True,
    result: str | None = "Completed.",
    evaluation: str = "ok",
    working_state: str = "done",
    next_goal: str = "none",
) -> AgentBrain:
    return AgentBrain(
        evaluation=evaluation,
        working_state=working_state,
        next_goal=next_goal,
        is_done=is_done,
        success=success,
        result=result,
    )


def _memory(
    *,
    tool_calls: list[ToolCallRecord] | None = None,
    goal: str = "test goal",
) -> WorkingMemory:
    mem = WorkingMemory(goal=goal)
    if tool_calls:
        mem.tool_calls = tool_calls
    return mem


def _tool_call(
    name: str,
    ok: bool = True,
    *,
    args: str = "{}",
    duration_ms: float | None = None,
    error: str | None = None,
    artifact_path: str | None = None,
) -> ToolCallRecord:
    return ToolCallRecord(
        tool_name=name,
        arguments_summary=args,
        duration_ms=duration_ms,
        ok=ok,
        error=error,
        artifact_path=artifact_path,
    )


# ---------------------------------------------------------------------------
# StructuralGuard tests
# ---------------------------------------------------------------------------

class TestStructuralGuard:
    """Tests for Layer 1: deterministic structural checks."""

    def test_empty_result_fails(self) -> None:
        guard = StructuralGuard()
        brain = _brain(result="")
        mem = _memory(tool_calls=[_tool_call("web_snapshot")])
        vr = guard.check("Find 5 items", brain, mem)
        assert not vr.passed
        assert vr.layer == "structural"
        assert "empty" in vr.reason

    def test_none_result_fails(self) -> None:
        guard = StructuralGuard()
        brain = _brain(result=None)
        mem = _memory(tool_calls=[_tool_call("web_snapshot")])
        vr = guard.check("Find items", brain, mem)
        assert not vr.passed
        assert "empty" in vr.reason

    def test_whitespace_only_result_fails(self) -> None:
        guard = StructuralGuard()
        brain = _brain(result="   \n  \t  ")
        mem = _memory(tool_calls=[_tool_call("web_snapshot")])
        vr = guard.check("goal", brain, mem)
        assert not vr.passed
        assert "empty" in vr.reason

    def test_placeholder_japanese_matome_fails(self) -> None:
        guard = StructuralGuard()
        brain = _brain(result="最終報告では以下をまとめます: 1) issues一覧の先頭5件タイトル")
        mem = _memory(tool_calls=[_tool_call("web_snapshot")])
        vr = guard.check("goal", brain, mem)
        assert not vr.passed
        assert "placeholder" in vr.reason

    def test_placeholder_english_will_summarize_fails(self) -> None:
        guard = StructuralGuard()
        brain = _brain(result="I will summarize the findings in the next step.")
        mem = _memory(tool_calls=[_tool_call("web_snapshot")])
        vr = guard.check("goal", brain, mem)
        assert not vr.passed
        assert "placeholder" in vr.reason

    def test_placeholder_ill_provide_fails(self) -> None:
        guard = StructuralGuard()
        brain = _brain(result="I'll now provide the complete list of results.")
        mem = _memory(tool_calls=[_tool_call("web_snapshot")])
        vr = guard.check("goal", brain, mem)
        assert not vr.passed
        assert "placeholder" in vr.reason

    def test_short_result_fails(self) -> None:
        guard = StructuralGuard(min_result_chars=100)
        brain = _brain(result="Done.")
        mem = _memory(tool_calls=[_tool_call("web_snapshot")])
        vr = guard.check("Find 5 items", brain, mem)
        assert not vr.passed
        assert "too short" in vr.reason

    def test_no_observation_fails(self) -> None:
        guard = StructuralGuard(min_result_chars=5)
        brain = _brain(result="Here are the results with enough detail to pass length checks.")
        mem = _memory(tool_calls=[_tool_call("tap"), _tool_call("fill")])
        vr = guard.check("goal", brain, mem)
        assert not vr.passed
        assert "observation" in vr.reason.lower()

    @pytest.mark.parametrize(
        "tool_name",
        [
            "web_query",
            "snapshot_search",
            "snapshot_refs",
            "snapshot_show",
            "webview_url",
            "webview_title",
        ],
    )
    def test_targeted_discovery_counts_as_observation(self, tool_name: str) -> None:
        guard = StructuralGuard(min_result_chars=5)
        brain = _brain(result="Here are the complete results from the observed page.")
        mem = _memory(tool_calls=[_tool_call(tool_name)])
        vr = guard.check("goal", brain, mem)
        assert vr.passed

    def test_all_recent_failures_with_success_fails(self) -> None:
        guard = StructuralGuard(min_result_chars=5)
        brain = _brain(success=True, result="Everything worked fine, task complete.")
        mem = _memory(tool_calls=[
            _tool_call("web_snapshot"),  # observation (outside recent 5)
            _tool_call("tap", ok=True),  # push observation outside window
            _tool_call("fill", ok=True),
            _tool_call("tap", ok=False),
            _tool_call("fill", ok=False),
            _tool_call("click", ok=False),
            _tool_call("tap", ok=False),
            _tool_call("scroll_down", ok=False),
        ])
        vr = guard.check("goal", brain, mem)
        assert not vr.passed
        assert "failed" in vr.reason

    def test_all_recent_failures_with_success_false_passes(self) -> None:
        """When brain.success=False, recent failures don't trigger this check."""
        guard = StructuralGuard(min_result_chars=5)
        brain = _brain(success=False, result="Could not complete the task due to errors encountered.")
        mem = _memory(tool_calls=[
            _tool_call("web_snapshot"),
            _tool_call("tap", ok=False),
            _tool_call("fill", ok=False),
        ])
        vr = guard.check("goal", brain, mem)
        assert vr.passed

    def test_adequate_result_passes(self) -> None:
        guard = StructuralGuard(min_result_chars=10)
        brain = _brain(result="Issue #1: Title A, Issue #2: Title B, Issue #3: Title C")
        mem = _memory(tool_calls=[_tool_call("web_snapshot"), _tool_call("tap")])
        vr = guard.check("Find issues", brain, mem)
        assert vr.passed
        assert vr.layer == "structural"

    def test_incident_regression_placeholder_preview(self) -> None:
        """Regression test for the incident that triggered this feature.

        The agent returned a preview promise instead of actual data.
        """
        guard = StructuralGuard()
        incident_result = (
            "完了。詳細ページを開き、snapshot取得に成功しました。"
            "最終報告では以下をまとめます: "
            "1) issues一覧の先頭5件タイトル "
            "2) label:bug フィルタ後の先頭5件タイトル "
            "3) 詳細ページのタイトル・作成者・ラベル一覧。"
        )
        brain = _brain(success=True, result=incident_result)
        mem = _memory(tool_calls=[_tool_call("web_snapshot")])
        vr = guard.check("GitHub issues task", brain, mem)
        assert not vr.passed
        assert "placeholder" in vr.reason


# ---------------------------------------------------------------------------
# Tool trace formatter tests
# ---------------------------------------------------------------------------

class TestToolTraceFormatter:
    """Tests for compact tool traces passed to the LLM judge."""

    def test_empty_trace_is_explicit(self) -> None:
        assert format_tool_trace([]) == "(no tool calls recorded)"

    def test_formats_success_failure_duration_error_and_artifact(self) -> None:
        trace = format_tool_trace([
            _tool_call(
                "goto",
                args='{"url":"https://www.yahoo.co.jp"}',
                duration_ms=1728.4,
            ),
            _tool_call(
                "web_text",
                ok=False,
                args='{"selector":"article"}',
                duration_ms=35.2,
                error="ERROR: article text not found",
                artifact_path="artifacts/screenshot-1.png",
            ),
        ])

        assert '1. goto {"url":"https://www.yahoo.co.jp"} -> ok 1728ms' in trace
        assert '2. web_text {"selector":"article"} -> fail 35ms' in trace
        assert "error=ERROR: article text not found" in trace
        assert "artifact=artifacts/screenshot-1.png" in trace

    def test_truncates_by_call_count_and_char_limit(self) -> None:
        calls = [
            _tool_call("web_text", args=f'{{"index":{index},"payload":"{"x" * 50}"}}')
            for index in range(5)
        ]

        trace = format_tool_trace(calls, max_calls=2, max_chars=300)

        assert "... 3 earlier tool call(s) omitted ..." in trace
        assert "4. web_text" in trace
        assert "5. web_text" in trace
        assert len(trace) <= 300


# ---------------------------------------------------------------------------
# LLMJudge tests (all mocked)
# ---------------------------------------------------------------------------

class TestLLMJudge:
    """Tests for Layer 2: LLM-as-judge with mocked API calls."""

    def test_satisfied_returns_pass(self) -> None:
        judge = LLMJudge(api_key="test-key", model="gpt-4.1")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"satisfied": true, "reason": "all items present", "missing": []}'

        with patch("openai.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(return_value=mock_response)
            vr = asyncio.get_event_loop().run_until_complete(
                judge.verify(
                    "Find 5 issues",
                    "Issue 1, Issue 2, Issue 3, Issue 4, Issue 5",
                    "1. web_query {} -> ok 10ms",
                )
            )

        assert vr.passed
        assert vr.layer == "llm_judge"
        assert vr.missing == []
        kwargs = instance.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == "gpt-4.1"
        system_prompt = kwargs["messages"][0]["content"]
        assert "completion gate, not a quality grader" in system_prompt
        assert "Use the tool trace to verify actions" in system_prompt
        assert "treat it as recovered" in system_prompt
        assert "Do not add requirements that are not explicitly stated" in system_prompt
        assert "titles, URLs" in system_prompt
        assert "Judge constraints by substance, not self-attestation" in system_prompt
        assert "## Tool Trace\n1. web_query {} -> ok 10ms" in kwargs["messages"][1]["content"]

    def test_not_satisfied_returns_fail(self) -> None:
        judge = LLMJudge(api_key="test-key")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            '{"satisfied": false, "reason": "only 3 of 5 issues", "missing": ["issue 4", "issue 5"]}'
        )

        with patch("openai.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(return_value=mock_response)
            vr = asyncio.get_event_loop().run_until_complete(
                judge.verify("Find 5 issues", "Issue 1, Issue 2, Issue 3", "1. web_query {} -> ok")
            )

        assert not vr.passed
        assert vr.layer == "llm_judge"
        assert "issue 4" in vr.missing
        assert "issue 5" in vr.missing
        assert "Fix only clear unmet explicit requirements" in vr.feedback
        assert "do not repeat it solely to satisfy verification" in vr.feedback

    def test_records_judge_usage_when_tracker_is_provided(self) -> None:
        tracker = UsageTracker(primary_model="gpt-4.1-mini")
        judge = LLMJudge(api_key="test-key", model="gpt-4.1", usage_tracker=tracker)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"satisfied": true, "reason": "ok", "missing": []}'
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 123
        mock_response.usage.completion_tokens = 12
        mock_response.usage.prompt_tokens_details = MagicMock()
        mock_response.usage.prompt_tokens_details.cached_tokens = 3
        mock_response.usage.completion_tokens_details = MagicMock()
        mock_response.usage.completion_tokens_details.reasoning_tokens = 4

        with patch("openai.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(return_value=mock_response)
            vr = asyncio.get_event_loop().run_until_complete(
                judge.verify("goal", "complete result", "1. snapshot {} -> ok")
            )

        assert vr.passed
        assert len(tracker.calls) == 1
        assert tracker.calls[0].call_type == "judge"
        assert tracker.calls[0].model == "gpt-4.1"
        assert tracker.calls[0].input_tokens == 123
        assert tracker.calls[0].cached_tokens == 3
        assert tracker.calls[0].output_tokens == 12
        assert tracker.calls[0].reasoning_tokens == 4

    def test_api_error_fail_open(self) -> None:
        judge = LLMJudge(api_key="test-key", fail_open=True)

        with patch("openai.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))
            vr = asyncio.get_event_loop().run_until_complete(
                judge.verify("goal", "result", "1. snapshot {} -> ok")
            )

        assert vr.passed
        assert "fail-open" in vr.reason

    def test_api_error_fail_closed(self) -> None:
        judge = LLMJudge(api_key="test-key", fail_open=False)

        with patch("openai.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))
            vr = asyncio.get_event_loop().run_until_complete(
                judge.verify("goal", "result", "1. snapshot {} -> ok")
            )

        assert not vr.passed
        assert "error" in vr.reason.lower()


# ---------------------------------------------------------------------------
# CompletionVerifier facade tests
# ---------------------------------------------------------------------------

class TestCompletionVerifier:
    """Tests for the two-layer facade."""

    def test_structural_fail_short_circuits_judge(self) -> None:
        """If structural guard fails, LLM judge should NOT be called."""
        guard = StructuralGuard()
        judge = LLMJudge(api_key="test-key")
        verifier = CompletionVerifier(guard=guard, judge=judge)

        brain = _brain(result="")
        mem = _memory(tool_calls=[_tool_call("web_snapshot")])

        with patch.object(judge, "verify", new_callable=AsyncMock) as mock_judge:
            vr = asyncio.get_event_loop().run_until_complete(
                verifier.verify("goal", brain, mem)
            )
            mock_judge.assert_not_called()

        assert not vr.passed
        assert vr.layer == "structural"

    def test_structural_pass_then_judge_pass(self) -> None:
        guard = StructuralGuard(min_result_chars=5)
        judge = LLMJudge(api_key="test-key")
        verifier = CompletionVerifier(guard=guard, judge=judge)

        brain = _brain(result="Complete results with all requested data here.")
        mem = _memory(tool_calls=[_tool_call("web_snapshot")])

        with patch.object(judge, "verify", new_callable=AsyncMock) as mock_judge:
            mock_judge.return_value = VerificationResult(
                passed=True, layer="llm_judge", reason="satisfied", feedback=""
            )
            vr = asyncio.get_event_loop().run_until_complete(
                verifier.verify("goal", brain, mem)
            )
            mock_judge.assert_called_once()
            args = mock_judge.call_args.args
            assert args[0] == "goal"
            assert args[1] == "Complete results with all requested data here."
            assert "1. web_snapshot {} -> ok" in args[2]

        assert vr.passed
        assert vr.layer == "llm_judge"

    def test_structural_pass_then_judge_fail(self) -> None:
        guard = StructuralGuard(min_result_chars=5)
        judge = LLMJudge(api_key="test-key")
        verifier = CompletionVerifier(guard=guard, judge=judge)

        brain = _brain(result="Here are 3 issues but user asked for 5 issues total.")
        mem = _memory(tool_calls=[_tool_call("web_snapshot")])

        with patch.object(judge, "verify", new_callable=AsyncMock) as mock_judge:
            mock_judge.return_value = VerificationResult(
                passed=False,
                layer="llm_judge",
                reason="only 3 of 5",
                feedback="Missing 2 issues",
                missing=["issue 4", "issue 5"],
            )
            vr = asyncio.get_event_loop().run_until_complete(
                verifier.verify("Find 5 issues", brain, mem)
            )

        assert not vr.passed
        assert vr.layer == "llm_judge"

    def test_no_judge_structural_pass_is_sufficient(self) -> None:
        guard = StructuralGuard(min_result_chars=5)
        verifier = CompletionVerifier(guard=guard, judge=None)

        brain = _brain(result="Complete list of all items requested by user in the goal.")
        mem = _memory(tool_calls=[_tool_call("snapshot")])

        vr = asyncio.get_event_loop().run_until_complete(
            verifier.verify("goal", brain, mem)
        )
        assert vr.passed
        assert vr.layer == "structural"

    def test_incident_regression_full(self) -> None:
        """Full regression test: the incident result fails structural guard
        while a proper result passes both layers.
        """
        guard = StructuralGuard()
        verifier = CompletionVerifier(guard=guard, judge=None)

        # Bad: incident result (placeholder promise)
        bad_brain = _brain(
            success=True,
            result=(
                "完了。詳細ページを開き、snapshot取得に成功しました。"
                "最終報告では以下をまとめます: "
                "1) issues一覧 2) bug issues 3) 詳細ページ。"
            ),
        )
        bad_mem = _memory(tool_calls=[_tool_call("web_snapshot")])
        vr_bad = asyncio.get_event_loop().run_until_complete(
            verifier.verify("Find issues", bad_brain, bad_mem)
        )
        assert not vr_bad.passed

        # Good: complete result
        good_brain = _brain(
            success=True,
            result=(
                "## Initial Issues (top 5)\n"
                "1. Fix scrollbar rendering\n"
                "2. Terminal crash on paste\n"
                "3. Extension host memory leak\n"
                "4. Debugger breakpoint not hit\n"
                "5. Git diff view broken\n\n"
                "## Bug Issues (top 5)\n"
                "1. Fix scrollbar rendering [bug]\n"
                "2. Terminal crash on paste [bug]\n"
                "3. Extension host memory leak [bug]\n"
                "4. Debugger breakpoint not hit [bug]\n"
                "5. Git diff view broken [bug]\n\n"
                "## Detail\n"
                "Title: Fix scrollbar rendering\n"
                "Author: user1\n"
                "Labels: bug, editor"
            ),
        )
        good_mem = _memory(tool_calls=[_tool_call("web_snapshot")])
        vr_good = asyncio.get_event_loop().run_until_complete(
            verifier.verify("Find issues", good_brain, good_mem)
        )
        assert vr_good.passed

    def test_tool_trace_can_prove_navigation_actions(self) -> None:
        guard = StructuralGuard(min_result_chars=10)
        judge = LLMJudge(api_key="test-key")
        verifier = CompletionVerifier(guard=guard, judge=judge)

        brain = _brain(
            success=True,
            result=(
                "・記事1の要約。\n"
                "・記事2の要約。\n"
                "・記事3の要約。"
            ),
        )
        mem = _memory(tool_calls=[
            _tool_call("goto", args='{"url":"https://www.yahoo.co.jp"}'),
            _tool_call("web_query", args='{"selector":"a[href*=sports]"}'),
            _tool_call("goto", args='{"url":"https://news.yahoo.co.jp/categories/sports"}'),
            _tool_call("web_eval", args='{"script":"return first three article urls"}'),
            _tool_call("goto", args='{"url":"https://news.yahoo.co.jp/articles/1"}'),
            _tool_call("web_text", args='{"selector":"","offset":0,"limit":6000}'),
            _tool_call("goto", args='{"url":"https://news.yahoo.co.jp/articles/2"}'),
            _tool_call("web_text", args='{"selector":"","offset":0,"limit":6000}'),
            _tool_call("goto", args='{"url":"https://news.yahoo.co.jp/articles/3"}'),
            _tool_call("web_text", args='{"selector":"","offset":0,"limit":6000}'),
        ])

        with patch.object(judge, "verify", new_callable=AsyncMock) as mock_judge:
            mock_judge.return_value = VerificationResult(
                passed=True,
                layer="llm_judge",
                reason="summaries present and navigation proven by tool trace",
                feedback="",
            )
            vr = asyncio.get_event_loop().run_until_complete(
                verifier.verify("Open Yahoo Sports and summarize first three articles", brain, mem)
            )

        assert vr.passed
        trace = mock_judge.call_args.args[2]
        assert "https://www.yahoo.co.jp" in trace
        assert "https://news.yahoo.co.jp/categories/sports" in trace
        assert trace.count("web_text") == 3
