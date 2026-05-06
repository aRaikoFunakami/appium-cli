# agent-browser

Production-oriented mobile browser automation built on the
[OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) and the
[`appium-cli`](../README.md) tool surface.

## Architecture

`agent-browser` runs a **single capable Browser Agent** with rich tools rather
than a chain of Planner / Observer / Executor / Verifier agents. The agent
performs planning, observation, verification, retry and fallback inside one
SDK loop, with safety enforced at the tool boundary.

```
User goal
  │
  ▼
load config (.env -> env vars override)
  │
  ▼
load JSONL episodic memory (hints from past runs)
  │
  ▼
ensure appium-cli session daemon is healthy (reuse or start)
  │
  ▼
create single Browser Agent
  │ tools: 70+ appium-cli tools (FunctionTool adapters)
  │      + browser_result   (signals completion, stops the run)
  │      + human_approval   (stdin approval for sensitive actions)
  │ instructions: dynamic - includes working memory + episodic hints
  │ tool_use_behavior: StopAtTools(["browser_result"])
  ▼
Runner.run(agent, goal, context=BrowserAgentContext)
  ├─ model picks tools and arguments
  ├─ adapter classifies safety BEFORE talking to the daemon
  ├─ adapter calls appium_cli.openai_tools.call_tool()
  ├─ screenshot results are saved to artifacts/, base64 stripped from logs
  ├─ adapter updates working memory and appends MemoryEvents to JSONL
  └─ agent self-verifies via snapshot/web_snapshot/webview_url/webview_title
  │
  ▼
TaskResult { success, title, url, summary, tool_calls, retries, artifacts }
```

### Why single-agent?

A previous multi-agent prototype required 6-8 LLM API calls per browser step
because of orchestrator/handoff overhead. The single-agent design folds
planning, observation and verification into the system prompt and lets the SDK
loop call multiple tools in one model turn, dramatically reducing wall-clock
time per step.

## Prerequisites

`agent-browser` is **observation-only** for prerequisites. It will not install
Appium, Android SDK, drivers, or Node.js for you.

You must have:

- Appium server running at `localhost:4723` (override with
  `AGENT_BROWSER_APPIUM_PORT`).
- Android emulator or physical device connected via `adb`.
- Parent `appium-cli` package installed (this project depends on it via the
  local editable path in `pyproject.toml`).
- `OPENAI_API_KEY` set in environment or `.env`.

## Install

```bash
cd agent-browser
uv sync
```

This installs:

- `openai-agents` (Agents SDK)
- `pydantic`
- `python-dotenv`
- the parent `appium-cli` package as an editable dependency

## Run a task

```bash
# preferred smoke test (deterministic, no CAPTCHA)
uv run agent-browser \
  "Navigate to https://openai.github.io/openai-agents-python/ and return the page title and URL"

# JSON output for downstream tooling
uv run agent-browser --json "Open https://example.com and report the page title"
```

The CLI prints structured progress logs to stderr (tool calls, durations,
guardrail decisions, retries, screenshots). Use `--log-level DEBUG` for more.

## Safety policy

- Sensitive actions (login, password entry, payment, purchase, reservation
  confirmation, personal data submission, submit/finalize buttons matched to a
  sensitive context) require an explicit `human_approval` call before
  execution.
- `human_approval` prompts on stdin for `yes` to grant approval. Anything else
  denies it. Approvals are scoped to the `approval_key` and live only inside
  the run context (never persisted as raw value).
- A small set of destructive tools is **blocked unconditionally** locally and
  never reach the daemon (`terminate_app`, `restart_app`, `set_orientation`).
- Credentials must NEVER be passed on the command line or hard-coded. Provide
  them through your own out-of-band mechanism.
- Argument values that look like sensitive content are summarized, not logged.
  Screenshot base64 is written to disk but never echoed to logs.

## Artifacts and memory

- **Artifacts**: each `screenshot` tool call saves a PNG to
  `AGENT_BROWSER_ARTIFACTS_DIR` (default `artifacts/`). The agent receives
  only a short reference back, not the base64 payload.
- **Episodic memory**: `MemoryEvent` records (tool successes/failures,
  approvals, completions) are appended to `AGENT_BROWSER_MEMORY_PATH`
  (default `.agent-browser-memory.jsonl`). Recent events relevant to the
  current domain are injected into the next run's instructions as hints.
- **Working memory**: per-run state (URL, observations, failures, approvals,
  retries) is held in `RunContextWrapper.context` and never sent to the LLM
  except via the dynamic instructions section.

## Known limitations

- **Google search triggers CAPTCHA** under automation. Prefer deterministic
  destinations (the OpenAI Agents docs site, `example.com`, etc.) for smoke
  tests. If you must search, use a non-Google search engine or a direct URL.
- **iOS Safari** is intentionally extension-ready (`AGENT_BROWSER_PLATFORM`)
  but not yet wired into the default workflow.
- **Strict JSON schemas** are disabled for the appium-cli tool subset because
  the registry uses partial `required` lists and `default` values that strict
  mode rejects. Custom tools (`browser_result`, `human_approval`) remain
  strict.

## Tests

```bash
uv run pytest
```

Unit tests cover schemas, memory, guardrails, and the appium-cli FunctionTool
adapter (with a mocked daemon `call_tool`). E2E coverage requires a running
Appium server and a connected device and is intentionally excluded from the
default test run.
