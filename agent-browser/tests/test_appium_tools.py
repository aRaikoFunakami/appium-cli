"""Tests for the appium-cli FunctionTool adapter and custom tools.

The daemon ``call_tool`` is mocked so these tests do not require a running
Appium server.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.run_context import RunContextWrapper
from agents.tool_context import ToolContext

from agent_browser.appium_tools import (
    BrowserAgentContext,
    MAX_TOOL_RESULT_CHARS,
    _invoke_appium_tool,
    all_tools,
    make_appium_tools,
)
from agent_browser.config import AgentBrowserConfig
from agent_browser.memory import WorkingMemory


def _ctx(tmp_path) -> ToolContext[BrowserAgentContext]:
    cfg = AgentBrowserConfig(artifacts_dir=tmp_path / "artifacts", memory_path=tmp_path / "mem.jsonl")
    memory = WorkingMemory(goal="test")
    bctx = BrowserAgentContext(config=cfg, memory=memory)
    # ToolContext is a thin extension of RunContextWrapper - we only need .context.
    wrapper = RunContextWrapper(context=bctx)
    return wrapper  # type: ignore[return-value]


class TestMakeAppiumTools:
    def test_returns_70_tools(self) -> None:
        tools = make_appium_tools()
        assert len(tools) >= 60
        names = {t.name for t in tools}
        # spot-check known tools
        assert {"snapshot", "tap", "fill", "goto", "webview_switch"} <= names

    def test_all_tools_includes_custom(self) -> None:
        names = {t.name for t in all_tools()}
        assert "browser_result" in names
        assert "human_approval" in names

    def test_all_appium_tools_have_loose_schemas(self) -> None:
        for tool in make_appium_tools():
            assert tool.strict_json_schema is False, f"{tool.name} should not be strict"


class TestInvokeAppiumTool:
    @pytest.mark.asyncio
    async def test_safe_call_dispatches(self, tmp_path) -> None:
        ctx = _ctx(tmp_path)
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "text": "OK", "data": {}}
            result = await _invoke_appium_tool("tap", json.dumps({"ref": "home_btn"}), ctx)
        assert result == "OK"
        mock_call.assert_called_once()
        # working memory updated
        assert len(ctx.context.memory.tool_calls) == 1
        assert ctx.context.memory.tool_calls[0].ok is True

    @pytest.mark.asyncio
    async def test_blocked_tool_does_not_call_daemon(self, tmp_path) -> None:
        ctx = _ctx(tmp_path)
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            result = await _invoke_appium_tool(
                "terminate_app", json.dumps({"app_id": "x"}), ctx
            )
        assert result.startswith("REFUSED")
        mock_call.assert_not_called()
        assert ctx.context.memory.tool_calls[0].ok is False

    @pytest.mark.asyncio
    async def test_sensitive_without_approval_blocks(self, tmp_path) -> None:
        ctx = _ctx(tmp_path)
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            result = await _invoke_appium_tool(
                "tap", json.dumps({"ref": "login_btn"}), ctx
            )
        assert result.startswith("APPROVAL_REQUIRED")
        mock_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_sensitive_with_approval_dispatches(self, tmp_path) -> None:
        from agent_browser.schemas import ApprovalRecord

        ctx = _ctx(tmp_path)
        ctx.context.memory.record_approval(
            ApprovalRecord(approval_key="tap:login", granted=True)
        )
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "text": "tapped", "data": {}}
            result = await _invoke_appium_tool(
                "tap", json.dumps({"ref": "login_btn"}), ctx
            )
        assert result == "tapped"
        mock_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_screenshot_saves_artifact(self, tmp_path) -> None:
        import base64

        ctx = _ctx(tmp_path)
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 16
        screenshot_payload = {
            "type": "screenshot",
            "image_base64": base64.b64encode(png_bytes).decode("ascii"),
            "region": "full",
        }
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {
                "ok": True,
                "text": json.dumps(screenshot_payload),
                "data": {},
            }
            result = await _invoke_appium_tool("screenshot", "{}", ctx)

        # The base64 must NOT appear in the result returned to the LLM.
        assert "image_base64" not in result
        # An artifact path must be recorded in working memory.
        assert len(ctx.context.memory.artifacts) == 1
        artifact = ctx.context.memory.artifacts[0]
        assert artifact.endswith(".png")
        # The file actually exists on disk.
        from pathlib import Path

        assert Path(artifact).exists()

    @pytest.mark.asyncio
    async def test_tool_failure_records_retry(self, tmp_path) -> None:
        ctx = _ctx(tmp_path)
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": False, "error": "no such ref"}
            result = await _invoke_appium_tool("tap", json.dumps({"ref": "ghost"}), ctx)
        assert result.startswith("ERROR")
        assert ctx.context.memory.retry_counts.get("tap") == 1
        assert ctx.context.memory.failures


class TestFixesV2:
    """Tests for FAILED-prefix detection and action-tool snapshot stripping."""

    @pytest.mark.asyncio
    async def test_failed_string_flipped_to_ok_false(self, tmp_path) -> None:
        """When daemon returns ok=True but text starts with FAILED, adapter flips to failure."""
        ctx = _ctx(tmp_path)
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "text": "FAILED: ref 'web_btn' cannot be resolved. No strategies available.", "data": {}}
            result = await _invoke_appium_tool("tap", json.dumps({"ref": "web_btn"}), ctx)
        # The result returned to the LLM should contain the error
        assert "FAILED" in result or "cannot be resolved" in result
        # Memory should record it as a failure
        assert ctx.context.memory.tool_calls[-1].ok is False
        assert ctx.context.memory.retry_counts.get("tap") == 1
        assert any("web_btn" in f for f in ctx.context.memory.failures)

    @pytest.mark.asyncio
    async def test_action_tool_snapshot_stripped(self, tmp_path) -> None:
        """Action tools (fill) should have embedded snapshot stripped from result."""
        ctx = _ctx(tmp_path)
        snapshot_body = "screen: CHROMIUM_123 https://yahoo.co.jp\nscreen_id: abc123\ncontext: CHROMIUM_123\n" + "x " * 4000
        full_text = f"OK\n{snapshot_body}"
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "text": full_text, "data": {}}
            result = await _invoke_appium_tool("fill", json.dumps({"ref": "web__14", "text": "hello"}), ctx)
        # Result should be very short - just "OK" without the snapshot
        assert len(result) < 500
        assert "screen_id:" not in result
        assert result.startswith("OK")

    @pytest.mark.asyncio
    async def test_scroll_metadata_preserved(self, tmp_path) -> None:
        """Scroll result should preserve can_scroll_more trailing metadata."""
        ctx = _ctx(tmp_path)
        snapshot_body = "screen: CHROMIUM_123 https://example.com\nscreen_id: def456\n" + "node " * 2000
        full_text = f"OK\n{snapshot_body}\ncan_scroll_more: True"
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "text": full_text, "data": {}}
            result = await _invoke_appium_tool("scroll_down", json.dumps({}), ctx)
        assert "can_scroll_more: True" in result
        assert "screen_id:" not in result
        assert len(result) < 500

    @pytest.mark.asyncio
    async def test_observation_tool_not_trimmed(self, tmp_path) -> None:
        """Observation tools should keep useful output but respect the token budget."""
        ctx = _ctx(tmp_path)
        big_snapshot = (
            "screen: CHROMIUM_123 https://yahoo.co.jp\n"
            "screen_id: xyz789\n"
            + "textbox ref:web__14\n" * 2000
        )
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "text": big_snapshot, "data": {}}
            result = await _invoke_appium_tool("web_snapshot", json.dumps({}), ctx)
        assert "screen_id: xyz789" in result
        assert len(result) <= MAX_TOOL_RESULT_CHARS
        assert "... [truncated " in result

    @pytest.mark.asyncio
    async def test_web_eval_result_respects_token_budget(self, tmp_path) -> None:
        ctx = _ctx(tmp_path)
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "text": "x" * 30000, "data": {}}
            result = await _invoke_appium_tool("web_eval", json.dumps({"script": "return []"}), ctx)
        assert len(result) <= MAX_TOOL_RESULT_CHARS
        assert "... [truncated " in result


class TestObservationProducing:
    def test_targeted_extraction_tools_are_observation_producing(self) -> None:
        from agent_browser.appium_tools import _OBSERVATION_PRODUCING

        for tool in ("snapshot_search", "snapshot_refs", "web_query"):
            assert tool in _OBSERVATION_PRODUCING, f"{tool} should be observation-producing"
