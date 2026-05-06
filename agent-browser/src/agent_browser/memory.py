"""Working memory and persistent episodic memory for the Browser Agent.

Working memory lives only for the duration of a single run and is exposed to
tools through the OpenAI Agents SDK ``RunContextWrapper``. Episodic memory is
persisted to a JSONL file by default but the storage backend is abstracted via
the :class:`MemoryStore` protocol so it can be swapped later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Protocol
from urllib.parse import urlparse

from agent_browser.schemas import (
    ApprovalRecord,
    MemoryEvent,
    ObservationSummary,
    ToolCallRecord,
)


def domain_of(url: str | None) -> str | None:
    """Return the netloc portion of a URL, or None if the URL is invalid."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    return parsed.netloc or None


@dataclass(slots=True)
class WorkingMemory:
    """Mutable per-run state shared with tools via RunContextWrapper.context."""

    goal: str
    current_url: str | None = None
    latest_observation: ObservationSummary | None = None
    failures: list[str] = field(default_factory=list)
    approvals: dict[str, ApprovalRecord] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    retry_counts: dict[str, int] = field(default_factory=dict)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    final_result: dict[str, object] | None = None

    def record_failure(self, message: str) -> None:
        self.failures.append(message)

    def record_artifact(self, path: str) -> None:
        if path not in self.artifacts:
            self.artifacts.append(path)

    def record_approval(self, approval: ApprovalRecord) -> None:
        self.approvals[approval.approval_key] = approval

    def is_approved(self, approval_key: str) -> bool:
        record = self.approvals.get(approval_key)
        return bool(record and record.granted)

    def increment_retry(self, key: str) -> int:
        new_value = self.retry_counts.get(key, 0) + 1
        self.retry_counts[key] = new_value
        return new_value

    def total_retries(self) -> int:
        return sum(self.retry_counts.values())


class MemoryStore(Protocol):
    """Pluggable backend for episodic memory persistence."""

    def append(self, event: MemoryEvent) -> None: ...

    def read_all(self) -> list[MemoryEvent]: ...


class JsonlMemoryStore:
    """Append-only JSONL backend for :class:`MemoryEvent` records."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event: MemoryEvent) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = event.model_dump_json()
        with self._path.open("a", encoding="utf-8") as fp:
            fp.write(line)
            fp.write("\n")

    def read_all(self) -> list[MemoryEvent]:
        if not self._path.exists():
            return []
        events: list[MemoryEvent] = []
        with self._path.open("r", encoding="utf-8") as fp:
            for raw in fp:
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    # Skip malformed lines but keep going.
                    continue
                try:
                    events.append(MemoryEvent.model_validate(payload))
                except Exception:
                    continue
        return events


class EpisodicMemory:
    """High-level interface over a :class:`MemoryStore`.

    Provides convenience methods for appending typed events and selecting
    relevant historical hints to inject into the agent's instructions.
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def store(self) -> MemoryStore:
        return self._store

    def record(self, event: MemoryEvent) -> None:
        self._store.append(event)

    def record_many(self, events: Iterable[MemoryEvent]) -> None:
        for event in events:
            self._store.append(event)

    def all_events(self) -> list[MemoryEvent]:
        return self._store.read_all()

    def hints_for(self, *, domain: str | None = None, limit: int = 8) -> list[MemoryEvent]:
        """Return up to ``limit`` recent events relevant to ``domain``.

        If ``domain`` is provided, prefer events that match the domain. Always
        include the most recent failure events to help the agent avoid known
        problems.
        """
        events = self.all_events()
        if not events:
            return []

        scored: list[tuple[int, int, MemoryEvent]] = []
        for index, event in enumerate(events):
            score = 0
            if domain and event.domain == domain:
                score += 3
            if event.event_type in {"selector_failure", "tool_failure", "task_failed"}:
                score += 2
            if event.event_type in {"selector_success", "tool_success"}:
                score += 1
            # Recency: later events get a higher tiebreaker.
            scored.append((score, index, event))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [event for _, _, event in scored[:limit]]

    def __iter__(self) -> Iterator[MemoryEvent]:
        return iter(self.all_events())
