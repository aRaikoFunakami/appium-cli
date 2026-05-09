"""Tests for Pydantic schemas."""

from __future__ import annotations

import json

from agent_browser.schemas import (
    BillingInfo,
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


class TestTaskResult:
    def test_defaults(self) -> None:
        r = TaskResult(goal="g", success=False, summary="s")
        assert r.tool_calls == 0
        assert r.retries == 0
        assert r.artifacts == []
        assert r.failures == []

    def test_verification_defaults(self) -> None:
        r = TaskResult(goal="g", success=False, summary="s")
        assert r.verification_passed is None
        assert r.verification_reason is None
        assert r.verification_attempts == 0

    def test_verification_fields_serialize(self) -> None:
        r = TaskResult(
            goal="g",
            success=False,
            summary="s",
            verification_passed=False,
            verification_reason="result too short",
            verification_attempts=2,
        )
        data = json.loads(r.model_dump_json())
        assert data["verification_passed"] is False
        assert data["verification_reason"] == "result too short"
        assert data["verification_attempts"] == 2

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


class TestBillingInfo:
    def test_billing_call_breakdown_defaults_empty(self) -> None:
        b = BillingInfo(model="gpt-5.4")
        assert b.call_breakdown == []

    def test_billing_call_breakdown_serializes(self) -> None:
        b = BillingInfo(
            model="gpt-5.4",
            call_breakdown=[
                BillingInfo.BillingCall(
                    index=1,
                    call_type="action",
                    input_tokens=10,
                    cached_tokens=2,
                    output_tokens=3,
                    total_tokens=13,
                    cost_usd=0.0001,
                )
            ],
        )
        data = json.loads(b.model_dump_json())
        assert data["call_breakdown"][0]["index"] == 1
        assert data["call_breakdown"][0]["call_type"] == "action"


class TestMemoryEvent:
    def test_required_fields(self) -> None:
        e = MemoryEvent(event_type="tool_success", tool_name="tap")
        assert e.event_type == "tool_success"
        assert e.tool_name == "tap"
        assert e.occurred_at is not None
