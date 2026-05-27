"""OpenAI tool interface adapter for appium-cli.

This module provides:
- ``get_openai_tools()`` — Generate OpenAI Chat Completions tool definitions
- ``call_tool()`` — Execute a tool call through the session daemon
- ``get_tool_skill_prompt()`` — Return reusable appium-cli tool usage guidance

It does NOT import or depend on the OpenAI SDK. External callers import
this module and wire it into their own OpenAI client loop.

Usage example (external caller)::

    from openai import OpenAI
    from appium_cli.openai_tools import get_openai_tools, call_tool

    client = OpenAI()
    tools = get_openai_tools()

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[...],
        tools=tools,
    )

    for tool_call in response.choices[0].message.tool_calls:
        result = call_tool(tool_call.function.name, tool_call.function.arguments)
        # submit result back to OpenAI...
"""

from __future__ import annotations

import json
from typing import Any, Literal

from appium_cli.daemon.client import request
from appium_cli.tool_registry import ToolDef, get_tool, list_tools, normalize_tool_call
from appium_cli.utils import exit_codes


PromptContextMode = Literal["native", "webview"]

_prompt_context_mode: PromptContextMode = "native"

COMMON_TOOL_PROMPT = """appium-cli tool skill:

Use appium-cli tools as an artifact-first, snapshot/ref-based mobile automation surface.
The active prompt section is selected by appium-cli's tool adapter from the
current Appium context mode. Follow the ordered examples; do not invent ad-hoc
tool sequences when a workflow below applies.

Core loop:
1. Observe with the context-appropriate snapshot tool.
2. In WebView, treat web_snapshot() as the authoritative page observation and ref source.
3. Find targets from the latest snapshot first with snapshot_search(), snapshot_refs(), and snapshot_show(ref=...).
4. Act only on refs from the latest snapshot/ref map, or use goto() directly when auxiliary href extraction returns a target URL.
5. Observe again after navigation, reload, scroll, click, fill+submit, dialog handling, or any action that may change the page.
6. Use only refs from the latest observation/artifacts. Old refs can become stale.

Token-safe artifact usage:
- snapshot() and web_snapshot() save full trees as artifacts. Do not read or list the whole artifact by default.
- Search first, then inspect small fragments: snapshot_search(text=...), snapshot_show(ref=...), or narrow snapshot_refs(role=...) when the result set is expected to be small.
- Avoid broad link dumps on portal/list/search-result pages, especially snapshot_refs({"snapshot_id": "latest", "role": "link"}) and snapshot_show({"snapshot_id": "latest"}) without a ref.
- Avoid broad CSS dumps such as web_query({"selector": "a", ...}) unless you are debugging. If href discovery is needed, use a narrow selector and a small limit.
- Good low-token sequence: web_snapshot({}) -> snapshot_search({"snapshot_id": "latest", "text": "<target>"}) -> snapshot_show({"snapshot_id": "latest", "ref": "<candidate ref>"}) -> click({"ref": "<candidate ref>"}).

Targeting rules:
- Snapshot refs are valid function-call arguments.
- Prefer snapshot refs over CSS/query targets. In WebView, snapshot refs are the web_* refs from the latest web_snapshot.
- Use web_query() only as an auxiliary tool for CSS/attribute/href/text discovery when snapshot_search(), snapshot_refs(), or snapshot_show() are ambiguous or insufficient.
- When web_query() returns an href for the desired page, prefer goto({"url": "<href>"}) instead of click({"ref": "..."}). Do not click refs copied from web_query output unless the same ref is present in the current web_snapshot ref map.
- If duplicate labels/refs appear, inspect with snapshot_refs(), snapshot_show({"ref": "..."}), list_containers(), or within_container() before acting.
- If visible text has no ref, target the nearest actionable parent row, button, link, container, or form control; find_by_text can help locate it.

Diagnostics and fallback order:
1. If context/prerequisite behavior is unclear, call get_context({}), list_contexts({}), webview_status({}), or get_driver_status({}).
2. If snapshot artifacts are insufficient, try targeted snapshot_search(), snapshot_refs(), or snapshot_show({"ref": "..."}).
3. Use console_messages() for browser console logs; returned entries may be consumed by the call.
4. Use network_requests() only when the session was started with network logging enabled.
5. Use screenshot() only when visual pixels are necessary.
6. Use get_page_source() only as a token-heavy diagnostic escape hatch after targeted tools are insufficient.
7. Diagnostics such as doctor, devices, get_device_info, webview_status, console_messages, and network_requests observe state; they do not install or fix prerequisites.

Verification and completion:
- Before finishing, verify the current page/state with snapshot(), web_snapshot(), targeted query/search/ref tools, screenshot(), get_page_source(), or assert_visible().
- If the goal asks for N items, collect and report all N items. Partial results are not success.
- For information retrieval, report the actual data plus concise provenance: start page, list/search/category page, detail pages or records inspected, and explicit constraint checks.
- If a verifier says evidence/provenance/formatting is missing but the data was already collected, finish again with a corrected result instead of browsing more.
- If data cannot be obtained, report what was tried and what is missing.
- Use wait_for() for asynchronous conditions: text appears, text disappears, or a ref becomes visible. Avoid wait_short_loading in normal workflows.

Responsibility boundary:
- Tool calls require an active appium-cli session. When the caller owns lifecycle, use one fresh session per user task and stop it at task end; stale sessions can cause InvalidSessionIdException.
- If refs/session state appear stale or the daemon loses WebDriver state, recover with session status, session stop, session start, then snapshot.
- Do not call adb, appium, npm, or installer commands directly from an appium-cli tool-calling agent unless the user explicitly asked for prerequisite management outside appium-cli.
- Do not cap depth for normal full-page observations unless there is a clear reason; full-page observations should preserve all visible targets.
"""

