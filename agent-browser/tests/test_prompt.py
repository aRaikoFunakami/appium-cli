"""Tests for minimal browser-operation prompt construction."""

from __future__ import annotations

from agent_browser.agent.prompt import SYSTEM_PROMPT, build_input_items
from agent_browser.agent.state import BrowserOperationState
from agent_browser.config import AgentBrowserConfig


def _prompt_text(items: list[dict[str, object]]) -> str:
    content = items[0]["content"]
    assert isinstance(content, list)
    first = content[0]
    assert isinstance(first, dict)
    return str(first["text"])


def test_prompt_includes_only_operation_state() -> None:
    cfg = AgentBrowserConfig(max_observation_chars=80, working_state_char_cap=50)
    state = BrowserOperationState(
        goal="Fill form",
        phase="filling",
        working_state="First Name=Taro; pending=Last Name",
        latest_observation="url: https://example.test\nref=firstName\n" + "DOM" * 100,
        last_step="fill(ref=firstName) -> ok",
    )

    text = _prompt_text(build_input_items(state, cfg, recent_steps="[1] fill() -> ok"))

    assert "<task>" in text
    assert "<working_state>" in text
    assert "<current_screen>" in text
    assert "<recent_steps>" in text
    assert "function_call" not in text
    assert "reasoning" not in text
    assert len(text) < 1200


def test_system_prompt_mentions_single_input_submit_rule() -> None:
    assert "single-input forms" in SYSTEM_PROMPT
    assert "use submit=true" in SYSTEM_PROMPT


def test_system_prompt_mentions_snapshot_depth_guidance() -> None:
    assert "depth=8" in SYSTEM_PROMPT


def test_system_prompt_mentions_result_must_contain_actual_data() -> None:
    assert "MUST contain the actual data" in SYSTEM_PROMPT


def test_system_prompt_warns_against_preview_results() -> None:
    assert "not a preview or promise" in SYSTEM_PROMPT


def test_system_prompt_mentions_runtime_verifier() -> None:
    assert "runtime verifier" in SYSTEM_PROMPT
