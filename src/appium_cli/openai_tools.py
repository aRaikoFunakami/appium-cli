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
2. Extract targeted candidates with snapshot_actionable_tree() (native), web_refs() (WebView), snapshot_search(), snapshot_show(ref=...), or context-appropriate query tools. Use web_text() when the task requires reading/summarizing page text.
3. Act with refs/selectors using the context-appropriate action tools.
4. Observe again after navigation, reload, scroll, click, fill+submit, dialog handling, or any action that may change the page.
5. Use only refs from the latest observation/artifacts. Old refs can become stale.

Targeting rules:
- Snapshot refs are valid function-call arguments.
- Normal snapshot outputs are metadata plus artifact paths, not full trees. Do not use raw/full snapshot output in agent loops; inspect saved artifacts with snapshot_search(), snapshot_show({"ref": "..."}), and paginated web_refs() (WebView only). For article/body/page text, use web_text().
- If a stale ref is used, appium-cli may refresh the affected context and retry the action once. If the ref disappeared, choose a new ref from the fresh snapshot metadata returned by the tool.
- web_refs() is paginated by default (limit=50). If has_more=true and the target is not listed, refine the role/search if possible or call web_refs(offset=next_offset).
- If duplicate labels/refs appear in native UI, inspect with snapshot_actionable_tree() before acting. Use snapshot_show({"ref": "..."}), list_containers(), or within_container() as follow-up detail tools.
- If visible text has no ref, target the nearest actionable parent row, button, link, container, or form control. For native snapshots, snapshot_search() may return tap_target_ref/action_target_ref for this exact purpose.
- Use any_text for synonym/translation/variant labels (e.g. snapshot_search({"text": "ログイン", "any_text": ["Login", "Sign in"]})). Keep to 2-4 variants. Do not invent regex or AND syntax.

Diagnostics and fallback order:
1. If context/prerequisite behavior is unclear, call get_context({}), list_contexts({}), webview_status({}), or get_driver_status({}).
2. If snapshot artifacts are insufficient, try targeted snapshot_search(), web_refs() (WebView), web_text(), or snapshot_show({"ref": "..."}).
3. Use console_messages() for browser console logs; returned entries may be consumed by the call.
4. Use network_requests() only when the session was started with network logging enabled.
5. Use screenshot() only when visual pixels are necessary.
6. Use get_page_source() only as a token-heavy diagnostic escape hatch after targeted tools are insufficient.
7. Diagnostics such as doctor, devices, get_device_info, webview_status, console_messages, and network_requests observe state; they do not install or fix prerequisites.

Verification and completion:
- Before finishing, verify the current page/state with snapshot(), web_snapshot(), targeted query/search/ref tools, screenshot(), get_page_source(), or assert_visible().
- If the goal asks for N items, collect and report all N items. Partial results are not success.
- If data cannot be obtained, report what was tried and what is missing.
- Use wait_for() for asynchronous conditions: text appears, text disappears, or a ref becomes visible. Avoid wait_short_loading in normal workflows.

Responsibility boundary:
- Tool calls require an active appium-cli session. When the caller owns lifecycle, use one fresh session per user task and stop it at task end; stale sessions can cause InvalidSessionIdException.
- If refs/session state appear stale or the daemon loses WebDriver state, recover with session status, session stop, session start, then snapshot.
- Do not call adb, appium, npm, or installer commands directly from an appium-cli tool-calling agent unless the user explicitly asked for prerequisite management outside appium-cli.
- Do not use depth for normal full-page observations. Snapshots are saved as artifacts, so preserve the full tree and reduce tokens with snapshot_search(), snapshot_show({"ref": "..."}), and paginated web_refs() (WebView) instead.
- Use depth only for scoped/debug snapshots when you intentionally want a smaller subtree.
"""

NATIVE_TOOL_PROMPT = """Current appium-cli context guidance: NATIVE_APP

Use native accessibility snapshots and native/mobile actions. Do not use WebView DOM tools until a WebView context switch/navigation succeeds.