NATIVE_TOOL_PROMPT = """Current appium-cli context guidance: NATIVE_APP

Use native accessibility snapshots and native/mobile actions. Do not use WebView DOM tools until a WebView context switch/navigation succeeds.

Native UI: observe, find refs, act:
1. snapshot({})
2. snapshot_refs({"snapshot_id": "latest", "role": "button"})
3. tap({"ref": "<button ref>"})
4. snapshot({})
5. snapshot_search({"text": "expected text"}) or assert_visible({"text": "expected text"})

Native UI: enter text:
1. snapshot({})
2. snapshot_refs({"snapshot_id": "latest", "role": "textbox"})
3. type_text({"ref": "<input ref>", "text": "value", "submit": false})
4. snapshot({})

Native UI: scrolling and lists:
1. snapshot({})
2. list_containers({}) or snapshot_refs({"snapshot_id": "latest"}) when you need a scrollable/list ref.
3. scroll_down({"ref": "<container ref>"}) to scroll inside a list; scroll_down({}) only for intentional full-screen scrolling.
4. snapshot({})
5. Repeat with a changed target/search. Do not loop on the same query if the screen did not change.

Starting WebView / Chrome work from native:
1. For browser URL tasks, prefer activate_app({"app_id": "com.android.chrome"}) before page-level work when no WebView/Chrome context is known.
2. If the task gives a URL, goto({"url": "https://example.com"}) is allowed; appium-cli will switch to WebView/Chrome if one is available, and future prompt guidance will become WebView.
3. If goto fails with "No WebView context", do not retry immediately. Activate Chrome, webview_switch({}) if needed, then retry goto once.
4. If you need an existing WebView without navigating, call webview_switch({}) first.
5. If the known app package must be opened, activate_app({"app_id": "com.android.chrome"}), then observe or switch/navigate as needed.
6. If the app package is unknown, use list_apps({}) when shell capability is available, then activate_app({"app_id": "<package>"}).
7. Do not loop on launcher snapshots looking for app icons; launcher labels are often text-only and not actionable.
"""

