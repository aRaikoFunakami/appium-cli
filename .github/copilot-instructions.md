# Copilot instructions for appium-cli

This repository implements `appium-cli`: a Python command-line interface for LLM agents to drive Appium-based mobile automation. Follow these instructions for all code changes.

## Core goals

- Build a CLI-first tool, not an MCP server.
- The CLI is called by LLM agents through shell commands such as `appium-cli snapshot` and `appium-cli get_device_info`.
- Preserve smartestiroid `android/appium_tools` tool names, inputs, outputs, and behavior wherever a tool is ported.
- Do not use an LLM inside any `appium-cli` tool. The caller is already an LLM agent.
- Do not install prerequisite tools. `appium-cli` only observes and reports environment state.

## Mandatory development workflow

For any development work beyond a very small, narrowly scoped change such as a one-line fix:

1. Use plan mode before editing implementation files.
2. Create or update a concrete development plan.
3. Finish all necessary prerequisite research in fleet mode with parallel sub-agents where possible.
4. Review the whole plan and research results for consistency before implementation.
5. Ask the user to choose edit/interactive or autopilot mode before starting development.
6. Do not begin implementation until the user has explicitly approved proceeding in edit/interactive or autopilot mode.

Only skip this workflow for truly tiny changes with a very limited blast radius, such as correcting a typo or changing a single obvious line. When in doubt, use the full workflow.

## Responsibility boundary

User responsibility:

- Node.js / npm
- Appium
- Appium drivers such as `uiautomator2` and `xcuitest`
- Android SDK, `ANDROID_HOME`, `JAVA_HOME`, `adb`
- Xcode / `xcrun` for iOS observation on macOS

`appium-cli` responsibility:

- `doctor`: read-only diagnostics and hints only. Never run fix/install commands.
- `devices`: enumerate connected devices by observing `adb` / `xcrun`.
- `server`: singleton Appium server usage with ownership tracking.
- `session`: persistent Appium WebDriver session daemon.
- Tool commands such as `get_device_info`, `snapshot`, `tap`, etc.

## Smartestiroid compatibility rules

- Canonical command names must match smartestiroid function names in snake_case.
  - Good: `appium-cli get_device_info`, `appium-cli type_text`, `appium-cli press_keycode`
  - Kebab-case aliases may exist, but documentation, SKILL files, and tests must use canonical snake_case names.
- Default stdout must match the smartestiroid return value for the tool.
  - If smartestiroid returns a text string, print that text.
  - If smartestiroid returns a JSON string, print that JSON string.
  - Example: `screenshot` must default to `{"type":"screenshot","image_base64":"...","region":"..."}`.
- `--json` may wrap CLI metadata, but it must not replace the default smartestiroid-compatible output.
- Strip smartestiroid-only logging/reporting concerns:
  - Remove `SLog` dependencies.
  - Remove screenshot saving/report side effects unless directly required by the tool output.
  - Remove LangChain `@tool` decorators.
  - Remove OpenAI/LLM dependencies.
- Preserve meaningful exceptions where compatibility depends on them, such as `ValueError("Driver is not initialized")` and `InvalidSessionIdException`.

## Tools to implement

Implement these groups, excluding LLM/dialog-agent internals:

- Observation: `snapshot`, `describe`, `find_by_text`, `screenshot`, `get_page_source`
- Basic actions: `tap`, `type_text`, `scroll`, `swipe`, `press_key`, `wait`
- Gestures: `long_press`, `double_tap`, `drag`, `fling`, `pinch_open`, `pinch_close`
- Containers: `list_containers`, `find_container`, `within_container`
- Legacy navigation: `scroll_element`, `scroll_to_element`, `wait_short_loading`
- Legacy locator interaction: `find_element`, `click_element`, `get_text`, `press_keycode`, legacy `double_tap`, `send_keys`
- App management: `get_current_app`, `activate_app`, `terminate_app`, `list_apps`, `restart_app`
- Device info: `get_device_info`, `is_locked`, `get_orientation`, `set_orientation`
- Verification: `assert_visible`
- Session status: `get_driver_status`

Do not implement:

- `analyze_screen_content`
- `verify_final_result`
- `find_element_with_screenshot`
- `detect_and_close_blocking_dialog`
- Any DialogAgent or LLM-backed behavior

## Phase 1 implementation scope

Start with the smallest functional path:

1. Project scaffold and packaging.
2. `doctor`.
3. `devices`.
4. `server start|stop|status`.
5. Session daemon and `session start|stop|status`.
6. `get_device_info`.
7. `install --skills`.
8. Unit tests and Android E2E smoke tests.

