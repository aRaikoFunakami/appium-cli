# OpenAI tools integration

This guide explains how to build a Python LLM agent that uses
`appium-cli` tools through `appium_cli.openai_tools`, without shelling out
for every tool call.

`appium_cli.openai_tools` is a small adapter layer. It does **not** import the
OpenAI SDK and it does **not** run an LLM. Your agent owns the model loop,
memory, safety policy, and result handling. The adapter provides tool schemas,
a reusable tool-usage prompt fragment, and dispatches tool calls to the
`appium-cli` session daemon.

## 1. Architecture

There are two integration styles:

| Integration style | Typical caller | How tools run |
|---|---|---|
| CLI | GitHub Copilot CLI, Claude Code, shell agents | `appium-cli snapshot`, `appium-cli tap btn_login`, pipes, `grep`, `jq`, files |
| Python API | Custom Python LLM agents | `get_tool_skill_prompt()` + `get_openai_tools()` + `call_tool(name, args)` |

The Python API path looks like this:

```text
Your agent
  |-- OpenAI SDK or another LLM client
  |-- get_tool_skill_prompt() -> appium-cli tool usage guidance in your prompt
  |-- get_openai_tools() -> tool schemas sent to the model
  |-- model returns a function/tool call
  `-- call_tool(name, arguments)
       |
       v Unix socket JSON-RPC, raw=True
     appium-cli session daemon
       |
       v Appium WebDriver
     Android/iOS device
```

`call_tool()` still requires an active `appium-cli` session daemon. Start one
before the model loop and stop it after the task.

## 2. Prerequisites

The latest source is available at
<https://github.com/aRaikoFunakami/appium-cli.git>.

### Developing inside this repository

When you are working inside the `appium-cli` repository itself, install the
current checkout as an editable CLI tool:

```bash
uv tool install --editable . --force
appium-cli --version
```

This is mainly for appium-cli development. It is not the usual setup for a
separate agent project.

### Using appium-cli from another Python project

For a new agent project, clone the latest `appium-cli` source next to your
agent project and add it as an editable dependency:

```bash
# From your agent project directory.
git clone https://github.com/aRaikoFunakami/appium-cli.git ../appium-cli
uv add --editable ../appium-cli
uv add openai
```

Your agent can then import the Python API:

```python
from appium_cli.openai_tools import call_tool, get_openai_tools, get_tool_skill_prompt
```

If you are not using `uv`, use the equivalent editable install in your virtual
environment:

```bash
python -m pip install -e ../appium-cli
python -m pip install openai
```

Before writing agent code, verify the host and device state:

```bash
appium-cli doctor
appium-cli devices --json
appium-cli server status
```

Start the session daemon before using `call_tool()`:

```bash
appium-cli session start
```

If Appium runs outside the agent process or container, pass the external URL:

```bash
appium-cli session start --server-url http://host.docker.internal:4723
```

For task-scoped agents, prefer one fresh session per task:

```bash
appium-cli session stop
appium-cli session start
# run one agent task
appium-cli session stop
```

The OpenAI SDK is intentionally not a dependency of `appium_cli.openai_tools`.
Install and configure the LLM client in your own agent package:

```bash
uv add openai
export OPENAI_API_KEY=...
```

## 3. Core API

Import the adapter:

```python
from appium_cli.openai_tools import (
    call_tool,
    get_openai_tool,
    get_openai_tools,
    get_tool_skill_prompt,
)
```

### `get_openai_tools()`

```python
def get_openai_tools() -> list[dict[str, object]]
```

Returns Chat Completions-style function tool schemas:

```python
{
    "type": "function",
    "function": {
        "name": "snapshot",
        "description": "...",
        "parameters": {
            "type": "object",
            "properties": {...},
            "required": [...],
        },
    },
}
```

Use these schemas directly with Chat Completions. For the Responses API, convert
them as shown in [Responses API example](#7-responses-api-example).

### `get_openai_tool(name)`

```python
def get_openai_tool(name: str) -> dict[str, object] | None
```

Returns a single tool schema or `None` if the name is unknown.

### `get_tool_skill_prompt()`

```python
def get_tool_skill_prompt() -> str
```

Returns the current reusable `appium-cli` tool usage prompt fragment for
tool-calling agents. The fragment is dynamic: `call_tool()` updates the prompt
mode after persistent Appium context changes such as `webview_switch`, `goto`,
and `native_switch`, so callers should fetch it for every model call rather
than cache it once.

It is **not** a complete system prompt. Compose it with your own agent-specific
role, memory, safety, output-format, and completion instructions:

```python
from appium_cli.openai_tools import get_tool_skill_prompt