WEBVIEW_TOOL_PROMPT = """Current appium-cli context guidance: WebView / Chrome

Use WebDriver/WebView commands for page-level work until native_switch() succeeds. Prefer click()/fill()/select()/select_option()/set_date() for web_* refs; do not use native tap/type_text for normal DOM work.

Open a URL and inspect the page:
1. goto({"url": "https://example.com"})
2. web_snapshot({})
3. webview_url({}) and webview_title({}) when you only need quick URL/title confirmation.
4. snapshot_search({"text": "target text"}) for text in the latest snapshot artifact.
5. snapshot_show({"ref": "<candidate ref>"}) when snapshot_search returns a likely ref.
6. Use snapshot_refs({"snapshot_id": "latest", "role": "button"}) or role="textbox" only when the expected list is small.
7. Use narrow web_query selectors only if snapshot refs are insufficient or you need href discovery for goto().

General recipe: collect N detail pages from a start page:
1. goto({"url": "<start url>"})
2. web_snapshot({})
3. Find the list/category/search page from the latest snapshot first:
   snapshot_search({"text": "<category keyword>", "snapshot_id": "latest"})
   snapshot_show({"ref": "<candidate ref>"})
4. If the latest snapshot contains a clear actionable ref, click({"ref": "<ref>"}), then web_snapshot({}).
5. If snapshot refs are ambiguous or no stable ref exists, use web_query() only to extract hrefs, then goto({"url": "<href>"}):
   web_query({"selector": "a[href*='<category keyword>'], a[href*='<category path>']", "attrs": "href,textContent,aria-label", "limit": 20})
6. On the list page, take web_snapshot({}) and identify item links from the latest snapshot:
   snapshot_search({"text": "<item/list keyword>", "snapshot_id": "latest"})
   snapshot_show({"ref": "<candidate ref>"})
7. If item hrefs are easier to extract by pattern, use web_query() as a fallback and navigate with goto():
   web_query({"selector": "a[href*='<detail path pattern>']", "attrs": "href,textContent,aria-label", "limit": 20})
8. Select exactly the first N unique detail refs or URLs. Track selected_urls/refs, visited_urls/refs, and completed_items in working_state.
9. Visit each selected detail exactly once:
   click({"ref": "<detail ref>"}) for refs from the latest snapshot, or goto({"url": "<detail url>"}) for hrefs.
   web_snapshot({"scope": "full", "depth": 3})
   Extract the requested title/body/details from that page.
10. Once N detail pages have been collected, stop browsing. Do not return to the list page, click extra links, or take deep snapshots unless a selected item failed extraction.
11. Final result must include the start URL, list/category/search URL, every detail page inspected, requested extracted data, and explicit checks for item count or character limits.

Examples of URL-pattern extraction:
- Category/list links: web_query({"selector": "a[href*='categories/sports'], a[href*='news'][href*='sports'], a[href*='sports']", "attrs": "href,textContent,aria-label", "limit": 20})
- Article/detail links: web_query({"selector": "a[href*='/articles/'], a[href*='/article/'], a[href*='/products/'], a[href*='/items/']", "attrs": "href,textContent,aria-label", "limit": 20})
- If the user asks for news, prefer news/category URLs (for example, paths containing categories or articles) over a separate sports portal URL that does not expose news detail links.

Important portal-search rule:
- Do not conclude that a link/category is absent from one broad query such as web_query({"selector": "a"}).
- Broad link lists may be long. If the task names a category, domain, keyword, path, or URL pattern, narrow the selector/search text and try again.
- Examples: web_query({"selector": "a[href*='login']"}), web_query({"selector": "a[href*='sports']"}), snapshot_search({"text": "ニュース"}).
- Avoid repeatedly reading large web_snapshot output directly. Keep web_snapshot as the ref source, then pull relevant fragments with snapshot_search(), snapshot_refs(), and snapshot_show().
- Do not use snapshot_refs(role="link") as the first step on large portal/list pages. It can return every link and waste tokens.

Click and read using refs:
1. goto({"url": "https://example.com"})
2. web_snapshot({})
3. snapshot_search({"snapshot_id": "latest", "text": "expected link text"})
4. snapshot_show({"snapshot_id": "latest", "ref": "web_<candidate ref>"})
5. click({"ref": "web_<candidate ref>"})
6. web_snapshot({})
7. snapshot_search({"text": "expected text"}) or assert_visible({"text": "expected text"})

Search or submit a simple form:
1. goto({"url": "https://example.com"})
2. web_snapshot({})
3. snapshot_refs({"snapshot_id": "latest", "role": "textbox"}) or web_query({"selector": "input,textarea,button", "attrs": "name,type,placeholder,aria-label", "limit": 30})
4. fill({"ref": "web_<search input ref>", "text": "query", "submit": true})
5. web_snapshot({})
6. snapshot_search({"text": "query"}) or web_query({"selector": "a,article,h1,h2,h3", "attrs": "href,textContent", "limit": 30})

Forms with suggestions, comboboxes, or React-controlled fields:
1. web_snapshot({})
2. fill({"ref": "web_<input ref>", "text": "partial text", "slowly": true})
3. web_snapshot({})
4. click({"ref": "web_<matching option ref>"}) or press_key({"key": "Escape"}) to dismiss an unneeded overlay.
5. Continue only after the transient UI is stable.
Never use web_eval to set input values; use fill so browser/framework input events fire.
For file inputs, use file_upload({"ref": "web_<file input ref>", "path": "/path/to/file"}) instead of typing a path manually.

- CSS selectors discovered by web_query are not refs unless passed as supported CSS selector strings such as "css:#submit", "css:.class", or "css:[name='q']".

Navigation and context rules:
- goto({"url": "https://..."}) navigates the current WebView/Chrome tab and auto-switches to WebView when possible.
- After goto or webview_switch succeeds, treat page-level work as WebView automation until native_switch().
- Use go_back(), go_forward(), reload(), tabs list/switch/new/close for browser navigation. Use tabs tools only when the task actually requires multiple tabs.
- Do not use web_eval to assign window.location/location.href/history state, and do not search for or tap the browser address bar just to load a URL.

Special read-only shortcut:
- web_form_url({"target": "form[name=search]"}) inspects a form's submit URL/payload without interacting. Use it only for information retrieval/debugging, not frontend behavior testing.
- If you use web_form_url output, state that frontend_interaction_skipped is true; never claim the form was actually exercised.
"""


