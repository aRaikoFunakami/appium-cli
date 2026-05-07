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


class TestArtifactFirst:
    """Tests for artifact-first snapshot handling and action metadata compaction."""

    @pytest.mark.asyncio
    async def test_failed_string_flipped_to_ok_false(self, tmp_path) -> None:
        """When daemon returns ok=True but text starts with FAILED, adapter flips to failure."""
        ctx = _ctx(tmp_path)
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "text": "FAILED: ref 'web_btn' cannot be resolved. No strategies available.", "data": {}}
            result = await _invoke_appium_tool("tap", json.dumps({"ref": "web_btn"}), ctx)
        assert "FAILED" in result or "cannot be resolved" in result
        assert ctx.context.memory.tool_calls[-1].ok is False
        assert ctx.context.memory.retry_counts.get("tap") == 1
        assert any("web_btn" in f for f in ctx.context.memory.failures)

    @pytest.mark.asyncio
    async def test_action_compact_metadata(self, tmp_path) -> None:
        """Action tools keep snapshot_id/screen_id but drop artifacts paths and tree body."""
        ctx = _ctx(tmp_path)
        metadata_block = (
            "snapshot_id: web-2026-05-07T07-05-18-853Z-728218\n"
            "source: web\n"
            "screen_id: 728218\n"
            "context: WEBVIEW_chrome\n"
            "title: Yahoo! JAPAN\n"
            "url: https://www.yahoo.co.jp/\n"
            "artifacts:\n"
            "  compact: /path/to/snapshot.compact.yml\n"
            "  full: /path/to/snapshot.full.yml\n"
            "  refs: /path/to/snapshot.refs.json\n"
            "  index: /path/to/snapshot.index.json\n"
            "  meta: /path/to/snapshot.meta.json\n"
        )
        full_text = f"OK\n{metadata_block}"
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "text": full_text, "data": {}}
            result = await _invoke_appium_tool("fill", json.dumps({"ref": "web__14", "text": "hello"}), ctx)
        assert result.startswith("OK")
        assert "snapshot_id: web-2026-05-07T07-05-18-853Z-728218" in result
        assert "screen_id: 728218" in result
        assert "source: web" in result
        assert "context: WEBVIEW_chrome" in result
        # artifact paths and title/url are removed
        assert "/path/to/" not in result
        assert "artifacts:" not in result
        assert "title:" not in result
        assert "url:" not in result

    @pytest.mark.asyncio
    async def test_action_can_scroll_more(self, tmp_path) -> None:
        """Scroll result preserves can_scroll_more alongside compact metadata."""
        ctx = _ctx(tmp_path)
        metadata_block = (
            "snapshot_id: native-abc\n"
            "source: native\n"
            "screen_id: abc\n"
            "context: NATIVE_APP\n"
            "artifacts:\n"
            "  compact: /path/snapshot.compact.yml\n"
        )
        full_text = f"OK\ncan_scroll_more: True\n{metadata_block}"
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "text": full_text, "data": {}}
            result = await _invoke_appium_tool("scroll_down", json.dumps({}), ctx)
        assert "can_scroll_more: True" in result
        assert "snapshot_id: native-abc" in result
        assert "screen_id: abc" in result
        assert "/path/" not in result

    @pytest.mark.asyncio
    async def test_snapshot_metadata_passthrough(self, tmp_path) -> None:
        """Observation tools (snapshot) pass metadata through to LLM unchanged."""
        ctx = _ctx(tmp_path)
        metadata_text = (
            "snapshot_id: web-test\n"
            "source: web\n"
            "screen_id: test123\n"
            "context: WEBVIEW_chrome\n"
            "title: Test Page\n"
            "url: https://example.com\n"
            "artifacts:\n"
            "  compact: /tmp/test.compact.yml\n"
        )
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "text": metadata_text, "data": {}}
            result = await _invoke_appium_tool("web_snapshot", json.dumps({}), ctx)
        # Observation tools are NOT compacted — full metadata passes through
        assert "snapshot_id: web-test" in result
        assert "artifacts:" in result
        assert "/tmp/test.compact.yml" in result

    @pytest.mark.asyncio
    async def test_artifacts_recorded_in_memory(self, tmp_path) -> None:
        """Snapshot data[artifacts] are recorded into WorkingMemory.artifacts."""
        ctx = _ctx(tmp_path)
        artifacts_dict = {
            "compact": "/snapshots/test.compact.yml",
            "full": "/snapshots/test.full.yml",
            "refs": "/snapshots/test.refs.json",
            "index": "/snapshots/test.index.json",
            "meta": "/snapshots/test.meta.json",
        }
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {
                "ok": True,
                "text": "snapshot_id: test\nsource: native\nscreen_id: x\n",
                "data": {"snapshot_id": "test", "artifacts": artifacts_dict},
            }
            await _invoke_appium_tool("snapshot", json.dumps({}), ctx)
        assert len(ctx.context.memory.artifacts) == 5
        assert "/snapshots/test.compact.yml" in ctx.context.memory.artifacts

    @pytest.mark.asyncio
    async def test_targeted_extraction_unchanged(self, tmp_path) -> None:
        """Targeted extraction tools (snapshot_search) return result as-is."""
        ctx = _ctx(tmp_path)
        search_result = (
            "Snapshot search results for 'Storage' (total=2):\n"
            "1. [ref:row_storage] row \"Storage\" actionable=true\n"
            "2. [ref:label_storage] text \"Storage usage\" actionable=false\n"
        )
        with patch("agent_browser.appium_tools.call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "text": search_result, "data": {}}
            result = await _invoke_appium_tool("snapshot_search", json.dumps({"text": "Storage"}), ctx)
        assert result == search_result

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
