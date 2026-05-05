# appium-cli

CLI for Appium-based mobile automation by LLM agents.

`appium-cli` exposes smartestiroid-compatible Appium tools as shell commands so coding agents can inspect and operate Android devices through concise CLI calls.

## Responsibility boundary

`appium-cli` does **not** install prerequisites or repair the host environment.

User responsibility:

- Node.js / npm
- Appium
- Appium drivers such as `uiautomator2` and `xcuitest`
- Android SDK, `ANDROID_HOME`, `JAVA_HOME`, `adb`
- Xcode / `xcrun` for iOS observation on macOS

`appium-cli` responsibility:

- `doctor`: read-only environment diagnostics and hints
- `devices`: Android/iOS device observation
- `server`: singleton Appium server reuse with ownership tracking
- `session`: persistent WebDriver session daemon
- smartestiroid-compatible tool commands such as `snapshot`, `tap`, and `get_device_info`

## Setup

Editable install is recommended during development:

```bash
uv tool install --editable . --force
appium-cli --version
```

The source tree is used directly, so changes under `src/` are reflected after reinstalling with `--force` when dependencies or entry points change.

## Core lifecycle

```bash
appium-cli doctor
appium-cli devices
appium-cli devices --platform android
appium-cli devices --platform ios
appium-cli devices --json

appium-cli server status
appium-cli server start --port 4723
appium-cli server start --no-allow-adb-shell
appium-cli server start --no-chromedriver-autodownload
appium-cli server stop

appium-cli session status
appium-cli session start
appium-cli session stop
```

`server stop` only stops an Appium server started by `appium-cli`. Externally started Appium servers are reused but never killed.

### Chrome/WebView Chromedriver autodownload

For Chrome or WebView automation, Appium must be able to find a Chromedriver that matches the device's Chrome/WebView version. When `appium-cli server start` starts a new Appium server, Chromedriver autodownload is enabled by default using the Appium 3-compatible insecure feature name `uiautomator2:chromedriver_autodownload`.

Disable this default with:

```bash
appium-cli server start --no-chromedriver-autodownload
```

When using an externally started Appium server, enable the feature yourself. Appium 3 requires insecure feature names to be prefixed with the driver automation name or `*`.

For Android UiAutomator2 on Appium 3, start Appium with:

```bash
appium --address 127.0.0.1 --port 4723 \
  --allow-insecure=uiautomator2:chromedriver_autodownload
```

To allow the feature for all drivers, use:

```bash
appium --address 127.0.0.1 --port 4723 \
  --allow-insecure='*:chromedriver_autodownload'
```

This enables Appium's Chromedriver autodownload feature on the server side. The session capabilities can remain the normal Android Chrome/WebView capabilities, for example:

```json
{
  "platformName": "Android",
  "appium:automationName": "UiAutomator2",
  "browserName": "Chrome"
}
```

Optionally set `appium:chromedriverExecutableDir` in the session capabilities to choose where downloaded Chromedriver binaries are stored. `--relaxed-security` also enables this feature, but `--allow-insecure=uiautomator2:chromedriver_autodownload` is safer because it only permits the required feature.

## Artifact storage

Runtime state and artifacts are stored under a project-local `.appium-cli/` directory (relative to cwd). This directory is `.gitignore`d.

```
.appium-cli/
├── current-session                          # active session id
├── server.json / server.log                 # Appium server state
├── session.sock / session.pid               # daemon IPC
├── session-2026-05-04T02-18-02-171Z.log     # CLI invocation log (JSONL)
└── session-2026-05-04T02-18-02-171Z/        # per-session artifacts
    ├── daemon.log                            # daemon stdout/stderr
    └── screenshot-2026-05-04T02-20-15-033Z.png
```

**Invocation log** (`.log`): Each CLI command appends a JSONL line with timestamp, command, sanitized args, status, exit code, and duration.

**Screenshots**: `screenshot` saves a PNG file under the session artifact directory and includes the `path` field in the JSON response.

## Tool command groups

Canonical command names follow smartestiroid function names in snake_case.

### Observation

```bash
appium-cli snapshot
appium-cli describe e12
appium-cli find_by_text "Log in"
appium-cli screenshot
appium-cli get_page_source
```

`screenshot` returns the smartestiroid-compatible JSON string with an additional `path` field when a session is active:

```json
{"type":"screenshot","image_base64":"...","region":"full","path":".appium-cli/session-.../screenshot-....png","size_bytes":12345,"mime_type":"image/png"}
```

### Basic actions

```bash
appium-cli tap e12
appium-cli type_text e8 "hello" --submit
appium-cli scroll_down
appium-cli scroll_down e20
appium-cli swipe_left
appium-cli press_key back
appium-cli wait 1
```

### Gestures

```bash
appium-cli long_press e12
appium-cli double_tap e12
appium-cli drag e12 500 900
appium-cli fling_up
appium-cli fling_up e20
appium-cli pinch_open e12
appium-cli pinch_close e12
```

Directional aliases take an optional ref. Passing a ref scopes the gesture to that element/container; omitting it performs the gesture on the full visible screen.

### Containers and verification

```bash
appium-cli list_containers
appium-cli find_container "Settings"
appium-cli within_container c2 --role=button
appium-cli assert_visible --text "Log in"
appium-cli assert_visible --ref e22
```

### App management and device info

```bash
appium-cli get_device_info
appium-cli get_current_app
appium-cli activate_app com.example.app
appium-cli terminate_app com.example.app
appium-cli restart_app com.example.app
appium-cli list_apps
appium-cli is_locked
appium-cli get_orientation
appium-cli set_orientation PORTRAIT
```

`get_device_info` output matches smartestiroid:

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

### Legacy locator/navigation tools

```bash
appium-cli find_element xpath "//*"
appium-cli click_element id "com.example:id/button"
appium-cli get_text accessibility_id "Login"
appium-cli press_keycode 4
appium-cli double_tap --by=xpath --value="//*[@text='Login']"
appium-cli send_keys xpath "//*[@class='android.widget.EditText']" "hello"
appium-cli wait_short_loading 5
appium-cli scroll_element xpath "//*[@scrollable='true']" --direction=up
appium-cli scroll_to_element xpath "//*[@text='Target']"
```

Prefer snapshot refs for new workflows. Use legacy locator tools for compatibility and low-level recovery.

## Output modes

Default stdout preserves each smartestiroid tool's return value.

Every command accepts `--json`. For smartestiroid-compatible tool commands, `--json` wraps the daemon response without changing the default stdout. For lifecycle/status commands, `--json` emits structured command metadata.

```bash
appium-cli get_device_info --json
appium-cli doctor --json
appium-cli server status --json
appium-cli session status --json
```

Session-not-running tool calls exit with code `3`. Shell-disabled remote Appium failures use exit code `8`.

## Skills

Install the bundled agent skill:

```bash
appium-cli install --skills
appium-cli install --skills --target=project --dry-run
appium-cli install --skills --target=project --force
```

The default target is the current project's `.agents/skills/appium-cli` directory. The skill allows only `Bash(appium-cli:*)`; it does not allow agents to run `adb`, `appium`, `npm`, or install commands directly.

## Tests

```bash
uv run pytest -q
uv run pytest -m e2e -q
uv run pytest -m e2e --run-e2e -q
```

E2E tests are skipped by default unless `--run-e2e` is provided and a real Android/Appium environment is available.
