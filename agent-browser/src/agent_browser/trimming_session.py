"""Custom Session that trims old verbose tool outputs to save context.

Inspired by smartestiroid's IterationContext pattern: keep only the most
recent snapshot/observation tool result verbatim, replace older ones with a
short stub. The agent can always re-fetch fresh state with another tool call.

Without this, every web_snapshot/find_by_text/screenshot result (often
~8000 chars) accumulates in conversation history, which:
  * Slows down each subsequent LLM turn (more input tokens to process)
  * Wastes money on token billing
  * Makes the model focus on stale state from earlier turns
"""
from __future__ import annotations

from typing import Any


class TrimmingSession:
    """In-memory Session that strips old large tool outputs.

    Strategy:
      * Keep all function_call items intact (the model needs to see what was
        attempted and which arguments were used).
      * Keep the N most recent function_call_output items verbatim.
      * For older function_call_output items whose ``output`` is longer than
        ``size_threshold`` characters, replace the output with a short stub
        noting the original length and tool call_id.

    This implements the Session protocol from openai-agents.
    """

    def __init__(
        self,
        session_id: str = "default",
        *,
        keep_recent: int = 2,
        size_threshold: int = 800,
    ) -> None:
        self.session_id = session_id
        self.session_settings = None
        self._items: list[dict[str, Any]] = []
        self._keep_recent = keep_recent
        self._size_threshold = size_threshold

    async def get_items(self, limit: int | None = None) -> list[dict[str, Any]]:
        items = self._materialize()
        if limit is None:
            return items
        return items[-limit:]

    async def add_items(self, items: list[dict[str, Any]]) -> None:
        # Items can be Pydantic models or plain dicts; normalize to dicts so
        # we can mutate output fields when trimming.
        for item in items:
            if hasattr(item, "model_dump"):
                self._items.append(item.model_dump(exclude_unset=False))
            elif isinstance(item, dict):
                self._items.append(dict(item))
            else:
                self._items.append(item)

    async def pop_item(self) -> dict[str, Any] | None:
        if self._items:
            return self._items.pop()
        return None

    async def clear_session(self) -> None:
        self._items.clear()

    def _materialize(self) -> list[dict[str, Any]]:
        # Indices of all function_call_output entries in chronological order.
        output_indices = [
            i
            for i, item in enumerate(self._items)
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        keep_idx = set(output_indices[-self._keep_recent :]) if output_indices else set()

        result: list[dict[str, Any]] = []
        for i, item in enumerate(self._items):
            if (
                isinstance(item, dict)
                and item.get("type") == "function_call_output"
                and i not in keep_idx
            ):
                output = item.get("output", "")
                if isinstance(output, str) and len(output) > self._size_threshold:
                    stub = (
                        f"[earlier tool output omitted: was {len(output)} chars. "
                        f"State may have changed - call the tool again to get fresh data.]"
                    )
                    trimmed = dict(item)
                    trimmed["output"] = stub
                    result.append(trimmed)
                    continue
            result.append(item)
        return result
