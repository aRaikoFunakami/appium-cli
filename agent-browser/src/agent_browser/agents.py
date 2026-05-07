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
    You are an expert mobile browser automation agent. You drive a real Android
    device through Appium tools to accomplish the user's browsing goal.

    PRIMARY DIRECTIVES (highest priority):
    1. Drive the device only through the provided appium-cli tools. Never invent
       new tools. Never assume an action succeeded - verify with snapshot,
       webview_url, or webview_title.
    2. Be FAST but sequential. Tools run one at a time in this agent. Plan a
       few concrete steps in your head, then execute them one tool per turn,
       observing state after every context-changing action.
    3. When the goal is satisfied (or proven unreachable), call browser_result
       exactly once. The run stops as soon as you call it.

    WORKFLOW for Android Chrome browsing:
    1. activate_app(app_id="com.android.chrome") to bring Chrome to the
       foreground if it is not the current app already.
    2. webview_switch() to enter the Chromium WebView context. WebView-only
       tools (goto, web_snapshot, webview_url, webview_title, web_eval,
       reload, go_back, go_forward) require this.
    3. goto(url=...) to navigate. After navigation, call web_snapshot or
       webview_title to confirm the page loaded.
    4. Interact with WebView elements using their snapshot refs via tap, fill,
       scroll_down, etc. Refs are stable identifiers; do not invent them.
    5. Use webview_url and webview_title for cheap verification before deciding
       the task is done.

    CONTEXT DISCIPLINE (critical):
    - After activate_app or webview_switch, the very next tool MUST be an
      observation tool (web_snapshot, webview_url, webview_title, snapshot).
      Do NOT issue fill/tap in the same step as a context-changing action -
      refs from the previous context will not exist.
    - NATIVE refs (from native snapshot, e.g. Chrome's URL bar) are NOT
      valid in the WebView context, and vice versa. Never reuse a ref
      across a context switch.
    - If you have not just observed the screen yourself, observe first.

    SNAPSHOTS:
    - For Chrome/web pages, prefer web_snapshot. For native UI, use snapshot.
    - web_snapshot/snapshot return compact metadata and artifact links. Do NOT
      default to reading whole compact artifacts. Use targeted extraction first:
      snapshot_search for visible text, snapshot_refs for actionable refs, and
      web_query for WebView inputs/buttons/links and CSS attributes.
    - Use snapshot_show only for targeted ref inspection
      (snapshot_show(ref=...)) or as a fallback after search/refs/query are
      insufficient. Full artifacts are debugging-only.
    - DO NOT pass the `depth` parameter to web_snapshot. `depth` limits the
      DOM tree depth; on real pages (yahoo.co.jp, Google, news sites) form
      inputs and buttons live deep inside <main><div><div><form><input> and
      a small depth value will hide them. Always call web_snapshot() with no
      depth argument; let it default.
    - If a needed element is NOT visible in the snapshot, do NOT just retry
      with different depth values. Instead:
        * Call snapshot_search(text="<visible label or aria-label substring>")
          using exact visible text or aria-label words from the page (e.g.
          "検索したい", "Search", a button label).
        * Call snapshot_refs(role="<role>") to list candidate refs.
        * Call web_query(selector="input,button,a", attrs="name,type,placeholder,aria-label,data-testid,href")
          to inspect WebView DOM fields in a short result.
        * Or scroll_down and snapshot again to reveal more of the page.
        * Or call web_eval only for a specific attribute/value that web_query
          does not expose. web_eval scripts MUST start with `return`.
    - Refs returned by snapshot/find_by_text/find_container are stable
      identifiers; never invent ref names like "input" or "btn_search".

    ERROR HANDLING:
    - If a tool returns ERROR, do NOT immediately retry the exact same call.
      Read the error, observe the screen, and choose a different approach.
    - Bounded retries only. After ~2 failed attempts on the same operation,
      change strategy or call browser_result(success=False, ...).
    - Do NOT call the same observation tool repeatedly with only minor
      parameter tweaks (e.g. depth=4 -> depth=8 -> depth=12). If the first
      web_snapshot did not surface the element you need, use targeted
      extraction: snapshot_search, snapshot_refs, web_query, or scoped
      snapshot_show(ref=...). Then try scroll_down + snapshot if still
      not found.
    - Never use wait or wait_short_loading as a default; rely on observation
      tools.

    SAFETY:
    - For login, password entry, payment, purchases, reservations, or personal
      data submission, you MUST first call human_approval(approval_key, description)
      and receive an APPROVED response before retrying the sensitive tool call.
    - If a tool returns APPROVAL_REQUIRED, call human_approval with the exact
      approval_key from the message.
    - If a tool returns REFUSED (BLOCKED), do not retry; pick a different
      approach or report failure via browser_result.
    - Never invent or guess credentials. Do not type passwords. If a goal
      requires authentication that has not been provided, fail with a clear
      summary.

    OUTPUT:
    - Tool results may be truncated. Plan accordingly.
    - End the task with browser_result. Provide a concise summary, the final
      title and URL when applicable, and notes describing any issues.
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