AGENT_RULES = """
You are a mobile task agent.
Use exactly one appium-cli tool call when an action or observation is needed.
After tool results, update working_state and either continue or return the
requested final answer.
"""

def build_system_prompt() -> str:
    return "\n\n".join([get_tool_skill_prompt(), AGENT_RULES])
```

### `call_tool(name, arguments)`

```python
def call_tool(
    name: str,
    arguments: dict[str, object] | str | None = None,
) -> dict[str, object]
```

Executes one appium-cli tool through the session daemon. `arguments` may be a
Python dict or the JSON argument string returned by OpenAI tool calls.

The response is a dict with this shape:

```python
{
    "ok": True,
    "text": "...",        # primary tool result, usually a string
    "data": {...},        # optional structured metadata
}
```

On failure:

```python
{
    "ok": False,
    "error": "...",
    "detail": "...",      # optional
    "exit_code": 3,
}
```

Built-in adapter errors include:

| Case | Response |
|---|---|
| Invalid JSON argument string | `{"ok": false, "error": "Invalid JSON arguments: ...", "exit_code": 1}` |
| Unknown tool name | `{"ok": false, "error": "Unknown tool: <name>", "exit_code": 1}` |
| Session daemon unavailable | `{"ok": false, "error": "Session daemon is not running", "detail": "...", "exit_code": 3}` |

`call_tool()` calls the daemon with `raw=True`, so programmatic callers receive
the full tool text instead of the human CLI's artifact-only metadata mode.

## 4. Session lifecycle from Python

You can start and stop the session daemon with a subprocess wrapper. This is
the same pattern used by `agent-browser` for lifecycle management.

```python
import asyncio
import json
import shutil


