"""Pytest fixtures shared across agent-browser unit tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def tmp_memory_path(tmp_path):
    return tmp_path / "memory.jsonl"
