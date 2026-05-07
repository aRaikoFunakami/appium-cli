"""Tests for AgentBrain structured output."""

from __future__ import annotations

import json

from agent_browser.agent.brain import build_agent_brain_schema, parse_agent_brain


def test_agent_brain_schema_is_strict() -> None:
    schema = build_agent_brain_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"evaluation", "working_state", "next_goal", "is_done", "success", "result"}


def test_parse_agent_brain_clamps_working_state() -> None:
    text = json.dumps(
        {
            "evaluation": "ok",
            "working_state": "x" * 200,
            "next_goal": "continue",
            "is_done": False,
            "success": False,
            "result": None,
        }
    )
    brain = parse_agent_brain(text, working_state_cap=50)
    assert len(brain.working_state) <= 50
    assert brain.working_state.endswith("[trimmed]")
