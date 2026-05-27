"""Query helpers for snapshot world models."""

from __future__ import annotations

from agent_browser.world.model import RefView, Snapshot, TextTarget


def find_text(snapshot: Snapshot, text: str) -> list[TextTarget]:
    """Return text targets containing text case-insensitively."""
    return snapshot.find_text(text)


def scrollable_containers(snapshot: Snapshot) -> list[RefView]:
    """Return scrollable container refs."""
    return snapshot.scrollable_containers()


def refs_within(snapshot: Snapshot, container_ref: str, role: str | None = None) -> list[RefView]:
    """Return refs inside a container, optionally filtered by role."""
    refs = snapshot.refs_within(container_ref)
    if role is None:
        return refs
    return [ref for ref in refs if ref.role == role]


def candidate_refs_by_name(snapshot: Snapshot, name_fragment: str) -> list[RefView]:
    """Return refs whose ref or accessible name contains the fragment."""
    lowered = name_fragment.lower()
    return [
        ref
        for ref in snapshot.refs.values()
        if lowered in ref.ref.lower() or lowered in ref.name.lower()
    ]