async def run_appium_cli(*args: str, timeout: float = 60.0) -> dict:
    binary = shutil.which("appium-cli") or "appium-cli"
    proc = await asyncio.create_subprocess_exec(
        binary,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    stdout = stdout_b.decode("utf-8", errors="replace").strip()
    stderr = stderr_b.decode("utf-8", errors="replace").strip()
    if proc.returncode:
        raise RuntimeError(f"appium-cli {' '.join(args)} failed: {stderr or stdout}")
    return json.loads(stdout) if stdout else {}


async def start_session(port: int = 4723) -> dict:
    return await run_appium_cli("session", "start", "--json", "--port", str(port), timeout=120.0)


async def stop_session() -> None:
    await run_appium_cli("session", "stop", "--json", timeout=30.0)
```

`agent-browser/src/agent_browser/session.py` contains a more complete
`AppiumSessionManager` that:

- checks `session status --json`
- stops an existing session for a fresh task
- starts `session start --json --port <port> [--udid <udid>]`
- stops the session on context-manager exit

## 5. LLM prompting guide

The CLI integration uses `skills/appium-cli/SKILL.md` to teach shell-based
agents how to operate `appium-cli`. A Python agent should use
`get_tool_skill_prompt()` for the same shared tool guidance, then append its
own agent-specific instructions. Fetch the fragment on every model call so the
Native/WebView section follows the current appium-cli context mode.

Recommended composition:

```python
from appium_cli.openai_tools import get_tool_skill_prompt


AGENT_RULES = """
You are a mobile automation agent using appium-cli tools through Python
function calls.

Use exactly one appium-cli tool call when an action or observation is needed.
Keep working_state short: current page, filled values, pending fields,
validation requirements, and recent failures only.

Safety rules:
- Do not type passwords, payment data, personal data, or submit final purchase,
  booking, login, or account-change forms unless your application has its own
  approval mechanism.
- Never log credentials or screenshot base64.

Completion rules:
- Set success=true only after the requested outcome is verified.
- If the requested data cannot be obtained, return success=false and explain
  what is missing.
"""

def build_system_prompt() -> str:
    # Fetch every turn so Native/WebView guidance follows appium-cli context.
    return "\n\n".join([get_tool_skill_prompt(), AGENT_RULES])
```

For Responses API agents, `agent-browser` also uses a structured per-turn user
message. This pattern keeps prompt history compact and avoids replaying old
snapshots:

```text
<task>
Goal: ...
Phase: ...
</task>

<working_state>
Current page, completed fields, pending fields, validation constraints,
and recent failures.
</working_state>

<current_screen>
The latest observation, usually the first relevant lines of snapshot or
web_snapshot output.
</current_screen>

<recent_steps>
Short records of the last few tool calls and outcomes.
</recent_steps>

<blocked_tools>
Tools that reached retry limits, if any.
</blocked_tools>

<reflection>
Verifier feedback or loop warning, if any.
</reflection>

<next_action_rule>
Choose exactly one appium-cli tool call that advances the goal, or finish.
</next_action_rule>
```

Recommended model-loop settings:

- set `tool_choice="auto"`
- set `parallel_tool_calls=False`
- execute returned tool calls in order defensively
- keep only current operation state, not unbounded raw history

## 6. Minimal Chat Completions example

This example shows a basic loop. It assumes `appium-cli session start` already
ran successfully.

```python
import json
from openai import OpenAI

from appium_cli.openai_tools import call_tool, get_openai_tools, get_tool_skill_prompt


AGENT_RULES = """
You are a mobile automation agent using appium-cli tools.
Use exactly one tool call when an action or observation is needed.
Keep working_state short and verify the requested outcome before final answer.
When the goal is satisfied, answer with the requested result.
"""

def build_system_prompt() -> str:
    return "\n\n".join([get_tool_skill_prompt(), AGENT_RULES])


def run_task(goal: str, model: str = "gpt-4o") -> str:
    client = OpenAI()
    tools = get_openai_tools()
    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": goal},
    ]

    for _ in range(30):
        messages[0] = {"role": "system", "content": build_system_prompt()}
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            parallel_tool_calls=False,
        )
        message = response.choices[0].message

        if not message.tool_calls:
            return message.content or ""

        messages.append(message)
        for tool_call in message.tool_calls:
            result = call_tool(
                tool_call.function.name,
                tool_call.function.arguments,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    raise RuntimeError("Task did not finish before max turns")
```

For production, do not pass every raw result through unchanged. Add the result
handling rules in [Tool result handling](#9-tool-result-handling).

If you copied the session helpers from [Session lifecycle from Python](#4-session-lifecycle-from-python),
wrap the task in a fresh session:

```python
import asyncio
import sys


async def main() -> None:
    await run_appium_cli("session", "stop", "--json", timeout=30.0)
    await start_session()
    try:
        print(run_task(sys.argv[1]))
    finally:
        await stop_session()


if __name__ == "__main__":
    asyncio.run(main())
```

## 7. Responses API example

`get_openai_tools()` returns Chat Completions-style schemas. Convert them before
passing them to `client.responses.create()`.

```python
import asyncio
import json
from copy import deepcopy
from typing import Any

from openai import AsyncOpenAI

from appium_cli.openai_tools import call_tool, get_openai_tools, get_tool_skill_prompt


AGENT_RULES = """
You are a mobile automation agent using appium-cli tools.
Use exactly one tool call when an action or observation is needed.
Keep working_state short and verify the requested outcome before final answer.
When the goal is satisfied, answer with the requested result.
"""

def build_system_prompt() -> str:
    return "\n\n".join([get_tool_skill_prompt(), AGENT_RULES])


def response_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    func = schema["function"]
    parameters = deepcopy(func.get("parameters") or {"type": "object", "properties": {}})
    if parameters.get("type") == "object":
        parameters.setdefault("additionalProperties", False)
    return {
        "type": "function",
        "name": func["name"],
        "description": func.get("description", ""),
        "parameters": parameters,
    }


def function_calls(response: Any) -> list[dict[str, Any]]:
    calls = []
    for item in getattr(response, "output", []) or []:
        payload = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
        if isinstance(payload, dict) and payload.get("type") == "function_call":
            calls.append(payload)
    return calls


async def run_responses_task(goal: str, model: str = "gpt-4o") -> str:
    client = AsyncOpenAI()
    tools = [response_tool_schema(t) for t in get_openai_tools()]
    input_items: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "input_text", "text": goal}]}
    ]

    for _ in range(30):
        response = await client.responses.create(
            model=model,
            instructions=build_system_prompt(),
            input=input_items,
            tools=tools,
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
        )

        calls = function_calls(response)
        if not calls:
            return getattr(response, "output_text", "") or ""

        output_items = []
        for call in calls:
            result = await asyncio.to_thread(
                call_tool,
                str(call["name"]),
                call.get("arguments"),
            )
            output_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.get("call_id"),
                    "output": json.dumps(result, ensure_ascii=False),
                }
            )

        previous_items = [
            item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else item
            for item in getattr(response, "output", []) or []
        ]
        input_items = input_items + previous_items + output_items

    raise RuntimeError("Task did not finish before max turns")
