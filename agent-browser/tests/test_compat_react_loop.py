"""Compatibility tests for controller rollout dispatch."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent_browser.config import AgentBrowserConfig
from agent_browser.main import cli_main, run_browser_task
from agent_browser.schemas import TaskResult


class FakeSessionManager:
    def __init__(self, cfg: AgentBrowserConfig) -> None:
        self.cfg = cfg

    async def __aenter__(self):
        return SimpleNamespace(
            udid="fake",
            server_url="http://127.0.0.1:4723",
            started_by_us=False,
        )

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _restore_default_event_loop() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


@pytest.mark.asyncio
async def test_react_controller_dispatch_uses_legacy_loop(tmp_path) -> None:
    cfg = AgentBrowserConfig(
        controller="react",
        openai_api_key="test",
        memory_path=tmp_path / "memory.jsonl",
        artifacts_dir=tmp_path / "artifacts",
    )
    expected = TaskResult(goal="goal", success=True, summary="react")

    with patch("agent_browser.main.AppiumSessionManager", FakeSessionManager), patch(
        "agent_browser.main.run_react_loop",
        new=AsyncMock(return_value=expected),
    ) as react_loop, patch(
        "agent_browser.main.run_structured_controller",
        new=AsyncMock(),
    ) as structured:
        result = await run_browser_task("goal", cfg)

    assert result is expected
    react_loop.assert_awaited_once()
    structured.assert_not_awaited()


@pytest.mark.asyncio
async def test_structured_controller_dispatch_uses_structured_loop(tmp_path) -> None:
    cfg = AgentBrowserConfig(
        controller="structured",
        openai_api_key="test",
        memory_path=tmp_path / "memory.jsonl",
        artifacts_dir=tmp_path / "artifacts",
    )
    expected = TaskResult(goal="goal", success=True, summary="structured")

    with patch("agent_browser.main.AppiumSessionManager", FakeSessionManager), patch(
        "agent_browser.main.run_react_loop",
        new=AsyncMock(),
    ) as react_loop, patch(
        "agent_browser.main.run_structured_controller",
        new=AsyncMock(return_value=expected),
    ) as structured:
        result = await run_browser_task("goal", cfg)

    assert result is expected
    structured.assert_awaited_once()
    react_loop.assert_not_awaited()


def test_cli_allows_default_structured_without_openai_key(monkeypatch, capsys) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    expected = TaskResult(goal="goal", success=True, summary="structured")

    with patch("agent_browser.main.run_browser_task", new=AsyncMock(return_value=expected)) as runner:
        exit_code = cli_main(["goal"])
    _restore_default_event_loop()

    assert exit_code == 0
    runner.assert_awaited_once()
    assert "[OK] structured" in capsys.readouterr().out


def test_cli_requires_openai_key_for_react_controller(monkeypatch, capsys) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    exit_code = cli_main(["goal", "--controller=react"])
    _restore_default_event_loop()

    assert exit_code == 2
    assert "OPENAI_API_KEY is required for --controller=react" in capsys.readouterr().err
