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

## Tool groups to maintain

Maintain these implemented command groups, excluding LLM/dialog-agent internals:

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

## Current implementation baseline

The Phase 1 baseline includes:

1. Project scaffold and packaging.
2. `doctor`.
3. `devices`.
4. `server start|stop|status`.
5. Session daemon and `session start|stop|status`.
6. `get_device_info`.
7. `install --skills`.
8. Unit tests and Android E2E smoke tests.

Phase 1 observation work (snapshot, ref resolution) is complete. `core/snapshot.py`, `core/snapshot_generator.py`, and `core/ref_resolver.py` are ported from smartestiroid and must be maintained as smartestiroid-compatible.

## Packaging and layout

Use a Python `src/` layout:

```text
pyproject.toml
src/appium_cli/
src/appium_cli/__main__.py
src/appium_cli/cli/
src/appium_cli/core/
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

Use the project-managed `uv` environment when running tests. Do not call `pytest` directly; use `uv run pytest ...` so agents use the dependency versions from this project.

Avoid adding `pydantic`, formatters, linters, or new build tools unless the implementation genuinely requires them.

## Server and session design

- Store runtime state in the project-local `.appium-cli/` directory relative to the current working directory.
- Store server ownership at `.appium-cli/server.json`.
- Store daemon socket at `.appium-cli/session.sock`.
- Store daemon pid at `.appium-cli/session.pid`.
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

## Snapshot and ref resolution (smartestiroid parity)

The snapshot system is a faithful port of smartestiroid's `SnapshotGenerator` and `RefResolver`.

### Ref naming

Refs are stable IDs derived from the element's attributes (not sequential `e1`/`e2`):

- `resource-id="com.example:id/login"` → `login`
- `content-desc="Search"` → `search`
- `role=button, name="Submit"` → `btn_submit`
- Duplicate resource-ids get `_2`, `_3`, `_4` suffixes (e.g. `tabbackground`, `tabbackground_2`, `tabbackground_3`, `tabbackground_4`)

### Ref resolution (multi-strategy with bounds verification)

`RefResolver` tries locator strategies in order. After finding an element with each strategy, it verifies the element's bounds match the expected bounds within ±20px. If bounds mismatch, it falls through to the next strategy.

1. **resource-id** (`AppiumBy.ID`) → verify bounds
2. **accessibility_id** (content-desc, `AppiumBy.ACCESSIBILITY_ID`) → verify bounds
3. **xpath** (text match) → verify bounds
4. **coordinates** (center of expected bounds) → always passes

This solves the problem where multiple elements share the same resource-id (e.g. all tab buttons have `resource-id="tabBackground"`). Without bounds verification, `find_element(BY.ID, "tabBackground")` always returns the first match.

### Key source files

- `src/appium_cli/core/snapshot.py`: Data models (`LocatorStrategy`, `RefEntry`, `SnapshotElement`, `SnapshotContainer`, `SelectionContainer`, `AccessibilitySnapshot`)
- `src/appium_cli/core/snapshot_generator.py`: `SnapshotGenerator` — XML → AccessibilitySnapshot + ref map
- `src/appium_cli/core/ref_resolver.py`: `RefResolver` — ref → WebElement with bounds verification
- `src/appium_cli/daemon/state.py`: Singleton `SnapshotGenerator` and `RefResolver` instances

### Rules for modifying snapshot/ref code

- Do not revert to sequential `e1`/`e2` ref naming.
- Do not remove bounds verification from `RefResolver`.
- Do not bypass `RefResolver` by using `driver.find_element` directly in action tools.
- All ref-based actions must go through `state.ref_resolver.resolve(ref, driver)`.
- `compute_screen_id` uses MD5 of sorted `(role, name)` tuples (not SHA1 of raw XML).

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

### SKILL file update workflow

1. Always edit source skill files in `skills/appium-cli/` first.
2. Then run `appium-cli install --skills` to propagate changes to install targets (`.agents/skills/appium-cli/`, `~/.copilot/skills/appium-cli/`, etc.).
3. Never edit installed skill files (under `.agents/` or `~/.copilot/`) directly. They are overwritten by `install --skills`.

## Testing expectations

Add tests with each implemented surface:

- Unit tests for parsers, exit codes, daemon protocol, server ownership, and skill installation.
- E2E tests behind a marker such as `e2e`; skip by default unless `--run-e2e` is provided and a real Android device is available.
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
uv run pytest
uv run pytest -m e2e --run-e2e
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
