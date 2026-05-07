"""Tests for token-bounded operation history."""

from __future__ import annotations

from agent_browser.agent.history import HistoryItem, LoopDetector, OperationHistory


def test_history_keeps_recent_step_lines_only() -> None:
    history = OperationHistory(recent_steps=2)
    for i in range(1, 8):
        history.add(
            HistoryItem(
                step=i,
                action_name="fill",
                args_summary=f"ref=f{i}",
                success=True,
                result_summary="OK",
            )
        )

    lines = history.recent_lines()
    assert "[6]" in lines
    assert "[7]" in lines
    assert "[1]" not in lines
    assert history.compacted_history


def test_history_prompt_line_has_no_raw_api_items() -> None:
    item = HistoryItem(step=1, action_name="tap", args_summary="ref=submit", success=False, result_summary="ERROR")
    line = item.to_prompt_line()
    assert "function_call" not in line
    assert "reasoning" not in line
    assert line == "[1] tap(ref=submit) -> fail ERROR"


def test_loop_detector_detects_information_only_loop() -> None:
    detector = LoopDetector()
    for _ in range(3):
        detector.record("web_snapshot", "{}", "same")
    warning = detector.detect()
    assert warning is not None
    assert "information-only" in warning
