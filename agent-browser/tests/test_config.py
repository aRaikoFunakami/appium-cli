"""Tests for runtime configuration defaults and environment overrides."""

from __future__ import annotations

from agent_browser.config import AgentBrowserConfig


def test_default_max_turns_is_50() -> None:
    cfg = AgentBrowserConfig()
    assert cfg.max_turns == 50


def test_from_env_uses_50_when_max_turns_unset(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_BROWSER_MAX_TURNS", raising=False)

    cfg = AgentBrowserConfig.from_env()

    assert cfg.max_turns == 50


def test_from_env_honors_max_turns_override(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BROWSER_MAX_TURNS", "75")

    cfg = AgentBrowserConfig.from_env()

    assert cfg.max_turns == 75


def test_default_working_state_char_cap_is_2400() -> None:
    cfg = AgentBrowserConfig()
    assert cfg.working_state_char_cap == 2400


def test_from_env_honors_working_state_char_cap_override(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BROWSER_WORKING_STATE_CHARS", "1800")

    cfg = AgentBrowserConfig.from_env()

    assert cfg.working_state_char_cap == 1800


def test_default_verification_fields() -> None:
    cfg = AgentBrowserConfig()
    assert cfg.max_verification_retries == 2
    assert cfg.max_wall_seconds == 300.0
    assert cfg.max_no_progress_steps == 8
    assert cfg.verify_with_llm is True
    assert cfg.min_result_chars == 50
    assert cfg.judge_model == "gpt-4.1"
    assert cfg.judge_fail_open is True


def test_default_controller_rollout_fields() -> None:
    cfg = AgentBrowserConfig()
    assert cfg.controller == "structured"
    assert cfg.scroll_main_content_bias == 1.0
    assert cfg.scroll_header_penalty == 1.0
    assert cfg.scroll_verify_required is True
    assert cfg.step_block_strict is True
    assert cfg.llm_assist_budget_per_step == 2


def test_default_artifacts_dir_is_appium_cli_fallback() -> None:
    cfg = AgentBrowserConfig()
    assert str(cfg.artifacts_dir) == ".appium-cli/agent-browser/artifacts"


def test_from_env_honors_artifacts_dir_override(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BROWSER_ARTIFACTS_DIR", "custom-artifacts")
    cfg = AgentBrowserConfig.from_env()
    assert str(cfg.artifacts_dir) == "custom-artifacts"


def test_from_env_honors_verify_with_llm_false(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BROWSER_VERIFY_WITH_LLM", "false")
    cfg = AgentBrowserConfig.from_env()
    assert cfg.verify_with_llm is False


def test_from_env_honors_verify_with_llm_true(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BROWSER_VERIFY_WITH_LLM", "1")
    cfg = AgentBrowserConfig.from_env()
    assert cfg.verify_with_llm is True


def test_from_env_honors_max_wall_seconds(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BROWSER_MAX_WALL_SECONDS", "600.0")
    cfg = AgentBrowserConfig.from_env()
    assert cfg.max_wall_seconds == 600.0


def test_from_env_honors_judge_model(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BROWSER_JUDGE_MODEL", "gpt-4o-mini")
    cfg = AgentBrowserConfig.from_env()
    assert cfg.judge_model == "gpt-4o-mini"


def test_from_env_honors_controller(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BROWSER_CONTROLLER", "structured")
    cfg = AgentBrowserConfig.from_env()
    assert cfg.controller == "structured"


def test_from_env_ignores_invalid_controller(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BROWSER_CONTROLLER", "unknown")
    cfg = AgentBrowserConfig.from_env()
    assert cfg.controller == "structured"


def test_from_env_honors_controller_scoring_fields(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BROWSER_SCROLL_MAIN_CONTENT_BIAS", "2.5")
    monkeypatch.setenv("AGENT_BROWSER_SCROLL_HEADER_PENALTY", "3.0")
    monkeypatch.setenv("AGENT_BROWSER_SCROLL_VERIFY_REQUIRED", "false")
    monkeypatch.setenv("AGENT_BROWSER_STEP_BLOCK_STRICT", "false")
    monkeypatch.setenv("AGENT_BROWSER_LLM_ASSIST_BUDGET_PER_STEP", "4")

    cfg = AgentBrowserConfig.from_env()

    assert cfg.scroll_main_content_bias == 2.5
    assert cfg.scroll_header_penalty == 3.0
    assert cfg.scroll_verify_required is False
    assert cfg.step_block_strict is False
    assert cfg.llm_assist_budget_per_step == 4
