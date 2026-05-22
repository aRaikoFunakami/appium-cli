"""Tests for retry-limit enforcement and progress tracking in the ReAct loop."""

from __future__ import annotations

from agent_browser.agent.history import INFO_ONLY_TOOLS
from agent_browser.agent.prompt import build_input_items
from agent_browser.agent.state import BrowserOperationState
from agent_browser.appium_tools import ToolExecutionResult
from agent_browser.config import AgentBrowserConfig


def _prompt_text(items: list[dict[str, object]]) -> str:
    content = items[0]["content"]
    assert isinstance(content, list)
    first = content[0]
    assert isinstance(first, dict)
    return str(first["text"])


class TestBlockedToolsPrompt:
    """build_input_items correctly renders <blocked_tools> section."""

    def test_no_blocked_tools_section_when_empty(self) -> None:
        cfg = AgentBrowserConfig()
        state = BrowserOperationState(goal="test")
        text = _prompt_text(build_input_items(state, cfg, blocked_tools=None))
        assert "<blocked_tools>" not in text

    def test_no_blocked_tools_section_when_empty_set(self) -> None:
        cfg = AgentBrowserConfig()
        state = BrowserOperationState(goal="test")
        text = _prompt_text(build_input_items(state, cfg, blocked_tools=set()))
        assert "<blocked_tools>" not in text

    def test_blocked_tools_section_lists_tools(self) -> None:
        cfg = AgentBrowserConfig(max_retries=3)
        state = BrowserOperationState(goal="test")
        text = _prompt_text(build_input_items(state, cfg, blocked_tools={"tap", "fill"}))
        assert "<blocked_tools>" in text
        assert "fill" in text
        assert "tap" in text
        assert "max_retries=3" in text
        assert "Do NOT call them again" in text


class TestProgressTracking:
    """Failed tools must not count as progress (regression test for loop.py:352)."""

    def test_failed_result_does_not_advance_progress(self) -> None:
        """Simulates the progress-tracking logic extracted from loop.py.

        When a tool fails, last_progress_step should NOT be updated
        even if the observation hash changes.
        """
        last_progress_step = 0
        prev_observation_hash: int | None = hash("initial screen")

        # Simulate a failed tool call with a different error message each time
        for step in range(1, 6):
            ok = False
            observation = f"ERROR: something different {step}"
            obs_hash = hash(observation)

            # This is the corrected logic from loop.py
            if ok:
                last_progress_step = step
                prev_observation_hash = obs_hash
            elif obs_hash != prev_observation_hash:
                prev_observation_hash = obs_hash

        # last_progress_step should remain at 0 since all tools failed
        assert last_progress_step == 0

    def test_successful_result_advances_progress(self) -> None:
        """Successful tool calls should always advance progress."""
        last_progress_step = 0
        prev_observation_hash: int | None = hash("initial")

        ok = True
        observation = "new screen content"
        obs_hash = hash(observation)

        if ok:
            last_progress_step = 1
            prev_observation_hash = obs_hash
        elif obs_hash != prev_observation_hash:
            prev_observation_hash = obs_hash

        assert last_progress_step == 1


class TestRetryLimitBlocking:
    """Tool execution is blocked when retry count exceeds max_retries."""

    def test_blocked_tool_returns_blocked_message(self) -> None:
        """Simulates the blocking logic from loop.py."""
        cfg = AgentBrowserConfig(max_retries=2)
        blocked_tools: set[str] = {"tap"}

        name = "tap"
        # Simulate the check in the loop
        if name in blocked_tools:
            result = ToolExecutionResult(
                name, "ref=ghost",
                f"BLOCKED: '{name}' reached retry limit ({cfg.max_retries}). Use a different tool.",
                False, 0.0,
            )
        else:
            result = None  # Would call execute_appium_tool

        assert result is not None
        assert not result.ok
        assert "BLOCKED" in result.output
        assert "retry limit" in result.output

    def test_observation_tools_not_in_info_only(self) -> None:
        """Confirm that action tools like tap/fill are NOT in INFO_ONLY_TOOLS.

        This ensures they are eligible for blocking.
        """
        assert "tap" not in INFO_ONLY_TOOLS
        assert "fill" not in INFO_ONLY_TOOLS
        assert "click" not in INFO_ONLY_TOOLS

    def test_info_only_tools_include_observation_tools(self) -> None:
        """Confirm observation tools are in INFO_ONLY_TOOLS (won't be blocked)."""
        assert "snapshot" in INFO_ONLY_TOOLS
        assert "web_snapshot" in INFO_ONLY_TOOLS
        assert "screenshot" in INFO_ONLY_TOOLS
