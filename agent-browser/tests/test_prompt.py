"""Tests for minimal browser-operation prompt construction."""

from __future__ import annotations

from agent_browser.agent.prompt import build_input_items, build_system_prompt
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
    prompt = build_system_prompt()
    assert "single-input forms" in prompt
    assert "use submit=true" in prompt


def test_system_prompt_mentions_snapshot_depth_guidance() -> None:
    prompt = build_system_prompt()
    assert "Do not use depth for normal full-page observations" in prompt
    assert "Use depth only for scoped/debug snapshots" in prompt
    assert "depth=8" not in prompt


def test_system_prompt_composes_appium_tool_skill_prompt() -> None:
    prompt = build_system_prompt()
    assert "appium-cli tool skill" in prompt
    assert "goto" in prompt
    assert "activate_app" in prompt
    assert "webview_status" in prompt
    assert "assert_visible" in prompt


def test_system_prompt_mentions_result_must_contain_actual_data() -> None:
    assert "MUST contain the actual data" in build_system_prompt()


def test_system_prompt_warns_against_preview_results() -> None:
    assert "not a preview or promise" in build_system_prompt()


def test_system_prompt_mentions_runtime_verifier() -> None:
    assert "runtime verifier" in build_system_prompt()


def test_system_prompt_requires_webview_snapshot_first() -> None:
    prompt = build_system_prompt()
    assert "After goto or webview_switch, take web_snapshot" in prompt
    assert "primary page observation" in prompt
    assert "use web_text" in prompt


def test_system_prompt_warns_against_broad_query_absence_judgment() -> None:
    prompt = build_system_prompt()
    assert 'web_query(selector="a")' in prompt
    assert "Do not conclude that a target is absent from one broad query alone" in prompt
    assert "a[href*='sports']" in prompt


def test_system_prompt_mentions_snapshot_refs_pagination() -> None:
    prompt = build_system_prompt()
    assert "snapshot_refs is paginated" in prompt
    assert "offset=next_offset" in prompt


def test_system_prompt_is_built_dynamically(monkeypatch) -> None:
    import agent_browser.agent.prompt as prompt_module

    calls = {"count": 0}

    def fake_tool_prompt() -> str:
        calls["count"] += 1
        return f"dynamic prompt {calls['count']}"

    monkeypatch.setattr(prompt_module, "get_tool_skill_prompt", fake_tool_prompt)

    assert "dynamic prompt 1" in prompt_module.build_system_prompt()
    assert "dynamic prompt 2" in prompt_module.build_system_prompt()
