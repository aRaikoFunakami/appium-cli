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
)
from agent_browser.memory import WorkingMemory
from agent_browser.schemas import ToolCallRecord


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


def _tool_call(name: str, ok: bool = True) -> ToolCallRecord:
    return ToolCallRecord(
        tool_name=name,
        arguments_summary="{}",
        ok=ok,
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
# LLMJudge tests (all mocked)
# ---------------------------------------------------------------------------

class TestLLMJudge:
    """Tests for Layer 2: LLM-as-judge with mocked API calls."""

    def test_satisfied_returns_pass(self) -> None:
        judge = LLMJudge(api_key="test-key", model="gpt-4.1-mini")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"satisfied": true, "reason": "all items present", "missing": []}'

        with patch("openai.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(return_value=mock_response)
            vr = asyncio.get_event_loop().run_until_complete(
                judge.verify("Find 5 issues", "Issue 1, Issue 2, Issue 3, Issue 4, Issue 5")
            )

        assert vr.passed
        assert vr.layer == "llm_judge"
        assert vr.missing == []

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
                judge.verify("Find 5 issues", "Issue 1, Issue 2, Issue 3")
            )

        assert not vr.passed
        assert vr.layer == "llm_judge"
        assert "issue 4" in vr.missing
        assert "issue 5" in vr.missing

    def test_api_error_fail_open(self) -> None:
        judge = LLMJudge(api_key="test-key", fail_open=True)

        with patch("openai.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))
            vr = asyncio.get_event_loop().run_until_complete(
                judge.verify("goal", "result")
            )

        assert vr.passed
        assert "fail-open" in vr.reason

    def test_api_error_fail_closed(self) -> None:
        judge = LLMJudge(api_key="test-key", fail_open=False)

        with patch("openai.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))
            vr = asyncio.get_event_loop().run_until_complete(
                judge.verify("goal", "result")
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
