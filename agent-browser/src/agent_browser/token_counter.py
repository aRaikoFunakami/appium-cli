"""Token usage and cost reporting for OpenAI models used by agent-browser.

Adapted from smartestiroid's ``utils/token_counter.py``. Only the pricing
table and model normalization are kept; LangChain / SLog / persistent-history features are
intentionally omitted.

Pricing is in USD per 1K tokens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional


class OpenAIPricingCalculator:
    """Pricing lookup for OpenAI models (USD per 1K tokens)."""

    # Mirror of smartestiroid PRICING table (snapshot 2026-03-31).
    PRICING: dict[str, dict[str, float]] = {
        # GPT-5.5 series (latest, per https://developers.openai.com/api/docs/pricing)
        # Note: gpt-5.5-mini / gpt-5.5-nano are not published on the public
        # pricing page as of 2026-05; do not add speculative entries.
        "gpt-5.5": {"input": 0.005, "cached": 0.0005, "output": 0.030},
        "gpt-5.5-pro": {"input": 0.030, "cached": 0.030, "output": 0.180},
        # GPT-5.4 series
        "gpt-5.4": {"input": 0.0025, "cached": 0.00025, "output": 0.015},
        "gpt-5.4-mini": {"input": 0.00075, "cached": 0.000075, "output": 0.0045},
        "gpt-5.4-nano": {"input": 0.0002, "cached": 0.00002, "output": 0.00125},
        "gpt-5.4-pro": {"input": 0.030, "cached": 0.030, "output": 0.180},
        # GPT-5.3 / 5.2 / 5.1 / 5 series (kept for legacy/historical lookups)
        "gpt-5.3": {"input": 0.00175, "cached": 0.000175, "output": 0.014},
        "gpt-5.3-chat-latest": {"input": 0.00175, "cached": 0.000175, "output": 0.014},
        "gpt-5.3-codex": {"input": 0.00175, "cached": 0.000175, "output": 0.014},
        "gpt-5.2": {"input": 0.00175, "cached": 0.000175, "output": 0.014},
        "gpt-5.2-chat-latest": {"input": 0.00175, "cached": 0.000175, "output": 0.014},
        "gpt-5.2-pro": {"input": 0.021, "cached": 0.021, "output": 0.168},
        "gpt-5.1": {"input": 0.00125, "cached": 0.000125, "output": 0.010},
        "gpt-5": {"input": 0.00125, "cached": 0.000125, "output": 0.010},
        "gpt-5-mini": {"input": 0.00025, "cached": 0.000025, "output": 0.002},
        "gpt-5-nano": {"input": 0.00005, "cached": 0.000005, "output": 0.0004},
        "gpt-5.1-chat-latest": {"input": 0.00125, "cached": 0.000125, "output": 0.010},
        "gpt-5-chat-latest": {"input": 0.00125, "cached": 0.000125, "output": 0.010},
        "gpt-5.1-codex-max": {"input": 0.00125, "cached": 0.000125, "output": 0.010},
        "gpt-5.1-codex": {"input": 0.00125, "cached": 0.000125, "output": 0.010},
        "gpt-5-codex": {"input": 0.00125, "cached": 0.000125, "output": 0.010},
        "gpt-5-pro": {"input": 0.015, "cached": 0.015, "output": 0.120},
        # GPT-4.1 series
        "gpt-4.1": {"input": 0.002, "cached": 0.0005, "output": 0.008},
        "gpt-4.1-mini": {"input": 0.0004, "cached": 0.0001, "output": 0.0016},
        "gpt-4.1-nano": {"input": 0.0001, "cached": 0.000025, "output": 0.0004},
        # O-series
        "o1": {"input": 0.015, "cached": 0.0075, "output": 0.060},
        "o1-pro": {"input": 0.150, "cached": 0.150, "output": 0.600},
        "o3": {"input": 0.002, "cached": 0.0005, "output": 0.008},
        "o3-pro": {"input": 0.020, "cached": 0.020, "output": 0.080},
        "o3-deep-research": {"input": 0.010, "cached": 0.0025, "output": 0.040},
        "o4-mini": {"input": 0.0011, "cached": 0.000275, "output": 0.0044},
        "o4-mini-deep-research": {"input": 0.002, "cached": 0.0005, "output": 0.008},
        "o3-mini": {"input": 0.0011, "cached": 0.00055, "output": 0.0044},
        "o1-mini": {"input": 0.0011, "cached": 0.00055, "output": 0.0044},
        # GPT-4o
        "gpt-4o": {"input": 0.0025, "cached": 0.00125, "output": 0.010},
        "gpt-4o-mini": {"input": 0.000150, "cached": 0.000075, "output": 0.000600},
        "gpt-4o-2024-05-13": {"input": 0.005, "cached": 0.005, "output": 0.015},
        # Realtime (gpt-realtime-1.5 is the current name; gpt-realtime kept as alias)
        "gpt-realtime-1.5": {"input": 0.004, "cached": 0.0004, "output": 0.016},
        "gpt-realtime": {"input": 0.004, "cached": 0.0004, "output": 0.016},
        "gpt-realtime-mini": {"input": 0.0006, "cached": 0.00006, "output": 0.0024},
        # Legacy
        "gpt-4": {"input": 0.03, "cached": 0.03, "output": 0.06},
        "gpt-4-32k": {"input": 0.06, "cached": 0.06, "output": 0.12},
        "gpt-4-turbo": {"input": 0.01, "cached": 0.01, "output": 0.03},
        "gpt-3.5-turbo": {"input": 0.0005, "cached": 0.0005, "output": 0.0015},
        "gpt-3.5-turbo-16k": {"input": 0.003, "cached": 0.003, "output": 0.004},
    }

    UNKNOWN_MODEL_ERROR_PREFIX = "課金計算不可: 価格テーブル未定義モデル"

    @classmethod
    def _normalize_model_name(cls, model_name: str) -> Optional[str]:
        model_lower = (model_name or "").lower().strip()
        if not model_lower:
            return None
        if model_lower in cls.PRICING:
            return model_lower

        # Order matters: most specific first.
        if "gpt-5.5-pro" in model_lower:
            return "gpt-5.5-pro"
        if "gpt-5.5" in model_lower:
            return "gpt-5.5"
        if "gpt-5-pro" in model_lower:
            return "gpt-5-pro"
        if "gpt-5-nano" in model_lower:
            return "gpt-5-nano"
        if "gpt-5-mini" in model_lower:
            return "gpt-5-mini"
        if "gpt-5-chat-latest" in model_lower:
            return "gpt-5-chat-latest"
        if "gpt-5-codex" in model_lower:
            return "gpt-5-codex"
        if "gpt-5.4-pro" in model_lower:
            return "gpt-5.4-pro"
        if "gpt-5.4-nano" in model_lower:
            return "gpt-5.4-nano"
        if "gpt-5.4-mini" in model_lower:
            return "gpt-5.4-mini"
        if "gpt-5.4" in model_lower:
            return "gpt-5.4"
        if "gpt-5.3-codex" in model_lower:
            return "gpt-5.3-codex"
        if "gpt-5.3" in model_lower:
            return "gpt-5.3"
        if "gpt-5.2" in model_lower:
            return "gpt-5.2"
        if "gpt-5.1" in model_lower:
            return "gpt-5.1"
        if "gpt-5" in model_lower:
            return "gpt-5"

        if "gpt-4.1-nano" in model_lower:
            return "gpt-4.1-nano"
        if "gpt-4.1-mini" in model_lower:
            return "gpt-4.1-mini"
        if "gpt-4.1" in model_lower:
            return "gpt-4.1"

        if "o4-mini-deep-research" in model_lower:
            return "o4-mini-deep-research"
        if "o4-mini" in model_lower:
            return "o4-mini"
        if "o3-deep-research" in model_lower:
            return "o3-deep-research"
        if "o3-pro" in model_lower:
            return "o3-pro"
        if "o3-mini" in model_lower:
            return "o3-mini"
        if "o3" in model_lower:
            return "o3"
        if "o1-pro" in model_lower:
            return "o1-pro"
        if "o1-mini" in model_lower:
            return "o1-mini"
        if "o1" in model_lower:
            return "o1"

        if "gpt-4o-mini" in model_lower:
            return "gpt-4o-mini"
        if "gpt-4o-2024-05-13" in model_lower:
            return "gpt-4o-2024-05-13"
        if "gpt-4o" in model_lower:
            return "gpt-4o"

        if "gpt-realtime-1.5" in model_lower:
            return "gpt-realtime-1.5"
        if "gpt-realtime-mini" in model_lower:
            return "gpt-realtime-mini"
        if "gpt-realtime" in model_lower:
            return "gpt-realtime"

        if "gpt-4-turbo" in model_lower:
            return "gpt-4-turbo"
        if "gpt-4-32k" in model_lower:
            return "gpt-4-32k"
        if "gpt-4" in model_lower:
            return "gpt-4"

        if "gpt-3.5-turbo-16k" in model_lower:
            return "gpt-3.5-turbo-16k"
        if "gpt-3.5-turbo" in model_lower:
            return "gpt-3.5-turbo"

        return None

    @classmethod
    def resolve_pricing_model(cls, model_name: str) -> str:
        normalized = cls._normalize_model_name(model_name)
        if not normalized or normalized not in cls.PRICING:
            raise ValueError(f"{cls.UNKNOWN_MODEL_ERROR_PREFIX}: {model_name}")
        return normalized

    @classmethod
    def cost_for(
        cls,
        model_name: str,
        input_tokens: int,
        cached_tokens: int,
        output_tokens: int,
    ) -> dict[str, float]:
        """Compute cost in USD for one invocation. Raises ValueError if unknown."""
        pricing = cls.PRICING[cls.resolve_pricing_model(model_name)]
        non_cached = max(input_tokens - cached_tokens, 0)
        non_cached_cost = (non_cached / 1000) * pricing["input"]
        cached_cost = (cached_tokens / 1000) * pricing["cached"]
        output_cost = (output_tokens / 1000) * pricing["output"]
        total = non_cached_cost + cached_cost + output_cost
        return {
            "input_cost": round(non_cached_cost + cached_cost, 6),
            "cached_cost": round(cached_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(total, 6),
        }


@dataclass
class ToolTokenAttribution:
    """Estimated tool payload contribution to one LLM input."""

    tool_name: str
    args_summary: str = "{}"
    output_chars: int = 0
    estimated_input_tokens: int = 0
    attributed_input_tokens: int = 0
    tokenizer: str = "heuristic"
    clamped: bool = False
    share_of_uncached_input: float | None = None


@dataclass
class CallUsage:
    """Per-request usage extracted from an OpenAI usage object."""

    input_tokens: int
    cached_tokens: int
    output_tokens: int
    call_type: str = "unknown"
    model: str | None = None
    reasoning_tokens: int = 0
    step_index: int | None = None
    phase: str | None = None
    tool_attributions: list[ToolTokenAttribution] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def uncached_input_tokens(self) -> int:
        return max(self.input_tokens - self.cached_tokens, 0)


def estimate_text_tokens(text: str) -> tuple[int, str]:
    """Estimate token count for a text payload.

    OpenAI usage is authoritative only at the request level. This helper is used
    for local attribution of prompt components such as tool outputs.
    """

    if not text:
        return 0, "heuristic"
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("o200k_base")
        return len(encoding.encode(text)), "tiktoken:o200k_base"
    except (ImportError, KeyError, ValueError):
        return max(1, (len(text) + 3) // 4), "heuristic"


def estimate_tool_attribution(
    *,
    tool_name: str,
    args_summary: str,
    output_text: str,
    payload_text: str | None = None,
) -> ToolTokenAttribution:
    """Estimate the input tokens contributed by a tool payload."""

    text = payload_text if payload_text is not None else output_text
    tokens, tokenizer = estimate_text_tokens(text)
    return ToolTokenAttribution(
        tool_name=tool_name,
        args_summary=args_summary,
        output_chars=len(output_text),
        estimated_input_tokens=tokens,
        attributed_input_tokens=tokens,
        tokenizer=tokenizer,
    )


def _clamp_tool_attributions(
    attributions: list[ToolTokenAttribution],
    uncached_input_tokens: int,
) -> list[ToolTokenAttribution]:
    """Clamp estimated tool contribution to the uncached input token budget."""

    if not attributions:
        return []

    total_estimated = sum(max(item.estimated_input_tokens, 0) for item in attributions)
    if total_estimated <= 0:
        return attributions

    if total_estimated <= uncached_input_tokens:
        for item in attributions:
            item.attributed_input_tokens = item.estimated_input_tokens
            item.clamped = False
            item.share_of_uncached_input = (
                round(item.attributed_input_tokens / uncached_input_tokens, 4)
                if uncached_input_tokens > 0
                else None
            )
        return attributions

    remaining = max(uncached_input_tokens, 0)
    for index, item in enumerate(attributions):
        if index == len(attributions) - 1:
            attributed = remaining
        else:
            attributed = int(item.estimated_input_tokens * uncached_input_tokens / total_estimated)
            attributed = min(attributed, remaining)
        item.attributed_input_tokens = attributed
        item.clamped = True
        item.share_of_uncached_input = (
            round(attributed / uncached_input_tokens, 4)
            if uncached_input_tokens > 0
            else None
        )
        remaining -= attributed
    return attributions


def _usage_attr(usage: Any, name: str) -> int:
    return int(getattr(usage, name, 0) or 0)


def _details_attr(usage: Any, details_name: str, attr_name: str) -> int:
    details = getattr(usage, details_name, None)
    return int(getattr(details, attr_name, 0) or 0) if details else 0


class UsageTracker:
    """Per-task LLM usage recorder."""

    def __init__(self, primary_model: str) -> None:
        self.primary_model = primary_model
        self.calls: list[CallUsage] = []

    def record_responses_response(
        self,
        response: Any,
        *,
        model: str,
        call_type: str,
        step_index: int | None = None,
        phase: str | None = None,
        tool_attributions: list[ToolTokenAttribution] | None = None,
    ) -> CallUsage | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        call = CallUsage(
            input_tokens=_usage_attr(usage, "input_tokens"),
            cached_tokens=_details_attr(usage, "input_tokens_details", "cached_tokens"),
            output_tokens=_usage_attr(usage, "output_tokens"),
            call_type=call_type,
            model=model,
            reasoning_tokens=_details_attr(usage, "output_tokens_details", "reasoning_tokens"),
            step_index=step_index,
            phase=phase,
            tool_attributions=_clamp_tool_attributions(
                list(tool_attributions or []),
                max(_usage_attr(usage, "input_tokens") - _details_attr(usage, "input_tokens_details", "cached_tokens"), 0),
            ),
        )
        self.calls.append(call)
        return call

    def record_chat_completion_response(
        self,
        response: Any,
        *,
        model: str,
        call_type: str = "judge",
        step_index: int | None = None,
        phase: str | None = None,
    ) -> CallUsage | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        call = CallUsage(
            input_tokens=_usage_attr(usage, "prompt_tokens"),
            cached_tokens=_details_attr(usage, "prompt_tokens_details", "cached_tokens"),
            output_tokens=_usage_attr(usage, "completion_tokens"),
            call_type=call_type,
            model=model,
            reasoning_tokens=_details_attr(usage, "completion_tokens_details", "reasoning_tokens"),
            step_index=step_index,
            phase=phase,
        )
        self.calls.append(call)
        return call

    def to_billing_info(self):
        return build_billing_info(self.calls, self.primary_model)


def build_billing_info(call_usages: list[CallUsage], model: str):
    """Aggregate per-call usages into a BillingInfo summary."""

    from agent_browser.schemas import BillingInfo

    total_in = sum(c.input_tokens for c in call_usages)
    total_cached = sum(c.cached_tokens for c in call_usages)
    total_out = sum(c.output_tokens for c in call_usages)
    total_reasoning = sum(c.reasoning_tokens for c in call_usages)
    total_cost = 0.0
    billing_status = "ok"
    uncomputable_reason = None
    call_breakdown: list[BillingInfo.BillingCall] = []
    models = sorted({c.model or model for c in call_usages})

    for idx, call in enumerate(call_usages, start=1):
        per_call_model = call.model or model
        per_call_status = "ok"
        per_call_reason = None
        per_call_cost: float | None = None
        try:
            cost = OpenAIPricingCalculator.cost_for(
                per_call_model, call.input_tokens, call.cached_tokens, call.output_tokens
            )
            total_cost += cost["total_cost"]
            per_call_cost = cost["total_cost"]
        except ValueError as exc:
            billing_status = "uncomputable"
            if uncomputable_reason is None:
                uncomputable_reason = str(exc)
            per_call_status = "uncomputable"
            per_call_reason = str(exc)

        tool_estimates = [
            BillingInfo.ToolTokenEstimate(
                tool_name=item.tool_name,
                args_summary=item.args_summary,
                output_chars=item.output_chars,
                estimated_input_tokens=item.estimated_input_tokens,
                attributed_input_tokens=item.attributed_input_tokens,
                tokenizer=item.tokenizer,
                clamped=item.clamped,
                share_of_uncached_input=item.share_of_uncached_input,
            )
            for item in call.tool_attributions
        ]
        call_breakdown.append(
            BillingInfo.BillingCall(
                index=idx,
                call_type=call.call_type
                if call.call_type in {"action", "brain", "judge", "llm_assist"}
                else "unknown",
                model=per_call_model,
                step_index=call.step_index,
                phase=call.phase,
                input_tokens=call.input_tokens,
                cached_tokens=call.cached_tokens,
                uncached_input_tokens=call.uncached_input_tokens,
                output_tokens=call.output_tokens,
                reasoning_tokens=call.reasoning_tokens,
                total_tokens=call.total_tokens,
                cost_usd=round(per_call_cost, 6) if per_call_cost is not None else None,
                billing_status=per_call_status,
                uncomputable_reason=per_call_reason,
                tool_token_estimates=tool_estimates,
            )
        )

    return BillingInfo(
        model=model,
        models=models or ([model] if model else []),
        api_calls=len(call_usages),
        input_tokens=total_in,
        cached_tokens=total_cached,
        uncached_input_tokens=max(total_in - total_cached, 0),
        output_tokens=total_out,
        reasoning_tokens=total_reasoning,
        total_tokens=total_in + total_out,
        total_cost_usd=round(total_cost, 6) if billing_status == "ok" else None,
        billing_status=billing_status,
        uncomputable_reason=uncomputable_reason,
        call_breakdown=call_breakdown,
    )


def _extract_call_usages(usage: Any) -> list[CallUsage]:
    """Return per-request usages from an agents-SDK Usage object.

    Falls back to a single aggregated entry if request_usage_entries is empty.
    """
    if usage is None:
        return []

    entries = getattr(usage, "request_usage_entries", None) or []
    calls: list[CallUsage] = []
    for entry in entries:
        details = getattr(entry, "input_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) if details else 0
        calls.append(
            CallUsage(
                input_tokens=int(getattr(entry, "input_tokens", 0) or 0),
                cached_tokens=int(cached or 0),
                output_tokens=int(getattr(entry, "output_tokens", 0) or 0),
            )
        )

    if calls:
        return calls

    # Fallback: aggregated only.
    details = getattr(usage, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) if details else 0
    in_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    out_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    if in_tokens or out_tokens:
        return [
            CallUsage(
                input_tokens=in_tokens,
                cached_tokens=int(cached or 0),
                output_tokens=out_tokens,
            )
        ]
    return []


def log_usage_report(
    usage: Any,
    model: str,
    logger: logging.Logger,
    *,
    label: str = "token",
) -> dict[str, Any]:
    """Log a per-call and total token/cost report for an agents-SDK Usage.

    Args:
        usage: An ``agents.usage.Usage`` instance (e.g. ``run_result.context_wrapper.usage``).
        model: Model name used for the run (for pricing lookup).
        logger: Logger to write the report to (INFO level).
        label: Prefix tag used in log lines.

    Returns:
        Dict with aggregated metrics: ``model``, ``calls``, ``input_tokens``,
        ``cached_tokens``, ``output_tokens``, ``total_tokens``,
        ``total_cost_usd`` (None if pricing unknown), ``billing_status``.
    """
    calls = _extract_call_usages(usage)
    if not calls:
        logger.info("[%s] no LLM usage recorded", label)
        return {
            "model": model,
            "calls": 0,
            "input_tokens": 0,
            "cached_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "billing_status": "ok",
        }

    billing_status = "ok"
    uncomputable_reason: Optional[str] = None
    total_cost = 0.0
    total_in = 0
    total_cached = 0
    total_out = 0

    for idx, call in enumerate(calls, start=1):
        total_in += call.input_tokens
        total_cached += call.cached_tokens
        total_out += call.output_tokens
        try:
            cost = OpenAIPricingCalculator.cost_for(
                model, call.input_tokens, call.cached_tokens, call.output_tokens
            )
            total_cost += cost["total_cost"]
            cost_str = f"${cost['total_cost']:.6f}"
        except ValueError as exc:
            billing_status = "uncomputable"
            uncomputable_reason = str(exc)
            cost_str = "課金計算不可"
        cache_part = (
            f" cached={call.cached_tokens}" if call.cached_tokens else ""
        )
        logger.info(
            "[%s] call #%d model=%s in=%d%s out=%d total=%d cost=%s",
            label,
            idx,
            model,
            call.input_tokens,
            cache_part,
            call.output_tokens,
            call.total_tokens,
            cost_str,
        )

    if billing_status == "ok":
        cost_summary = f"${total_cost:.6f}"
        cost_value: Optional[float] = round(total_cost, 6)
    else:
        cost_summary = f"課金計算不可 ({uncomputable_reason})"
        cost_value = None

    logger.info(
        "[%s] summary calls=%d in=%d cached=%d out=%d total=%d cost=%s",
        label,
        len(calls),
        total_in,
        total_cached,
        total_out,
        total_in + total_out,
        cost_summary,
    )

    return {
        "model": model,
        "calls": len(calls),
        "input_tokens": total_in,
        "cached_tokens": total_cached,
        "output_tokens": total_out,
        "total_tokens": total_in + total_out,
        "total_cost_usd": cost_value,
        "billing_status": billing_status,
        "uncomputable_reason": uncomputable_reason,
    }


__all__ = [
    "OpenAIPricingCalculator",
    "CallUsage",
    "ToolTokenAttribution",
    "UsageTracker",
    "build_billing_info",
    "estimate_text_tokens",
    "estimate_tool_attribution",
    "log_usage_report",
]
