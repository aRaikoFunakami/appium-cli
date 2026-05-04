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

## Workflow

Use this loop for normal mobile automation:

1. Observe: run `appium-cli snapshot` after launching an app or changing screens.
2. Read the full snapshot output before acting. Do not rely on a single filtered line when choosing a target.
3. Choose a ref from the latest snapshot. Refs become stale after navigation, scrolling, dialogs, or screen updates.
4. Act on the current ref, for example `appium-cli tap btn_7`.
5. Verify with another `snapshot`, `assert_visible`, or the visible screen title before the next action.

Prefer visible snapshot refs over locator tools. Do not call `find_by_text` to re-search for an element that is already visible in the snapshot.

## Important rules

- Use canonical smartestiroid tool names such as `get_device_info`, `type_text`, and `press_keycode`.
- Do not call `adb`, `appium`, `npm`, or installation commands directly unless the user explicitly asks.
- `doctor` is read-only and only reports problems and hints.
- `server stop` only stops Appium servers started by `appium-cli`.
- Edit source skill files under `skills/appium-cli/` first, then propagate with `appium-cli install --skills`. Do not edit installed files under `~/.copilot/skills/` directly.

## References

- [Doctor and devices](references/doctor-and-devices.md)
- [Session lifecycle](references/session-lifecycle.md)
- [Device info](references/device-info.md)
- [Observation](references/observation.md)
- [Actions](references/actions.md)
- [Common patterns](references/patterns.md)
- [Gestures](references/gestures.md)
- [Containers and verification](references/containers.md)
- [App management](references/app-management.md)
- [Legacy locator tools](references/legacy-locator.md)
