# Session Lifecycle

`appium-cli` separates the Appium HTTP server from the daemon-owned WebDriver session. Start or reuse a server, then start a persistent session before using snapshot/action tools.

```bash
appium-cli server status
appium-cli server start --port 4723
appium-cli session status
appium-cli session start
appium-cli snapshot
```

`server start` reuses an existing Appium server when one is already running. `server stop` only stops a server that `appium-cli` started itself; it will not terminate external servers.

## Server commands

```bash
appium-cli server status
appium-cli server status --json
appium-cli server start --port 4723
appium-cli server start --no-allow-adb-shell
appium-cli server start --no-chromedriver-autodownload
appium-cli server stop
```

Shell-dependent tools need Appium `mobile: shell`. When `appium-cli` starts Appium, shell support is enabled by default. External local servers may fall back to `adb` only when safe; remote external servers without the feature fail with exit code 8.

## Session commands

```bash
appium-cli session status
appium-cli session status --json
appium-cli session start
appium-cli session stop
```

The daemon keeps WebDriver state and latest snapshot/ref artifacts across short-lived CLI invocations. If refs look stale or the daemon loses the session:

```bash
appium-cli session stop
appium-cli session start
appium-cli snapshot
```

## Artifact state

Snapshots write artifacts under `.appium-cli/snapshots/` and update `latest.json`. Action commands refresh the snapshot automatically and print the new artifact links in normal output. Use `snapshot_search`, `snapshot_refs latest`, or targeted `snapshot_show latest --ref=<ref>` to inspect that state without another device query.

## WebView lifecycle

Chrome/WebView automation needs a matching Chromedriver. When `appium-cli` starts Appium, Chromedriver autodownload is enabled by default; use `--no-chromedriver-autodownload` to opt out.

```bash
appium-cli webview_status
appium-cli list_contexts
appium-cli webview_switch
appium-cli web_snapshot
```
