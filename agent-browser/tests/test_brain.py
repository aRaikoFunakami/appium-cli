"""Tests for AgentBrain structured output."""

from __future__ import annotations

import json
import logging

import pytest
from pydantic import ValidationError

from agent_browser.agent.brain import build_agent_brain_schema, parse_agent_brain


def test_agent_brain_schema_is_strict() -> None:
    schema = build_agent_brain_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"evaluation", "working_state", "next_goal", "is_done", "success", "result"}


VALID_BRAIN_DICT = {
    "evaluation": "ok",
    "working_state": "page loaded",
    "next_goal": "fill form",
    "is_done": False,
    "success": False,
    "result": None,
}


def test_parse_agent_brain_succeeds_with_markdown_wrapped_json() -> None:
    text = "Here is the result:\n" + json.dumps(VALID_BRAIN_DICT) + "\nDone."
    brain = parse_agent_brain(text, working_state_cap=200)
    assert brain.evaluation == "ok"
    assert brain.working_state == "page loaded"
    assert brain.next_goal == "fill form"
    assert brain.is_done is False
    assert brain.success is False
    assert brain.result is None


def test_parse_agent_brain_fails_on_concatenated_json_objects() -> None:
    text = json.dumps(VALID_BRAIN_DICT) + json.dumps(VALID_BRAIN_DICT)
    with pytest.raises((ValidationError, json.JSONDecodeError)):
        parse_agent_brain(text, working_state_cap=200)


def test_parse_agent_brain_logs_diagnostics_on_failure(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="agent_browser.agent.brain"):
        with pytest.raises((ValidationError, json.JSONDecodeError)):
            parse_agent_brain("not json at all", working_state_cap=200)
    assert any("[brain] direct parse failed" in msg for msg in caplog.messages)


def test_parse_agent_brain_logs_fallback_extraction_details(caplog: pytest.LogCaptureFixture) -> None:
    text = "prefix {invalid json content} suffix"
    with caplog.at_level(logging.DEBUG, logger="agent_browser.agent.brain"):
        with pytest.raises(Exception):
            parse_agent_brain(text, working_state_cap=200)
    assert any("[brain] fallback extraction:" in msg for msg in caplog.messages)


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
