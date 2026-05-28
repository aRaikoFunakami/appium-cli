"""Tests for token usage tracking and billing aggregation."""

from __future__ import annotations

import builtins
from types import SimpleNamespace

from agent_browser.token_counter import (
    UsageTracker,
    build_billing_info,
    estimate_text_tokens,
    estimate_tool_attribution,
)


def _details(**kwargs):
    return SimpleNamespace(**kwargs)


def test_usage_tracker_records_responses_usage_with_reasoning_tokens() -> None:
    tracker = UsageTracker(primary_model="gpt-4.1-mini")
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=1000,
            input_tokens_details=_details(cached_tokens=250),
            output_tokens=120,
            output_tokens_details=_details(reasoning_tokens=40),
        )
    )

    call = tracker.record_responses_response(
        response,
        model="gpt-4.1-mini",
        call_type="brain",
        step_index=2,
        phase="brain",
    )

    assert call is not None
    assert call.input_tokens == 1000
    assert call.cached_tokens == 250
    assert call.uncached_input_tokens == 750
    assert call.output_tokens == 120
    assert call.reasoning_tokens == 40
    assert call.step_index == 2


def test_usage_tracker_records_chat_completion_usage_shape() -> None:
    tracker = UsageTracker(primary_model="gpt-4.1-mini")
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=300,
            prompt_tokens_details=_details(cached_tokens=25),
            completion_tokens=40,
            completion_tokens_details=_details(reasoning_tokens=7),
        )
    )

    call = tracker.record_chat_completion_response(
        response,
        model="gpt-4.1",
        call_type="judge",
        phase="verification",
    )

    assert call is not None
    assert call.model == "gpt-4.1"
    assert call.call_type == "judge"
    assert call.input_tokens == 300
    assert call.cached_tokens == 25
    assert call.output_tokens == 40
    assert call.reasoning_tokens == 7


def test_tool_attribution_is_clamped_to_uncached_input() -> None:
    tracker = UsageTracker(primary_model="gpt-4.1-mini")
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=100,
            input_tokens_details=_details(cached_tokens=80),
            output_tokens=10,
            output_tokens_details=_details(reasoning_tokens=0),
        )
    )
    first = estimate_tool_attribution(
        tool_name="web_text",
        args_summary="{}",
        output_text="x" * 200,
        payload_text="x" * 200,
    )
    second = estimate_tool_attribution(
        tool_name="web_query",
        args_summary="{}",
        output_text="y" * 200,
        payload_text="y" * 200,
    )

    call = tracker.record_responses_response(
        response,
        model="gpt-4.1-mini",
        call_type="brain",
        tool_attributions=[first, second],
    )

    assert call is not None
    assert sum(item.attributed_input_tokens for item in call.tool_attributions) <= 20
    assert all(item.clamped for item in call.tool_attributions)


def test_build_billing_info_preserves_primary_model_and_per_call_models() -> None:
    tracker = UsageTracker(primary_model="gpt-4.1-mini")
    tracker.record_responses_response(
        SimpleNamespace(
            usage=SimpleNamespace(input_tokens=100, output_tokens=10, input_tokens_details=None)
        ),
        model="gpt-4.1-mini",
        call_type="action",
    )
    tracker.record_chat_completion_response(
        SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=50, completion_tokens=5, prompt_tokens_details=None)
        ),
        model="gpt-4.1",
        call_type="judge",
    )

    billing = tracker.to_billing_info()

    assert billing.model == "gpt-4.1-mini"
    assert billing.models == ["gpt-4.1", "gpt-4.1-mini"]
    assert [call.model for call in billing.call_breakdown] == ["gpt-4.1-mini", "gpt-4.1"]
    assert billing.api_calls == 2


def test_unknown_model_marks_billing_uncomputable() -> None:
    from agent_browser.token_counter import CallUsage

    billing = build_billing_info(
        [CallUsage(input_tokens=1, cached_tokens=0, output_tokens=1, model="unknown-model")],
        "gpt-4.1-mini",
    )

    assert billing.billing_status == "uncomputable"
    assert billing.total_cost_usd is None
    assert billing.call_breakdown[0].billing_status == "uncomputable"


def test_estimate_text_tokens_falls_back_when_tiktoken_unavailable(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    tokens, source = estimate_text_tokens("abcdefgh")

    assert tokens == 2
    assert source == "heuristic"
