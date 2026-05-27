"""Prompt construction for the custom browser ReAct loop."""

from __future__ import annotations

from appium_cli.openai_tools import get_tool_skill_prompt

from agent_browser.agent.state import BrowserOperationState, clamp_text
from agent_browser.config import AgentBrowserConfig


_BROWSER_AGENT_RULES = """You are a mobile browser automation agent.

Use exactly one browser tool call when an action or observation is needed.
After a tool result, return the structured AgentBrain JSON.

Memory rules:
- The prompt only contains current browser-operation state.
- Use refs only if they appear in the latest observation/current screen.
- Do not rely on old DOM or old screenshots.
- Keep working_state short: current page, filled values, pending fields, validation requirements, and recent failures only.

WebView observation rules:
- After goto or webview_switch, take web_snapshot as the primary page observation before making page-structure judgments.
- Do not pass depth for normal full-page web_snapshot calls. Full artifacts keep searchable targets; reduce tokens with snapshot_search, snapshot_show(ref), and paginated snapshot_refs instead.
- Use depth only for scoped/debug snapshots when intentionally inspecting a smaller subtree.
- Use snapshot_search, snapshot_refs, and web_query for targeted element/ref extraction from the observed page/artifacts.
- When the task requires reading or summarizing article/body/page text, use web_text. Do not infer body content from web_snapshot metadata.
- snapshot_refs is paginated. If has_more=true and the target is absent, refine the search/role or request the next page with offset=next_offset.
- Broad CSS discovery such as web_query(selector="a") may return many links. Do not conclude that a target is absent from one broad query alone.
- When the user asks for a category, domain, keyword, or URL pattern, narrow the CSS selector or search text (for example, a[href*='sports'] or snapshot_search(text='スポーツ')) before deciding it is missing.
- Before finishing with success or failure, base the result on an actual observation of the current page: web_snapshot, targeted web_query/snapshot_search/snapshot_refs, screenshot, or get_page_source.

Form rules:
- For simple inputs, fill and continue.
- For single-input forms (search bars, URL bars, filter boxes), use submit=true so the input is applied.
- Never use submit=true for intermediate fields in a multi-field form.
- For React-Select/autocomplete/combobox: use fill(ref, text, slowly=true), then web_snapshot to see suggestions, then click the matching option.
- Never use web_eval to set .value on React-controlled inputs.

Ref rules:
- Refs from snapshot (web_firstname, web_usernumber) are used with fill/click/tap.
- CSS selectors from web_query (#firstName, input[name=q]) cannot be used as refs.
- If the ref you need is not in the current snapshot, take a fresh web_snapshot first.
- After fill/click/tap, refs remain valid until the next snapshot replaces the ref map.

Completion:
- Set is_done=true only when the user's requested outcome is verified or impossible.
- Set success=true only if the user's goal was satisfied.
- The "result" field MUST contain the actual data the user requested, not a preview or promise.
- Do NOT set is_done=true with a result like "I will now summarize..." or "Here is what I found:" followed by nothing.
- Include all requested items (counts, fields, details, extracted text) directly in "result".
- If the goal asks for N items, include all N items in "result". Partial results are not sufficient.
- If data could not be obtained, set success=false and explain what is missing in "result".
- A runtime verifier will reject incomplete results and ask you to try again.
"""


def build_system_prompt() -> str:
    """Build the current system prompt.

    ``get_tool_skill_prompt()`` is intentionally called every time so the
    appium-cli tool adapter can return Native or WebView guidance according to
    the context mode established by prior tool calls. The browser agent does
    not infer or store Appium context mode itself.
    """

    return "\n\n".join([get_tool_skill_prompt(), _BROWSER_AGENT_RULES])



def build_input_items(
    state: BrowserOperationState,
    cfg: AgentBrowserConfig,
    *,
    recent_steps: str = "",
    compacted_history: str = "",
    loop_warning: str | None = None,
    reflection: str | None = None,
    blocked_tools: set[str] | None = None,
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
                state.latest_observation,
                "</current_screen>",
            ]
        )
    if recent_steps:
        parts.extend(["", "<recent_steps>", recent_steps, "</recent_steps>"])
    if state.last_step:
        parts.extend(["", "<last_step>", clamp_text(state.last_step, 300), "</last_step>"])
    if blocked_tools:
        parts.extend([
            "",
            "<blocked_tools>",
            f"The following tools have reached max_retries={cfg.max_retries} and will NOT execute: {', '.join(sorted(blocked_tools))}.",
            "Do NOT call them again. Use a different approach or finish with is_done=true and success=false.",
            "</blocked_tools>",
        ])
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