```

`agent-browser` uses the same conversion pattern in
`agent-browser/src/agent_browser/agent/registry.py`.

## 8. Tool catalog

The tool registry is the source of truth for schemas and aliases:
`src/appium_cli/tool_registry.py`.

### Observation

- `snapshot`
- `web_snapshot`
- `snapshot_show`
- `snapshot_search`
- `snapshot_refs`
- `generate_locator`
- `web_query`
- `web_form_url`
- `describe`
- `find_by_text`
- `screenshot`
- `get_page_source`
- `webview_url`
- `webview_title`
- `console_messages`
- `network_requests`

### Actions and gestures

- `tap`
- `click` (alias for `tap`)
- `type_text`
- `fill` (alias for `type_text`)
- `select`
- `select_option`
- `set_date`
- `file_upload`
- `wait_for`
- `scroll`
- `scroll_up`
- `scroll_down`
- `scroll_left`
- `scroll_right`
- `swipe`
- `swipe_up`
- `swipe_down`
- `swipe_left`
- `swipe_right`
- `press_key`
- `wait`
- `long_press`
- `double_tap`
- `drag`
- `fling`
- `fling_up`
- `fling_down`
- `fling_left`
- `fling_right`
- `pinch_open`
- `pinch_close`
- `web_eval`

### Containers

- `list_containers`
- `find_container`
- `within_container`

### App management

- `get_current_app`
- `activate_app`
- `terminate_app`
- `list_apps`
- `restart_app`

### Device info

- `get_device_info`
- `is_locked`
- `get_orientation`
- `set_orientation`

### Contexts and WebView

- `list_contexts`
- `get_context`
- `switch_context`
- `native_switch`
- `webview_switch`
- `webview_status`
- `goto`
- `go_back`
- `go_forward`
- `reload`
- `tabs`

### Web dialogs

- `dialog_accept`
- `dialog_dismiss`
- `dialog_text`

### Verification and legacy locator tools

- `assert_visible`
- `find_element`
- `click_element`
- `get_text`
- `press_keycode`
- `send_keys`
- `wait_short_loading`
- `scroll_element`
- `scroll_to_element`

Directional aliases such as `scroll_down`, `swipe_left`, and `fling_up` map to
their base daemon tools with injected direction arguments. Prefer canonical
snake_case tool names in prompts and examples.

## 9. Tool result handling

Raw `call_tool()` responses are correct, but production agents should normalize
them before feeding results back to the model.

Copy this serializer into a new agent and use its return value as the tool
message/function output:

```python
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ACTION_TOOLS = {
    "tap", "click", "fill", "type_text", "scroll", "scroll_up",
    "scroll_down", "scroll_left", "scroll_right", "swipe", "swipe_up",
    "swipe_down", "swipe_left", "swipe_right", "long_press", "double_tap",
    "drag", "fling", "fling_up", "fling_down", "fling_left", "fling_right",
    "pinch_open", "pinch_close", "press_key", "press_keycode", "select",
    "send_keys", "scroll_element", "scroll_to_element", "click_element",
    "activate_app", "set_orientation", "clear", "reload", "go_back",
    "go_forward",
}
SNAPSHOT_TOOLS = {"snapshot", "web_snapshot"}
METADATA_KEEP = {"snapshot_id", "source", "screen_id", "context", "can_scroll_more"}


