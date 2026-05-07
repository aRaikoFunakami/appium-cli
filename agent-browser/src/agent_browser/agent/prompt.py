"""Prompt construction for the custom browser ReAct loop."""

from __future__ import annotations

from agent_browser.agent.state import BrowserOperationState, clamp_text
from agent_browser.config import AgentBrowserConfig


SYSTEM_PROMPT = """You are a mobile browser automation agent.

Use exactly one browser tool call when an action or observation is needed.
After a tool result, return the structured AgentBrain JSON.

Memory rules:
- The prompt only contains current browser-operation state.
- Use refs only if they appear in the latest observation/current screen.
- Old refs are stale after a new snapshot/web_snapshot.
- Do not rely on old DOM or old screenshots.
- Keep working_state short: current page, filled values, pending fields, validation requirements, and recent failures only.

Form rules:
- For simple inputs, fill and continue.
- Never use submit=true for intermediate fields in a multi-field form.
- Never use send_keys or press_key for React-Select/combobox inputs.
- Prefer fill(ref,text), then click the visible option.

Completion:
- Set is_done=true only when the user's requested outcome is verified or impossible.
- Set success=true only if the user's goal was satisfied.
- Put the final concise report in result.
"""


def build_input_items(
    state: BrowserOperationState,
    cfg: AgentBrowserConfig,
    *,
    recent_steps: str = "",
    compacted_history: str = "",
    loop_warning: str | None = None,
    reflection: str | None = None,
) -> list[dict[str, object]]:
    """Build a fresh Responses API input list for the next model call."""

    parts = [
        "<task>",
        f"Goal: {clamp_text(state.goal, 1000)}",
        f"Phase: {state.phase}",
        "</task>",
        "",
        "<working_state>",
        clamp_text(state.working_state or "(none yet)", cfg.working_state_char_cap),
        "</working_state>",
    ]
    if compacted_history:
        parts.extend(["", "<compact_notes>", clamp_text(compacted_history, 500), "</compact_notes>"])
    if state.latest_observation:
        parts.extend(
            [
                "",
                "<current_screen>",
                clamp_text(state.latest_observation, cfg.max_observation_chars),
                "</current_screen>",
            ]
        )
    if recent_steps:
        parts.extend(["", "<recent_steps>", recent_steps, "</recent_steps>"])
    if state.last_step:
        parts.extend(["", "<last_step>", clamp_text(state.last_step, 300), "</last_step>"])
    if loop_warning:
        parts.extend(["", "<loop_warning>", clamp_text(loop_warning, 300), "</loop_warning>"])
    if reflection:
        parts.extend(["", "<reflection>", clamp_text(reflection, 300), "</reflection>"])

    parts.extend(
        [
            "",
            "<next_action_rule>",
            "Choose exactly one browser action that advances the goal from the current screen, or finish with is_done=true.",
            "</next_action_rule>",
        ]
    )
    return [{"role": "user", "content": [{"type": "input_text", "text": "\n".join(parts)}]}]
