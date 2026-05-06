"""Pydantic schemas for agent-browser runtime data and final results."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _BaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SafetyCategory(str, Enum):
    """Safety classification for a tool call."""

    SAFE = "safe"
    SENSITIVE = "sensitive"
    BLOCKED = "blocked"


class SafetyDecision(_BaseModel):
    """Outcome of inspecting a pending tool call."""

    tool_name: str
    category: SafetyCategory
    reason: str | None = None
    matched_pattern: str | None = None
    approval_key: str | None = Field(
        default=None,
        description="Stable key used to look up an approval record for sensitive actions.",
    )


class ApprovalRecord(_BaseModel):
    """Record of a human approval granted for a sensitive action."""

    approval_key: str
    granted: bool
    note: str | None = None
    granted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolCallRecord(_BaseModel):
    """Structured log entry for a single tool invocation."""

    tool_name: str
    arguments_summary: str = Field(
        description="Truncated, non-secret summary of arguments suitable for logs.",
    )
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float | None = None
    ok: bool | None = None
    error: str | None = None
    artifact_path: str | None = None


class ObservationSummary(_BaseModel):
    """Compact observation derived from a snapshot/url/title call."""

    source: Literal["snapshot", "web_snapshot", "webview_url", "webview_title", "other"]
    url: str | None = None
    title: str | None = None
    summary: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryEvent(_BaseModel):
    """Single episodic-memory record persisted to JSONL."""

    event_type: Literal[
        "tool_success",
        "tool_failure",
        "selector_success",
        "selector_failure",
        "approval",
        "task_complete",
        "task_failed",
    ]
    domain: str | None = None
    tool_name: str | None = None
    selector_ref: str | None = None
    retry_count: int | None = None
    detail: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BrowserResultPayload(_BaseModel):
    """Argument schema for the browser_result completion tool."""

    success: bool
    title: str | None = None
    url: str | None = None
    summary: str
    notes: str | None = None


class TaskResult(_BaseModel):
    """Final structured result returned by run_browser_task()."""

    goal: str
    success: bool
    title: str | None = None
    url: str | None = None
    summary: str
    notes: str | None = None
    tool_calls: int = 0
    retries: int = 0
    artifacts: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    finished_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
