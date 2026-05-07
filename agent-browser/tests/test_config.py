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
