"""Tool-call safety policy.

Sensitive actions (login, payment, PII, purchases, reservations) require an
approval recorded in the run context before they are executed. Destructive
actions are blocked unconditionally locally and never reach the daemon.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent_browser.memory import WorkingMemory
from agent_browser.schemas import SafetyCategory, SafetyDecision


# Tools whose mere invocation never requires approval (read-only observation).
_OBSERVATION_TOOLS = frozenset({
    "snapshot",
    "web_snapshot",
    "describe",
    "find_by_text",
    "screenshot",
    "get_page_source",
    "webview_url",
    "webview_title",
    "list_containers",
    "find_container",
    "get_current_app",
    "list_apps",
    "get_device_info",
    "is_locked",
    "get_orientation",
    "get_text",
    "get_driver_status",
    "list_contexts",
    "get_context",
    "webview_status",
    "assert_visible",
})

# Tools that are unconditionally blocked locally. We refuse to forward these
# to the daemon regardless of any approval.
BLOCKED_TOOLS: frozenset[str] = frozenset({
    "terminate_app",
    "restart_app",
    "set_orientation",
})


# Patterns over (tool_name, stringified args) that mark a sensitive action.
# Patterns are applied case-insensitively.
@dataclass(frozen=True, slots=True)
class _Pattern:
    label: str
    regex: re.Pattern[str]


_SENSITIVE_PATTERNS: tuple[_Pattern, ...] = (
    # Substring matches - selectors often contain underscores (login_btn, signin_field).
    _Pattern("login", re.compile(r"(login|log[\W_]*in|sign[\W_]*in|signin|signup|sign[\W_]*up|register)", re.IGNORECASE)),
    _Pattern("password", re.compile(r"(password|passwd|passcode|otp|two[\W_]*factor|2fa)", re.IGNORECASE)),
    _Pattern("payment", re.compile(r"(payment|checkout|credit[\W_]*card|card[\W_]*number|cvv|cvc|billing)", re.IGNORECASE)),
    _Pattern("purchase", re.compile(r"(purchase|buy[\W_]*now|place[\W_]*order|confirm[\W_]*order)", re.IGNORECASE)),
    _Pattern("reservation", re.compile(r"(reserve|book[\W_]*now|confirm[\W_]*reservation|confirm[\W_]*booking)", re.IGNORECASE)),
    _Pattern("personal_data", re.compile(r"(ssn|social[\W_]*security|passport|driver'?s?[\W_]*license|tax[\W_]*id)", re.IGNORECASE)),
)


def _stringify_arg_values(args: dict[str, Any] | None) -> str:
    """Stringify only argument *values* (not keys) to avoid spurious key matches.

    For example, ``submit=True`` should not by itself trigger a "submit" pattern;
    the boolean flag value ``True`` will not match any sensitive pattern.
    """
    if not args:
        return ""
    parts: list[str] = []
    for value in args.values():
        if isinstance(value, bool):
            continue
        parts.append(str(value))
    return " ".join(parts)


def _matches(text: str) -> _Pattern | None:
    for pattern in _SENSITIVE_PATTERNS:
        if pattern.regex.search(text):
            return pattern
    return None


def classify_tool_call(name: str, args: dict[str, Any] | None) -> SafetyDecision:
    """Classify a pending tool call into safe / sensitive / blocked.

    The classification is local-only. ``call_tool`` is never invoked here.
    """
    tool_name = name.strip()

    if tool_name in BLOCKED_TOOLS:
        return SafetyDecision(
            tool_name=tool_name,
            category=SafetyCategory.BLOCKED,
            reason=f"Tool '{tool_name}' is blocked by local policy.",
        )

    # Special-case: type_text / fill / send_keys with sensitive text content.
    if tool_name in {"type_text", "fill", "send_keys"} and args:
        text_value = str(args.get("text") or args.get("value") or "")
        ref_value = str(args.get("ref") or "")
        # Only inspect the text/ref - never the boolean ``submit`` flag.
        haystack = f"{ref_value} {text_value}"
        match = _matches(haystack)
        if match is not None:
            approval_key = f"{tool_name}:{match.label}"
            return SafetyDecision(
                tool_name=tool_name,
                category=SafetyCategory.SENSITIVE,
                reason=f"Detected sensitive '{match.label}' content in input.",
                matched_pattern=match.label,
                approval_key=approval_key,
            )
        # Typing into a non-sensitive field is safe even if submit=True.
        return SafetyDecision(tool_name=tool_name, category=SafetyCategory.SAFE)

    if tool_name in _OBSERVATION_TOOLS:
        return SafetyDecision(tool_name=tool_name, category=SafetyCategory.SAFE)

    # For other tools, scan only the argument *values* for sensitive references.
    haystack = f"{tool_name} {_stringify_arg_values(args)}"
    match = _matches(haystack)
    if match is not None:
        approval_key = f"{tool_name}:{match.label}"
        return SafetyDecision(
            tool_name=tool_name,
            category=SafetyCategory.SENSITIVE,
            reason=f"Detected sensitive '{match.label}' reference in tool call.",
            matched_pattern=match.label,
            approval_key=approval_key,
        )

    return SafetyDecision(tool_name=tool_name, category=SafetyCategory.SAFE)


def requires_approval(decision: SafetyDecision) -> bool:
    return decision.category == SafetyCategory.SENSITIVE


def is_approved(memory: WorkingMemory, decision: SafetyDecision) -> bool:
    if decision.approval_key is None:
        return False
    return memory.is_approved(decision.approval_key)