Native UI: observe, understand operable hierarchy, act:
1. snapshot({})
2. snapshot_actionable_tree({}) for tabs, menus, lists, duplicate labels, or ambiguous regions
3. tap({"ref": "<ref selected from the actionable hierarchy>"}) or snapshot_search({"text": "<visible label>"}) for targeted lookup after structure is understood
4. snapshot({})
5. snapshot_search({"text": "expected text"}) or assert_visible({"text": "expected text"})
6. For multilingual/variant labels: snapshot_search({"text": "ログイン", "any_text": ["Login", "Sign in"]})

Native targeting rules:
- Do NOT default to role="button" in native UI. Tappable native targets are often rows, tabs, layouts, or containers with child text labels.
- Use role filters for specific element types such as textbox/list, or when the user explicitly asks for that role.
- If snapshot_search returns tap_target_ref/action_target_ref, use it only when the target is unambiguous in snapshot_actionable_tree. When the same label appears in multiple containers (for example main tabs and sub-tabs), choose the ref from snapshot_actionable_tree by parent region.
- If persisted artifacts are unavailable or stale, find_by_text can locate the visible label in the current native snapshot.
- Do not tap unlabeled refs such as generic buttons unless nearby text/snippet confirms the target.

Native UI: enter text:
1. snapshot({})
2. snapshot_actionable_tree({}) to find textbox refs in the operable hierarchy
3. type_text({"ref": "<input ref>", "text": "value", "submit": false})
4. snapshot({})

Native UI: scrolling and lists:
1. snapshot({})
2. list_containers({}) to find scrollable/list refs.
3. scroll_down({"ref": "<container ref>"}) to scroll inside a list; scroll_down({}) only for intentional full-screen scrolling.
4. snapshot({}) before the next ref-based action is recommended. If omitted, appium-cli will reject stale refs or auto-refresh/retry once; if the old ref disappeared, use the returned fresh snapshot to choose a new ref.
5. snapshot_actionable_tree({}) only renders the last snapshot; it does NOT refresh the device state. Call snapshot({}) first when you need a guaranteed fresh tree.
6. Repeat with a changed target/search. Do not loop on the same query if the screen did not change.

Starting WebView / Chrome work from native:
1. If the task gives a URL, goto({"url": "https://example.com"}) is allowed; appium-cli will switch to WebView/Chrome if one is available, and future prompt guidance will become WebView.
2. If you need an existing WebView without navigating, call webview_switch({}) first.
3. If the known app package must be opened, activate_app({"app_id": "com.android.chrome"}), then observe or switch/navigate as needed.
4. If the app package is unknown, use list_apps({}) when shell capability is available, then activate_app({"app_id": "<package>"}).
5. Do not loop on launcher snapshots looking for app icons; launcher labels are often text-only and not actionable.
"""

WEBVIEW_TOOL_PROMPT = """Current appium-cli context guidance: WebView / Chrome

Use WebDriver/WebView commands for page-level work until native_switch() succeeds. Prefer click()/fill()/select()/select_option()/set_date() for web_* refs; do not use native tap/type_text for normal DOM work.

Open a URL and inspect the page:
1. goto({"url": "https://example.com"})
2. web_snapshot({})
3. webview_url({}) and webview_title({}) when you only need quick URL/title confirmation.
4. snapshot_search({"text": "target text"}) for text in the latest snapshot artifact.
5. web_refs({"snapshot_id": "latest", "role": "link"}) or web_query({"selector": "a", "attrs": "href,textContent,aria-label", "limit": 50}) for links.

