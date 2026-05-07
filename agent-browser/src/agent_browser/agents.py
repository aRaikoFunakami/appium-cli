"""Single Browser Agent factory.

Builds one ``Agent`` configured with the appium-cli toolbelt, custom completion
and approval tools, dynamic instructions that include current memory state and
episodic hints, and a ``tool_use_behavior`` that stops the run as soon as the
agent calls ``browser_result``.
"""

from __future__ import annotations

import logging
from textwrap import dedent

from agents import Agent, ModelSettings, RunContextWrapper, StopAtTools

from agent_browser.appium_tools import BrowserAgentContext, all_tools
from agent_browser.config import AgentBrowserConfig
from agent_browser.memory import EpisodicMemory, domain_of
from agent_browser.schemas import MemoryEvent

logger = logging.getLogger(__name__)


def _model_settings_for_model(model: str) -> ModelSettings:
    """Return model settings compatible with the selected model."""

    kwargs: dict[str, object] = {"parallel_tool_calls": False}
    if not model.startswith("gpt-5"):
        kwargs["temperature"] = 0.2
    return ModelSettings(**kwargs)


_BASE_POLICY = dedent(
    """
    You are a mobile browser automation agent driving Android Chrome via appium-cli tools.

    RULES:
    1. One tool per turn. Verify every action with an observation tool before proceeding.
    2. Call browser_result exactly once when done (or proven unreachable).
    3. Never invent refs or tools. Only use refs from the latest snapshot.

    CHROME WORKFLOW:
    1. get_current_app → if not Chrome, activate_app("com.android.chrome").
    2. After Chrome is active with a page loaded, webview_switch() to enter WebView context.
       Do NOT call webview_switch before Chrome is active — it will fail.
    3. goto(url=...) or interact using refs from web_snapshot.
    4. Verify with webview_url / webview_title before calling browser_result.

    OBSERVATION — TOKEN-EFFICIENT PATTERN:
    - After any action, a snapshot is already saved to disk automatically.
    - To find elements: snapshot_search(text="...") or snapshot_refs(role="button").
    - For DOM queries: web_query(selector="input,button,a", attrs="name,type,...").
    - To inspect one ref: snapshot_show(ref="btn_login").
    - AVOID calling snapshot_show with artifact=compact — it returns the full tree and wastes tokens.
    - Only call snapshot/web_snapshot for a FRESH tree after context switch or dynamic wait.

    CONTEXT RULES:
    - Native refs ≠ WebView refs. Never reuse refs across a context switch.
    - After activate_app or webview_switch, observe first before acting.

    ERRORS: Do not retry the same failing call. Observe, then try a different approach.
    Use snapshot_search, snapshot_refs, web_query, or scroll_down + snapshot to find elements.
    After 2 failures on the same operation, call browser_result(success=False).

    SAFETY: For login/payment/personal-data actions, call human_approval first.
    If BLOCKED, do not retry. If APPROVAL_REQUIRED, get approval then retry.
    """
).strip()


def _format_memory_section(ctx: RunContextWrapper[BrowserAgentContext]) -> str:
    memory = ctx.context.memory
    lines = ["CURRENT WORKING MEMORY:"]
    lines.append(f"- goal: {memory.goal}")
    lines.append(f"- current_url: {memory.current_url or '(unknown)'}")
    if memory.latest_observation is not None:
        obs = memory.latest_observation
        lines.append(
            f"- last_observation: source={obs.source} title={obs.title!r} url={obs.url!r}"
        )
    if memory.failures:
        recent = memory.failures[-3:]
        lines.append("- recent failures:")
        for failure in recent:
            lines.append(f"    * {failure[:200]}")
    if memory.retry_counts:
        retries = ", ".join(f"{k}={v}" for k, v in memory.retry_counts.items())
        lines.append(f"- retries: {retries}")
    if memory.approvals:
        granted = [k for k, v in memory.approvals.items() if v.granted]
        if granted:
            lines.append(f"- approvals granted: {', '.join(granted)}")
    return "\n".join(lines)


def _format_hints(episodic: EpisodicMemory | None, current_url: str | None) -> str:
    if episodic is None:
        return ""
    domain = domain_of(current_url)
    hints = episodic.hints_for(domain=domain, limit=6)
    if not hints:
        return ""
    lines = ["EPISODIC HINTS (from past runs, may be stale):"]
    for event in hints:
        descriptor = f"[{event.event_type}]"
        bits = []
        if event.tool_name:
            bits.append(f"tool={event.tool_name}")
        if event.selector_ref:
            bits.append(f"ref={event.selector_ref}")
        if event.domain:
            bits.append(f"domain={event.domain}")
        if event.detail:
            bits.append(f"detail={event.detail[:120]}")
        lines.append(f"- {descriptor} " + " ".join(bits))
    return "\n".join(lines)


def create_browser_agent(
    config: AgentBrowserConfig,
    episodic_memory: EpisodicMemory | None = None,
) -> Agent[BrowserAgentContext]:
    """Build and return the single Browser Agent."""

    def dynamic_instructions(
        ctx: RunContextWrapper[BrowserAgentContext],
        agent: Agent[BrowserAgentContext],
    ) -> str:
        sections = [_BASE_POLICY, _format_memory_section(ctx)]
        hints = _format_hints(ctx.context.episodic, ctx.context.memory.current_url)  # type: ignore[arg-type]
        if hints:
            sections.append(hints)
        return "\n\n".join(sections)

    tools = all_tools()
    return Agent[BrowserAgentContext](
        name="BrowserAgent",
        instructions=dynamic_instructions,
        tools=tools,
        model=config.model,
        # parallel_tool_calls=False forces the model to observe -> act
        # sequentially, which avoids issuing fill/tap with stale refs from
        # before a context switch (a real failure mode observed in testing).
        model_settings=_model_settings_for_model(config.model),
        # Stop the run as soon as the agent calls browser_result. Its return
        # value (RESULT_RECORDED ...) is treated as the final output.
        tool_use_behavior=StopAtTools(stop_at_tool_names=["browser_result"]),
        reset_tool_choice=True,
    )