def truncate_text(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit - 200]
    return head + f"\n\n... [truncated {len(text) - len(head)} chars]"


def compact_action_metadata(text: str) -> str:
    prefix_lines: list[str] = []
    meta_lines: list[str] = []
    in_meta = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_meta and stripped.startswith("snapshot_id:"):
            in_meta = True
        if in_meta:
            key = stripped.split(":", 1)[0] if ":" in stripped else ""
            if key in METADATA_KEEP:
                meta_lines.append(stripped)
        else:
            prefix_lines.append(line)
    result = "\n".join(prefix_lines).rstrip()
    if meta_lines:
        result += "\n" + "\n".join(meta_lines)
    return result if result.strip() else "OK"


def save_screenshot_artifact(text: str, artifacts_dir: Path) -> str | None:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("type") != "screenshot":
        return None
    image_base64 = payload.get("image_base64")
    if not isinstance(image_base64, str) or not image_base64:
        return None
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(image_base64, validate=False)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
    region = str(payload.get("region", "full")).replace("/", "_").replace(":", "_")
    path = artifacts_dir / f"screenshot_{timestamp}_{region}.png"
    path.write_bytes(raw)
    return str(path)


def serialize_tool_response(
    name: str,
    response: dict[str, Any],
    *,
    artifacts_dir: Path = Path("artifacts"),
    max_result_chars: int = 12000,
    max_snapshot_show_chars: int = 1500,
) -> str:
    if not response.get("ok"):
        error = response.get("error") or "tool failed"
        detail = response.get("detail")
        return f"ERROR: {error}" + (f" ({detail})" if detail else "")

    text = str(response.get("text") or "")
    if not text and response.get("data") is not None:
        text = json.dumps(response["data"], ensure_ascii=False)
    if not text:
        return "OK"

    if name == "screenshot":
        artifact_path = save_screenshot_artifact(text, artifacts_dir)
        if artifact_path:
            region = "full"
            try:
                region = json.loads(text).get("region", "full")
            except json.JSONDecodeError:
                pass
            return json.dumps(
                {"type": "screenshot", "artifact_path": artifact_path, "region": region},
                ensure_ascii=False,
            )

    if name in ACTION_TOOLS:
        return compact_action_metadata(text)
    if name == "snapshot_show" and len(text) > max_snapshot_show_chars:
        head = text[: max_snapshot_show_chars - 100]
        return (
            head
            + f"\n\n... [truncated {len(text) - len(head)} chars. "
            "Use snapshot_search(text=...) or snapshot_refs(role=...) for targeted extraction.]"
        )
    if name in SNAPSHOT_TOOLS:
        return text
    return truncate_text(text, max_result_chars)
```

In a tool loop, call it immediately after `call_tool()`:

```python
response = call_tool(name, arguments)
tool_output = serialize_tool_response(name, response)
```

### General response handling

Use `response["ok"]` as the primary status flag. Also treat a successful text
result starting with `FAILED` as a failure, because some smartestiroid-compatible
tools return failure-shaped text.

```python
def is_tool_ok(response: dict) -> bool:
    text = str(response.get("text") or "")
    return bool(response.get("ok")) and not text.lstrip().startswith("FAILED")
