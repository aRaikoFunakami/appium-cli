"""Tests for memory module: WorkingMemory, JsonlMemoryStore, EpisodicMemory."""

from __future__ import annotations

from agent_browser.memory import (
    EpisodicMemory,
    JsonlMemoryStore,
    WorkingMemory,
    domain_of,
)
from agent_browser.schemas import ApprovalRecord, MemoryEvent


class TestDomainOf:
    def test_https(self) -> None:
        assert domain_of("https://example.com/foo") == "example.com"

    def test_none(self) -> None:
        assert domain_of(None) is None
        assert domain_of("") is None

    def test_relative(self) -> None:
        assert domain_of("/foo/bar") is None


class TestWorkingMemory:
    def test_record_failure_and_artifact(self) -> None:
        m = WorkingMemory(goal="g")
        m.record_failure("oops")
        m.record_failure("again")
        m.record_artifact("a.png")
        m.record_artifact("a.png")  # dedup
        assert m.failures == ["oops", "again"]
        assert m.artifacts == ["a.png"]

    def test_approval_lifecycle(self) -> None:
        m = WorkingMemory(goal="g")
        assert not m.is_approved("k")
        m.record_approval(ApprovalRecord(approval_key="k", granted=True))
        assert m.is_approved("k")
        m.record_approval(ApprovalRecord(approval_key="k2", granted=False))
        assert not m.is_approved("k2")

    def test_retry_counts(self) -> None:
        m = WorkingMemory(goal="g")
        assert m.increment_retry("tap") == 1
        assert m.increment_retry("tap") == 2
        assert m.increment_retry("fill") == 1
        assert m.total_retries() == 3


class TestJsonlMemoryStore:
    def test_append_and_read(self, tmp_memory_path) -> None:
        store = JsonlMemoryStore(tmp_memory_path)
        assert store.read_all() == []
        store.append(MemoryEvent(event_type="tool_success", tool_name="tap"))
        store.append(MemoryEvent(event_type="tool_failure", tool_name="goto", detail="bad url"))
        events = store.read_all()
        assert len(events) == 2
        assert events[0].tool_name == "tap"
        assert events[1].detail == "bad url"

    def test_skip_malformed_lines(self, tmp_memory_path) -> None:
        tmp_memory_path.write_text(
            '{"event_type":"tool_success","tool_name":"tap"}\n'
            'this is not json\n'
            '{"event_type":"tool_failure","tool_name":"x"}\n',
            encoding="utf-8",
        )
        store = JsonlMemoryStore(tmp_memory_path)
        events = store.read_all()
        assert len(events) == 2

    def test_creates_parent_dir(self, tmp_path) -> None:
        path = tmp_path / "subdir" / "memory.jsonl"
        store = JsonlMemoryStore(path)
        store.append(MemoryEvent(event_type="tool_success", tool_name="tap"))
        assert path.exists()


class TestEpisodicMemory:
    def test_hints_prefer_domain_and_failures(self, tmp_memory_path) -> None:
        store = JsonlMemoryStore(tmp_memory_path)
        store.append(MemoryEvent(event_type="tool_success", tool_name="tap", domain="other.com"))
        store.append(MemoryEvent(event_type="tool_failure", tool_name="goto", domain="example.com", detail="fail"))
        store.append(MemoryEvent(event_type="selector_success", tool_name="tap", domain="example.com", selector_ref="login_btn"))
        episodic = EpisodicMemory(store)
        hints = episodic.hints_for(domain="example.com", limit=2)
        assert len(hints) == 2
        # Failure on the matching domain should outrank a success on other domain.
        assert hints[0].domain == "example.com"

    def test_no_hints_when_empty(self, tmp_memory_path) -> None:
        episodic = EpisodicMemory(JsonlMemoryStore(tmp_memory_path))
        assert episodic.hints_for(domain="example.com") == []