Find a category or news page from a portal:
1. goto({"url": "https://www.yahoo.co.jp/"})
2. web_snapshot({})
3. snapshot_search({"text": "スポーツ"})
4. web_query({"selector": "a[href*='sports'], a[href*='news.yahoo.co.jp/categories/sports']", "attrs": "href,textContent,aria-label", "limit": 20})
5. If the target URL is clear, prefer goto({"url": "https://news.yahoo.co.jp/categories/sports"}) over clicking an ambiguous duplicate link.
6. web_snapshot({})
7. web_query({"selector": "a[href*='/articles/']", "attrs": "href,textContent", "limit": 10})
8. Open each needed article with goto({"url": "<article url>"}), then web_text({}) to read article/body text for summarization. Use web_snapshot({}) only when you need refs/navigation targets.

Important portal-search rule:
- Do not conclude that a link/category is absent from one broad query such as web_query({"selector": "a"}).
- Broad link lists may be long. If the task names a category, domain, keyword, path, or URL pattern, narrow the selector/search text and try again.
- Examples: web_query({"selector": "a[href*='login']"}), web_query({"selector": "a[href*='sports']"}), snapshot_search({"text": "ニュース"}).
- For text variants across languages: snapshot_search({"text": "Search", "any_text": ["検索"]}).

Click and read using refs:
1. goto({"url": "https://example.com"})
2. web_snapshot({})
3. web_refs({"snapshot_id": "latest", "role": "link"})
4. click({"ref": "web_<ref>"})
5. web_snapshot({})
6. snapshot_search({"text": "expected text"}) or assert_visible({"text": "expected text"})

Search or submit a simple single-input form:
1. goto({"url": "https://example.com"})
2. web_snapshot({})
3. web_refs({"snapshot_id": "latest", "role": "textbox"}) or web_query({"selector": "input,textarea,button", "attrs": "name,type,placeholder,aria-label", "limit": 30})
4. fill({"ref": "web_<search input ref>", "text": "query", "submit": true})
5. web_snapshot({})
6. snapshot_search({"text": "query"}) or web_query({"selector": "a,article,h1,h2,h3", "attrs": "href,textContent", "limit": 30})

Multi-field station/address/location forms:
1. web_snapshot({})
2. web_refs({"snapshot_id": "latest", "role": "textbox"})
3. fill({"ref": "web_<first input ref>", "text": "first value", "submit": false})
4. press_key({"key": "escape"}) to close any autocomplete/dropdown before the next field.
5. web_snapshot({})
6. Repeat fill -> press_key(escape) -> web_snapshot for each station/address/location field.
7. Before clicking checkboxes/buttons after field entry, press_key({"key": "escape"}) once more if any autocomplete may still be open.

Forms where a visible suggestion/option must be selected:
1. web_snapshot({})
2. fill({"ref": "web_<input ref>", "text": "partial text", "slowly": true})
3. web_snapshot({})
4. click({"ref": "web_<matching option ref>"}) or press_key({"key": "escape"}) to dismiss an unneeded overlay.
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

DOM extraction with web_eval (Playwright browser_evaluate equivalent):
- Use web_eval when you need ordered, structured, or computed data from the DOM that snapshot_search/web_query cannot provide directly.
- web_eval({"script": "return Array.from(document.querySelectorAll('a[href*=\"/articles/\"]')).map(a=>({title:a.innerText.trim(),url:a.href})).filter(x=>x.title).slice(0,5)"})
- web_eval({"script": "return (document.querySelector('article')||document.querySelector('main')||document.body).innerText"})
- web_eval returns JSON for arrays/objects; use it for article link lists, table data, heading structures, computed attributes, etc.
- Do not use web_eval for navigation (window.location), form value mutation (.value=), or synthetic events.
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

    # Keep normal daemon output by default. Snapshot tools return metadata plus
    # artifact paths; callers should use targeted artifact tools instead of
    # pushing full trees into the model context.
    try:
        response = request(daemon_tool, args=merged_args if merged_args else None, raw=False)
    except (FileNotFoundError, ConnectionError, OSError) as exc:
        return {
            "ok": False,
            "error": "Session daemon is not running",
            "detail": str(exc),
            "exit_code": exit_codes.STOPPED,
        }

    _update_tool_skill_prompt_mode(daemon_tool, merged_args, response)
    return response
