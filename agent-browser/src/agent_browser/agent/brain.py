"""Structured model output for the custom browser ReAct loop."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class AgentBrain(BaseModel):
    """Per-step structured output.

    This is operation state, not chat memory. Keep only information needed to
    decide the next browser action.
    """

    model_config = ConfigDict(extra="forbid")

    evaluation: str = Field(description="Short evaluation of the previous step.")
    working_state: str = Field(
        description="Browser-operation state only: current page, form progress, pending fields, validation requirements, and recent failures.",
    )
    next_goal: str = Field(description="The next single browser-operation goal.")
    is_done: bool = Field(description="Whether the task is complete.")
    success: bool = Field(description="Whether the user's goal was satisfied when is_done is true.")
    result: str | None = Field(default=None, description="Final report when is_done is true.")


def build_agent_brain_schema() -> dict[str, Any]:
    """Return a strict JSON schema suitable for Responses API text.format."""

    schema = AgentBrain.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)
    schema["additionalProperties"] = False
    schema["required"] = list(schema.get("properties", {}).keys())
    return schema


def parse_agent_brain(output_text: str, *, working_state_cap: int) -> AgentBrain:
    """Parse and clamp an AgentBrain from Responses API output text."""

    try:
        brain = AgentBrain.model_validate_json(output_text)
    except ValidationError:
        # Some models return a JSON object as plain text but with surrounding
        # whitespace/markdown. Do one conservative object extraction.
        start = output_text.find("{")
        end = output_text.rfind("}")
        if start < 0 or end <= start:
            raise
        brain = AgentBrain.model_validate(json.loads(output_text[start : end + 1]))

    if len(brain.working_state) > working_state_cap:
        brain = brain.model_copy(
            update={"working_state": brain.working_state[: working_state_cap - 20] + "... [trimmed]"}
        )
    return brain
