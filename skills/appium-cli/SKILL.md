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
appium-cli scroll up --ref=recycler_view
appium-cli snapshot
```

## Commands

Do not guess argument order. Before using a command for the first time, check this command catalog, the linked reference page, or `appium-cli <command> --help`.

### Environment and session

```bash
appium-cli doctor
appium-cli devices --platform android
appium-cli server status
appium-cli server start --port 4723
appium-cli server stop
appium-cli session status
appium-cli session start
appium-cli session stop
```

### Observation

```bash
appium-cli snapshot
appium-cli describe btn_7
appium-cli find_by_text "Storage"
appium-cli screenshot
appium-cli screenshot --region=ref:btn_7
appium-cli get_page_source
```

### Core actions

```bash
# ref-first actions
appium-cli tap btn_7
appium-cli type_text input_search "hello" --submit

# direction-first gestures; pass the target container with --ref
appium-cli scroll up --ref=recycler_view
appium-cli scroll down --ref=main_content_scrollable_container
appium-cli swipe left
appium-cli swipe left --ref=carousel

appium-cli press_key back
appium-cli wait 1
```

### Gestures

```bash
appium-cli long_press btn_photo
appium-cli double_tap btn_photo
appium-cli drag btn_photo 500 900
appium-cli fling up
appium-cli fling down --ref=recycler_view
appium-cli pinch_open image_preview
appium-cli pinch_close image_preview
```

### Containers and verification

```bash
appium-cli list_containers
appium-cli find_container "Storage"
appium-cli within_container main_content_scrollable_container --role=button --position=first
appium-cli assert_visible --text="Storage"
appium-cli assert_visible --ref=btn_7
```

### App and device management

```bash
appium-cli get_device_info
appium-cli get_current_app
appium-cli activate_app com.android.settings
appium-cli terminate_app com.example.app
appium-cli restart_app com.example.app
appium-cli list_apps
appium-cli is_locked
appium-cli get_orientation
appium-cli set_orientation PORTRAIT
```

### Legacy locator tools

```bash
appium-cli find_element xpath "//*[@text='Login']"
appium-cli click_element id "com.example:id/button"
appium-cli get_text accessibility_id "Login"
appium-cli send_keys xpath "//*[@class='android.widget.EditText']" "hello"
appium-cli press_keycode 4
appium-cli scroll_element xpath "//*[@scrollable='true']" --direction=up
appium-cli scroll_to_element xpath "//*[@text='Target']"
```

## Argument order rules

- Ref-first actions pass the ref as the first positional argument: `tap <ref>`, `long_press <ref>`, `pinch_open <ref>`.
- Ref plus value actions pass the ref first, then the value: `type_text <ref> <text>`.
- Direction-first gestures pass direction first and the target as an option: `scroll <direction> --ref=<scrollable-ref>`, `swipe <direction> [--ref=<ref>]`, `fling <direction> [--ref=<ref>]`.
- Legacy locator tools use `<by> <value>` positionals; extra behavior is usually an option, for example `scroll_element <by> <value> --direction=up`.

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