Do not port `core/snapshot.py`, `ref_resolver.py`, or `xml_compressor.py` in Phase 1 unless a Phase 1 command directly requires them. They belong to the Phase 2 observation work.

## Packaging and layout

Use a Python `src/` layout:

```text
pyproject.toml
src/appium_cli/
src/appium_cli/__main__.py
src/appium_cli/cli/
src/appium_cli/daemon/
src/appium_cli/tools/
src/appium_cli/utils/
skills/appium-cli/
tests/
```

Use the script entry point:

```toml
appium-cli = "appium_cli.__main__:main"
```

Phase 1 runtime dependencies should stay minimal:

- `appium-python-client`
- `selenium`
- `typer`

Phase 1 test dependency:

- `pytest`

Avoid adding `pydantic`, formatters, linters, or new build tools unless the implementation genuinely requires them.

## Server and session design

- Store server ownership at `~/.appium-cli/server.json`.
- Store daemon socket at `~/.appium-cli/session.sock`.
- Store daemon pid at `~/.appium-cli/session.pid`.
- `server stop` must only stop a self-owned Appium server.
- Never kill an externally started Appium server.
- `server status` should report:
  - running/stopped
  - ownership: `self`, `external`, or `none`
  - port
  - pid when known
  - URL
  - `shell_capable`: `true`, `false`, or `unknown`
- `session start` should create a persistent daemon-owned WebDriver session.
- CLI tool commands should be short-lived clients that call the daemon through line-delimited JSON-RPC over the Unix socket.
- Use request/response IDs in the JSON-RPC protocol.
- On session startup, probe `mobile: shell` with a lightweight command to determine shell capability.
- If a shell-dependent command runs against a local external Appium server without `mobile: shell`, fall back to `adb -s <udid> shell` when safe.
- If a shell-dependent command runs against a remote external Appium server without `mobile: shell`, fail with exit code `8` (`FEATURE_NOT_ENABLED`).

## `get_device_info` compatibility

The Phase 1 `get_device_info` command must match smartestiroid output:

```text
Device Information:
Model: ...
Brand: ...
Device Name: ...
Android Version: ...
SDK: ...
Display: ...
Density: ...
Current Package: ...
Current Activity: ...
Orientation: ...
Is Locked: ...
```

It should use:

- `getprop ro.product.model`
- `getprop ro.product.brand`
- `getprop ro.product.name`
- `getprop ro.build.version.release`
- `getprop ro.build.version.sdk`
- `wm size`
- `wm density`
- `driver.current_package`
- `driver.current_activity`
- `driver.orientation`
- `driver.is_locked()`

Handle Appium `mobile: shell` responses that are either a dict containing `stdout` or a raw string.

## SKILL policy

- Implement only `appium-cli install --skills`.
- Do not add `appium-cli init`.
- Source skill files live in `skills/appium-cli/`.
- The default install target is project-local `.agents/skills/appium-cli`.
- `install --skills` should support:
  - `--target=project|claude-code|copilot-cli|all`
  - `--dry-run`
  - `--force`
- Re-running without changes should be idempotent and skip byte-identical files.
- User-level skill destinations should be conservative: only write when explicitly requested and/or the destination exists.
- `SKILL.md` frontmatter must use only:

```markdown
---
name: appium-cli
description: Automate Android device interactions through Appium with snapshot-based refs.
allowed-tools: Bash(appium-cli:*)
---
```

Do not add `Bash(adb:*)`, `Bash(appium:*)`, `Bash(npm:*)`, or other direct prerequisite commands to `allowed-tools`.

## Testing expectations

Add tests with each implemented surface:

- Unit tests for parsers, exit codes, daemon protocol, server ownership, and skill installation.
- E2E tests behind a marker such as `e2e`; skip by default when a real Android device is not available.
- Split Appium E2E into:
  - self-owned server case
  - external server reuse case
- Confirm external Appium servers are not stopped by `appium-cli server stop`.

Expected validation commands:

```bash
uv tool install --editable . --force
appium-cli --help
appium-cli doctor
appium-cli devices --json
pytest
pytest -m e2e
```

Run only existing test/build commands. Do not introduce unrelated tooling.

## Safety and implementation style

- Prefer precise, small changes.
- Do not silently swallow errors. Surface actionable messages and exit codes.
- Do not use broad `except Exception` unless re-raising or converting to a clear CLI error at the boundary.
- Do not use destructive process cleanup. Kill only specific PIDs that `appium-cli` owns.
- Do not use `pkill`, `killall`, or name-based process killing.
- Do not run `git push` or otherwise publish changes. Pushing must always be performed manually by the user.
- Do not commit secrets, device-specific credentials, or environment-specific paths into source.
- Keep code ASCII unless a file already uses non-ASCII and there is a clear reason.
