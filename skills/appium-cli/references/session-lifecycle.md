# Session Lifecycle

`appium-cli` separates the Appium HTTP server from the daemon-owned WebDriver session.

```bash
appium-cli server status
appium-cli server status --json
appium-cli server start --port 4723
appium-cli server start --no-allow-adb-shell
appium-cli server stop
```

`server start` reuses an existing Appium server when one is already running. `server stop` only stops a server that `appium-cli` started itself.

Session commands keep WebDriver state alive across tool invocations:

```bash
appium-cli session status
appium-cli session status --json
appium-cli session start
appium-cli session stop
```

Shell-dependent commands need Appium `mobile: shell`. When `appium-cli` starts Appium, shell support is enabled by default. External servers without shell support may fall back to local `adb` only when safe.