```

If `text` is empty and `data` exists, serialize `data` as compact JSON for the
model.

### Snapshots

`snapshot` and `web_snapshot` return tree text. The tree contains refs that can
be used by later actions:

```text
- button "Log in" [ref=btn_login]
- textbox "Email" [ref=input_email]
```

Useful rules:

- Keep the latest snapshot as the current screen.
- Use only refs from the latest snapshot or web_snapshot.
- After a new snapshot, old refs are stale.
- For large trees, send only the first relevant lines to the next prompt and
  rely on `snapshot_search`, `snapshot_refs`, `snapshot_show`, or `web_query`
  for targeted extraction.

`agent-browser` stores the first 80 lines of snapshot output as its observation
summary and preserves fuller results only when needed.

### Actions

Actions often return success text plus post-action metadata. For model context,
keep only fields that help the next decision:

- `snapshot_id`
- `source`
- `screen_id`
- `context`
- `can_scroll_more`

### Screenshots

`screenshot` returns a JSON string:

```json
{"type":"screenshot","image_base64":"...","region":"full"}
```

Do not send large base64 strings back to the model. Decode and save them as
files, then return a compact reference:

```json
{"type":"screenshot","artifact_path":"artifacts/screenshot_001.png","region":"full"}
```

### Truncation

A practical default is:

- successful non-snapshot tool result: 12,000 characters
- errors: keep the beginning and end if truncated
- `snapshot_show`: truncate and explicitly tell the model to use
  `snapshot_search` or `snapshot_refs` for targeted extraction
- `working_state`: keep under a few thousand characters

## 10. Async use

`call_tool()` is synchronous. In an async model loop, run it in a worker thread:

```python
result = await asyncio.to_thread(call_tool, name, args)
```

Do not assume parallel tool execution improves reliability. The session daemon
represents a single WebDriver session, and UI state changes are sequential. For
LLM agents, `parallel_tool_calls=False` is recommended.

## 11. Production checklist

`agent-browser` adds these production features on top of raw `call_tool()`:

- fresh session lifecycle per task
- typed config loaded from environment
- shared tool guidance from `get_tool_skill_prompt()`
- agent-specific system prompt rules and per-turn compact context
- Chat-to-Responses tool schema conversion
- one tool call per action
- safety classification and approval blocking
- full successful tool output forwarding to the next model turn
- screenshot artifact extraction
- observation extraction into current screen state
- retry counters and tool blocking after repeated failures
- loop detection and wall-time/no-progress limits
- structural completion verification
- optional LLM judge
- JSONL episodic memory
- token usage and cost tracking

Use the raw adapter for minimal agents. Copy these patterns when building a
long-running or production-facing agent.

## 12. Reference implementation

`agent-browser` is the reference implementation for a full Python agent that
uses `appium_cli.openai_tools`:

| File | What to copy or study |
|---|---|
| `agent-browser/src/agent_browser/session.py` | task-scoped session lifecycle around `appium-cli session ...` |
| `agent-browser/src/agent_browser/appium_tools.py` | `call_tool()` dispatch, safety checks, screenshot artifact handling, observation extraction |
| `agent-browser/src/agent_browser/agent/registry.py` | Chat Completions schema to Responses API schema conversion |
| `agent-browser/src/agent_browser/agent/prompt.py` | `get_tool_skill_prompt()` plus browser-specific rules, and per-turn context format |
| `agent-browser/src/agent_browser/agent/loop.py` | ReAct loop, function call output handling, verification loop |
| `agent-browser/src/agent_browser/memory.py` | working memory and episodic memory patterns |

For shell-based agents, use `skills/appium-cli/SKILL.md`. For Python API
agents, call `get_tool_skill_prompt()` on every model turn and combine it with
agent-specific runtime context as shown in this guide.
