"""Narrow LLM assistance hooks for ambiguous structured-controller choices."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LlmChoice:
    """A schema-friendly choice returned by future LLM-assisted disambiguation."""

    ref: str
    reason: str