def get_tool_skill_prompt() -> str:
    """Return reusable appium-cli tool usage guidance for tool-calling agents.

    The returned text is a composable prompt fragment, not a complete system
    prompt. Callers should combine it with their own role, memory, safety,
    output-format, and completion instructions.
    """
    context_prompt = WEBVIEW_TOOL_PROMPT if _prompt_context_mode == "webview" else NATIVE_TOOL_PROMPT
    return "\n\n".join([COMMON_TOOL_PROMPT, context_prompt])


def _reset_tool_skill_prompt_mode_for_tests() -> None:
    global _prompt_context_mode
    _prompt_context_mode = "native"


def _switch_context_target_mode(arguments: dict[str, Any] | None) -> PromptContextMode | None:
    if not arguments:
        return None
    raw = str(arguments.get("context") or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    if lowered in {"native", "native_app"}:
        return "native"
    if lowered in {"webview", "chromium"} or raw.startswith("WEBVIEW_"):
        return "webview"
    return None


def _update_tool_skill_prompt_mode(
    tool_name: str,
    arguments: dict[str, Any] | None,
    response: dict[str, Any],
) -> None:
    """Update prompt mode after persistent Appium context changes.

    Appium starts in the native context by convention, and appium-cli mirrors
    that with daemon ``state.current_context = "NATIVE_APP"``. The mode here is
    intentionally updated only for tool calls that persistently change the
    driver context. In appium-cli source, ``webview_switch``/``native_switch``
    call ``driver.switch_to.context(...)`` directly. Web navigation commands
    such as ``goto`` call ``_require_web_driver()``, which auto-switches to the
    first WebView/CHROMIUM context and does not restore the old context.

    By contrast, ``web_snapshot`` is implemented as ``snapshot(context="webview")``
    with ``restore_context=True`` via ``using_context(...)``. It observes a
    WebView temporarily, then restores the original context, so it must not
    switch the prompt mode.
    """

    if not response.get("ok"):
        return

    global _prompt_context_mode
    if tool_name == "native_switch":
        _prompt_context_mode = "native"
        return
    if tool_name == "webview_switch":
        _prompt_context_mode = "webview"
        return
    if tool_name == "switch_context":
        mode = _switch_context_target_mode(arguments)
        if mode is not None:
            _prompt_context_mode = mode
        return
    if tool_name in {"goto", "go_back", "go_forward", "reload", "tabs"}:
        _prompt_context_mode = "webview"


def _tool_to_openai_schema(tool_def: ToolDef) -> dict[str, Any]:
    """Convert a ToolDef to OpenAI Chat Completions tool format."""
    return {
        "type": "function",
        "function": {
            "name": tool_def.name,
            "description": tool_def.description,
            "parameters": tool_def.parameters,
        },
    }


def get_openai_tools() -> list[dict[str, Any]]:
    """Return all tools as OpenAI Chat Completions tool definitions.

    Each entry has the shape::

        {
            "type": "function",
            "function": {
                "name": "snapshot",
                "description": "...",
                "parameters": { "type": "object", "properties": {...}, ... }
            }
        }
    """
    return [_tool_to_openai_schema(t) for t in list_tools()]


def get_openai_tool(name: str) -> dict[str, Any] | None:
    """Return a single tool definition by name, or None if not found."""
    tool_def = get_tool(name)
    if tool_def is None:
        return None
    return _tool_to_openai_schema(tool_def)


def call_tool(name: str, arguments: dict[str, Any] | str | None = None) -> dict[str, Any]:
    """Execute a tool call through the session daemon.

    Args:
        name: Canonical tool name (e.g. "snapshot", "scroll_down").
        arguments: Tool arguments as a dict or JSON string (OpenAI returns
                   arguments as a JSON string in tool_calls).

    Returns:
        Daemon response dict with keys: ok, text, data, and optionally
        error/exit_code on failure.
    """
    # Parse JSON string arguments (OpenAI returns them as strings)
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except (json.JSONDecodeError, ValueError):
            return {
                "ok": False,
                "error": f"Invalid JSON arguments: {arguments!r}",
                "exit_code": exit_codes.GENERAL_ERROR,
            }

    # Resolve tool name and merge directional alias args
    try:
        daemon_tool, merged_args = normalize_tool_call(name, arguments)
    except KeyError:
        return {
            "ok": False,
            "error": f"Unknown tool: {name}",
            "exit_code": exit_codes.GENERAL_ERROR,
        }

    # Call the daemon with raw=True so snapshot tools return the full tree
    # content instead of just artifact file paths (metadata-only mode is for
    # human CLI usage; programmatic callers need the tree text).
    try:
        response = request(daemon_tool, args=merged_args if merged_args else None, raw=True)
    except (FileNotFoundError, ConnectionError, OSError) as exc:
        return {
            "ok": False,
            "error": "Session daemon is not running",
            "detail": str(exc),
            "exit_code": exit_codes.STOPPED,
        }

    _update_tool_skill_prompt_mode(daemon_tool, merged_args, response)
    return response
