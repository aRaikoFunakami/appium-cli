"""Browser operation state used to rebuild prompts every iteration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Phase = Literal["navigating", "filling", "verifying", "done"]


@dataclass(slots=True)
class BrowserOperationState:
    """Minimal state allowed into the model prompt."""

    goal: str
    phase: Phase = "navigating"
    latest_observation: str = ""
    working_state: str = ""
    last_step: str | None = None
    loop_warning: str | None = None
    reflection: str | None = None

    def consume_reflection(self) -> str | None:
        value = self.reflection
        self.reflection = None
        return value


def clamp_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 20] + "... [trimmed]"
