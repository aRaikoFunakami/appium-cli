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
    assert "Do not cap depth for normal full-page observations" in prompt
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


def test_system_prompt_requires_information_retrieval_provenance() -> None:
    prompt = build_system_prompt()
    assert "include brief provenance" in prompt
    assert "detail pages or records inspected" in prompt
    assert "explicit constraint checks" in prompt


def test_system_prompt_warns_against_browsing_after_evidence_verifier_failure() -> None:
    prompt = build_system_prompt()
    assert "missing evidence, provenance, or output formatting" in prompt
    assert "instead of browsing again" in prompt


def test_system_prompt_includes_n_item_working_state_checklist() -> None:
    prompt = build_system_prompt()
    assert "For tasks that require N items" in prompt
    assert "selected URLs/refs" in prompt
    assert "completed item count" in prompt


def test_system_prompt_requires_webview_snapshot_first() -> None:
    prompt = build_system_prompt()
    assert "After goto or webview_switch, take web_snapshot" in prompt
    assert "primary page observation" in prompt
    assert "authoritative WebView ref source" in prompt
    assert "before web_query" in prompt


def test_system_prompt_warns_against_broad_query_absence_judgment() -> None:
    prompt = build_system_prompt()
    assert 'web_query(selector="a")' in prompt
    assert "Do not conclude that a target is absent from one broad query alone" in prompt
    assert "a[href*='sports']" in prompt


def test_system_prompt_includes_general_n_detail_page_recipe() -> None:
    import appium_cli.openai_tools as openai_tools

    openai_tools._update_tool_skill_prompt_mode("webview_switch", {}, {"ok": True})
    try:
        prompt = build_system_prompt()
    finally:
        openai_tools._reset_tool_skill_prompt_mode_for_tests()

    assert "General recipe: collect N detail pages from a start page" in prompt
    assert "Find the list/category/search page from the latest snapshot first" in prompt
    assert "Select exactly the first N unique detail refs or URLs" in prompt
    assert "Visit each selected detail exactly once" in prompt
    assert "Once N detail pages have been collected, stop browsing" in prompt


def test_system_prompt_prefers_snapshot_refs_before_web_query() -> None:
    import appium_cli.openai_tools as openai_tools

    openai_tools._update_tool_skill_prompt_mode("webview_switch", {}, {"ok": True})
    try:
        prompt = build_system_prompt()
    finally:
        openai_tools._reset_tool_skill_prompt_mode_for_tests()

    assert "web_snapshot() as the authoritative page observation and ref source" in prompt
    assert "Find targets from the latest snapshot first" in prompt
    assert "Use web_query() only as an auxiliary tool" in prompt


def test_system_prompt_includes_token_safe_artifact_usage() -> None:
    prompt = build_system_prompt()
    assert "Token-safe artifact usage" in prompt
    assert "Search first, then inspect small fragments" in prompt
    assert 'snapshot_refs({"snapshot_id": "latest", "role": "link"})' in prompt
    assert "Avoid broad link dumps" in prompt


def test_system_prompt_prefers_goto_for_web_query_hrefs() -> None:
    prompt = build_system_prompt()
    assert "web_query() returns an href" in prompt
    assert 'prefer goto({"url": "<href>"})' in prompt
    assert "Do not click refs copied from web_query output" in prompt


def test_system_prompt_prefers_news_category_urls_for_news_tasks() -> None:
    import appium_cli.openai_tools as openai_tools

    openai_tools._update_tool_skill_prompt_mode("webview_switch", {}, {"ok": True})
    try:
        prompt = build_system_prompt()
    finally:
        openai_tools._reset_tool_skill_prompt_mode_for_tests()

    assert "a[href*='categories/sports']" in prompt
    assert "prefer news/category URLs" in prompt
    assert "separate sports portal URL" in prompt


def test_system_prompt_prefers_chrome_activation_for_native_url_tasks() -> None:
    prompt = build_system_prompt()
    assert "For browser URL tasks, prefer activate_app" in prompt
    assert 'If goto fails with "No WebView context"' in prompt
    assert "then retry goto once" in prompt


def test_system_prompt_is_built_dynamically(monkeypatch) -> None:
    import agent_browser.agent.prompt as prompt_module

    calls = {"count": 0}

    def fake_tool_prompt() -> str:
        calls["count"] += 1
        return f"dynamic prompt {calls['count']}"

    monkeypatch.setattr(prompt_module, "get_tool_skill_prompt", fake_tool_prompt)

    assert "dynamic prompt 1" in prompt_module.build_system_prompt()
    assert "dynamic prompt 2" in prompt_module.build_system_prompt()
