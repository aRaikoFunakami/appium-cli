"""Tests for guardrails module."""

from __future__ import annotations

import pytest

from agent_browser.guardrails import (
    BLOCKED_TOOLS,
    classify_tool_call,
    is_approved,
    requires_approval,
)
from agent_browser.memory import WorkingMemory
from agent_browser.schemas import ApprovalRecord, SafetyCategory


class TestSafe:
    @pytest.mark.parametrize(
        "name,args",
        [
            ("snapshot", {}),
            ("tap", {"ref": "home_btn"}),
            ("fill", {"ref": "search_box", "text": "weather", "submit": True}),
            ("scroll_down", {}),
            ("press_keycode", {"keycode": 4}),
            ("get_device_info", None),
        ],
    )
    def test_safe_actions(self, name, args) -> None:
        decision = classify_tool_call(name, args)
        assert decision.category == SafetyCategory.SAFE


class TestSensitive:
    @pytest.mark.parametrize(
        "name,args,label",
        [
            ("tap", {"ref": "login_btn"}, "login"),
            ("tap", {"ref": "signin_link"}, "login"),
            ("tap", {"ref": "checkout_button"}, "payment"),
            ("tap", {"ref": "place_order_btn"}, "purchase"),
            ("fill", {"ref": "password_field", "text": "secret"}, "password"),
            ("fill", {"ref": "credit_card_input", "text": "4242"}, "payment"),
        ],
    )
    def test_sensitive_actions(self, name, args, label) -> None:
        decision = classify_tool_call(name, args)
        assert decision.category == SafetyCategory.SENSITIVE
        assert decision.matched_pattern == label
        assert decision.approval_key is not None
        assert requires_approval(decision)


class TestBlocked:
    def test_terminate_app_blocked(self) -> None:
        decision = classify_tool_call("terminate_app", {"app_id": "x"})
        assert decision.category == SafetyCategory.BLOCKED
        assert decision.tool_name in BLOCKED_TOOLS

    def test_restart_app_blocked(self) -> None:
        assert classify_tool_call("restart_app", {"app_id": "x"}).category == SafetyCategory.BLOCKED

    def test_set_orientation_blocked(self) -> None:
        assert classify_tool_call("set_orientation", {"orientation": "PORTRAIT"}).category == SafetyCategory.BLOCKED


class TestApprovalGating:
    def test_unapproved_sensitive_is_blocked(self) -> None:
        memory = WorkingMemory(goal="g")
        decision = classify_tool_call("tap", {"ref": "login_btn"})
        assert requires_approval(decision)
        assert not is_approved(memory, decision)

    def test_approved_sensitive_passes(self) -> None:
        memory = WorkingMemory(goal="g")
        decision = classify_tool_call("tap", {"ref": "login_btn"})
        memory.record_approval(ApprovalRecord(approval_key=decision.approval_key, granted=True))
        assert is_approved(memory, decision)

    def test_denied_approval_does_not_pass(self) -> None:
        memory = WorkingMemory(goal="g")
        decision = classify_tool_call("tap", {"ref": "login_btn"})
        memory.record_approval(ApprovalRecord(approval_key=decision.approval_key, granted=False))
        assert not is_approved(memory, decision)
