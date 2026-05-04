---
name: appium-cli
description: Automate Android device interactions through Appium with snapshot-based refs.
allowed-tools: Bash(appium-cli:*)
---

# Mobile Automation with appium-cli

Use `appium-cli` to inspect the local Appium environment, list devices, manage the Appium server/session lifecycle, and call smartestiroid-compatible tools.

## Quick start

```bash
appium-cli doctor
appium-cli devices --platform android
appium-cli server status
appium-cli server start --port 4723
appium-cli session status
appium-cli get_device_info
appium-cli snapshot
appium-cli find_by_text "Log in"
appium-cli tap tabbackground_4
```

## Important rules

- Use canonical smartestiroid tool names such as `get_device_info`, `type_text`, and `press_keycode`.
- Do not call `adb`, `appium`, `npm`, or installation commands directly unless the user explicitly asks.
- `doctor` is read-only and only reports problems and hints.
- `server stop` only stops Appium servers started by `appium-cli`.

## References

- [Doctor and devices](references/doctor-and-devices.md)
- [Session lifecycle](references/session-lifecycle.md)
- [Device info](references/device-info.md)
- [Observation](references/observation.md)
- [Actions](references/actions.md)
- [Gestures](references/gestures.md)
- [Containers and verification](references/containers.md)
- [App management](references/app-management.md)
- [Legacy locator tools](references/legacy-locator.md)
