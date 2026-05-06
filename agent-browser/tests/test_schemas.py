"""Tests for Pydantic schemas."""

from __future__ import annotations

import json

from agent_browser.schemas import (
    BrowserResultPayload,
    MemoryEvent,
    SafetyCategory,
    SafetyDecision,
    TaskResult,
)


class TestSafetyDecision:
    def test_safe_decision(self) -> None:
        d = SafetyDecision(tool_name="tap", category=SafetyCategory.SAFE)
        assert d.tool_name == "tap"
        assert d.category == SafetyCategory.SAFE
        assert d.approval_key is None

    def test_serialize_roundtrip(self) -> None:
        d = SafetyDecision(
            tool_name="fill",
            category=SafetyCategory.SENSITIVE,
            reason="login content",
            matched_pattern="login",
            approval_key="fill:login",
        )
        payload = d.model_dump_json()
        restored = SafetyDecision.model_validate_json(payload)
        assert restored == d


class TestBrowserResultPayload:
    def test_minimal(self) -> None:
        p = BrowserResultPayload(success=True, summary="done")
        assert p.success is True
        assert p.summary == "done"
        assert p.title is None

    def test_full_roundtrip(self) -> None:
        p = BrowserResultPayload(
            success=True,
            summary="Found page",
            title="OpenAI Agents",
            url="https://example.com",
            notes="ok",
        )
        restored = BrowserResultPayload.model_validate_json(p.model_dump_json())
        assert restored == p


class TestTaskResult:
    def test_defaults(self) -> None:
        r = TaskResult(goal="g", success=False, summary="s")
        assert r.tool_calls == 0
        assert r.retries == 0
        assert r.artifacts == []
        assert r.failures == []

    def test_json_serializable(self) -> None:
        r = TaskResult(
            goal="g",
            success=True,
            summary="s",
            artifacts=["a.png"],
            failures=["x"],
            tool_calls=3,
            retries=1,
        )
        data = json.loads(r.model_dump_json())
        assert data["tool_calls"] == 3
        assert data["artifacts"] == ["a.png"]


class TestMemoryEvent:
    def test_required_fields(self) -> None:
        e = MemoryEvent(event_type="tool_success", tool_name="tap")
        assert e.event_type == "tool_success"
        assert e.tool_name == "tap"
        assert e.occurred_at is not None
