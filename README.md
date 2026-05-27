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

The latest source is available at
<https://github.com/aRaikoFunakami/appium-cli.git>.

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

### Remote ADB server (containerized / cross-host setups)

When `appium-cli` runs inside a container or VM while the Android device is attached to a different host (for example on Apple Silicon + Colima, where USB cannot be passed into the Linux VM), set the following environment variables before `appium-cli session start` so the Appium server is told to reach `adb` over TCP instead of localhost:

| Variable | Maps to W3C capability | Example |
|---|---|---|
| `APPIUM_REMOTE_ADB_HOST` | `appium:remoteAdbHost` | `host.docker.internal` |
| `APPIUM_REMOTE_ADB_PORT` | `appium:adbPort`       | `5037` |

```bash
# On the host: expose adb on all interfaces
adb kill-server
adb -a -P 5037 nodaemon server &

# Inside the container
export APPIUM_REMOTE_ADB_HOST=host.docker.internal
export APPIUM_REMOTE_ADB_PORT=5037
appium-cli server start --port 4723
appium-cli session start --udid <serial>
```

Both variables are optional and have no effect when unset; existing local-only setups are unchanged.

### External Appium server (host-side / Apple Silicon WebView)

`appium-cli session start` can connect to an Appium server running outside the current host or container. Two equivalent ways:

```bash
# Via CLI flag
appium-cli session start --server-url http://host.docker.internal:4723

# Via environment variable (read by session start, server status, and server start)
export APPIUM_SERVER_URL=http://host.docker.internal:4723
appium-cli session start
```

When an external URL is provided:

- `start_server` is not called; the external server is treated as ownership `external` and is never stopped by `appium-cli`.
- `server status` reports the external URL with `ownership=external` and probes `<URL>/status` for liveness.
- `server start` becomes a no-op that prints a friendly notice and exits 0 when the external endpoint is reachable; it errors out clearly if the endpoint is unreachable.
- The session daemon's `--adb-fallback` is *not* enabled for non-loopback external hosts because the host Appium can use its own adb. For loopback external URLs, the fallback is still enabled.

Precedence in `session start`:

1. explicit `--server-url`
2. explicit `--port` (local mode at that port)
3. `APPIUM_SERVER_URL` env (external)
4. default local port `4723`

If both `--server-url` and `--port` are passed, the URL wins and a warning is printed to stderr.

### Apple Silicon (arm64) macOS + Linux arm64 devcontainer: Chrome/WebView

Running Android Chrome / WebView automation from an arm64 Linux devcontainer on an Apple Silicon Mac has a structural constraint that pure Android (native UiAutomator2) does *not* have.

Why native Android automation works in arm64 Linux containers:

- Native Appium + uiautomator2 talks to `adb` and the device-side UiAutomator2 server.
- Nothing needs a Linux arm64 ChromeDriver, so the container architecture does not matter for native flows.

Why Chrome/WebView automation breaks in arm64 Linux containers:

- For WebView / context switching / `webview_title` / `goto` / `web_query`, Appium must launch a local **ChromeDriver** binary that matches the device's Chrome / WebView version.
- "Local" means inside the OS where Appium itself runs (the container OS), not the macOS host.
- Chrome for Testing publishes ChromeDriver for `linux64` (x86_64 Linux), `mac-arm64` (Apple Silicon **macOS**, Mach-O), `mac-x64`, `win32`, `win64`. **There is no `linux-arm64` ChromeDriver build.**
- The Mach-O `mac-arm64` binary cannot be executed inside any Linux container; macOS executables are not ELF.
- The `linux64` (x86_64) binary cannot execute in an arm64 Linux container without an x86_64 emulator. With Apple Silicon + arm64 Linux Docker images, this is what Appium downloads, and it fails with errors like `Chromedriver --version exited with code 255`.
- Result: native Android keeps working, but the moment a flow needs WebView, it fails inside the container.

Supported fix: run Appium on the macOS host (where `mac-arm64` ChromeDriver is valid), keep the agent / `appium-cli` arm64 in the container, and connect them via `host.docker.internal`:

```bash
# On the macOS host (one-time install: appium and uiautomator2 driver).
# appium-cli does not install these.
npm install -g appium
appium driver install uiautomator2

# Start Appium on the host with the right insecure features.
appium --address 0.0.0.0 --port 4723 \
  --allow-insecure=uiautomator2:chromedriver_autodownload,uiautomator2:adb_shell

# From inside the arm64 Linux container.
appium-cli session start --server-url http://host.docker.internal:4723
```

Notes:

- Rosetta / amd64 emulated containers are *not* a supported workaround for this; keep the container arm64.
- Do **not** set `APPIUM_REMOTE_ADB_HOST` when Appium runs on the macOS host, because the host Appium can reach `adb` locally; remote-ADB capabilities are only for the in-container Appium case.
- `agent-sandbox` automates host Appium lifecycle and devcontainer wiring for this pattern (see its README).

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

Persistent artifacts are stored under a project-local `.appium-cli/` directory (relative to cwd). This directory is `.gitignore`d.

```
.appium-cli/
├── current-session                          # active session id
├── server.json / server.log                 # Appium server state
├── session-2026-05-04T02-18-02-171Z.log     # CLI invocation log (JSONL)
└── session-2026-05-04T02-18-02-171Z/        # per-session artifacts
    ├── daemon.log                            # daemon stdout/stderr
    └── screenshot-2026-05-04T02-20-15-033Z.png
```

Daemon runtime coordination files (`session.sock`, `session.pid`) live in a per-workspace runtime directory under `/tmp` (`/tmp/.appium-cli-<cwd-hash>/`, mode `0700`). They are kept off the workspace filesystem because Unix domain sockets are unsupported on some bind mounts (notably `virtiofs` in Docker Desktop devcontainers). Set `APPIUM_CLI_RUNTIME_DIR` to override the location.

**Invocation log** (`.log`): Each CLI command appends a JSONL line with timestamp, command, sanitized args, status, exit code, and duration.

**Screenshots**: `screenshot` saves a PNG file under the session artifact directory and includes the `path` field in the JSON response. Agent integrations should reuse that returned path instead of decoding and saving `image_base64` again.

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

## Python API

`appium_cli.openai_tools` provides a Python integration layer for building LLM
agents that use appium-cli tools programmatically instead of invoking each tool
through the shell. It exposes OpenAI-compatible tool schemas, a reusable
`get_tool_skill_prompt()` prompt fragment, and `call_tool()` dispatch through
the session daemon.

See [docs/openai-tools-integration.md](docs/openai-tools-integration.md) for a
full integration guide, code examples, prompt templates, result handling rules,
and the tool catalog.

## Tests

```bash
uv run pytest -q
uv run pytest -m e2e -q
uv run pytest -m e2e --run-e2e -q
```

E2E tests are skipped by default unless `--run-e2e` is provided and a real Android/Appium environment is available.
