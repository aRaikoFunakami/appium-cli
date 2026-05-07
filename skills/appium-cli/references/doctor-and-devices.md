# Doctor and Devices

Use these commands before starting an automation session. They are observation/diagnostic commands, not installers.

```bash
appium-cli doctor
appium-cli doctor --json
appium-cli devices
appium-cli devices --platform android
appium-cli devices --platform ios
appium-cli devices --json
```

`doctor` reports `PASS`, `WARN`, or `FAIL` with hints. It never installs, fixes, or changes prerequisite tools.

`devices` observes Android devices via `adb devices -l` and iOS/simulator information via `xcrun` on macOS. Android automation commands require an Android device whose status is `device`.

After diagnostics pass, start/reuse the server and session, then observe with artifact-first snapshots:

```bash
appium-cli server start --port 4723
appium-cli session start
appium-cli snapshot
```
