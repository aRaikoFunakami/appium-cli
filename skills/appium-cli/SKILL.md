---
name: appium-cli
description: Automate Android device interactions through Appium with snapshot-based refs.
allowed-tools: Bash(appium-cli:*)
---

# Mobile Automation with appium-cli

Use `appium-cli` as an artifact-first Appium automation CLI. Observe with snapshots, act on refs from the latest snapshot, and rely on persisted artifacts for full trees, refs, search, and diffs.

## Quick start

```bash
appium-cli doctor
appium-cli devices --platform android
appium-cli server status
appium-cli server start --port 4723
appium-cli session status
appium-cli session start

appium-cli snapshot
appium-cli snapshot_refs
appium-cli tap btn_login
appium-cli snapshot_show latest
```

Default `snapshot` and `web_snapshot` output is compact metadata plus artifact links. Full trees live in files under `.appium-cli/snapshots/`. Action commands automatically append a post-action snapshot artifact link in normal output.

## Core workflow

1. Observe: `appium-cli snapshot` or `appium-cli web_snapshot`.
2. Inspect artifacts if needed: `snapshot_show`, `snapshot_refs`, `snapshot_search`.
3. Act on a current ref: `tap <ref>`, `type_text <ref> <text>`, `scroll_down [ref]`.
4. Read the post-action snapshot metadata printed by the action.
5. Use refs from the newest snapshot only.

For piping, diffs, or full tree output, use global `--raw` before the command:

```bash
appium-cli --raw snapshot > before.yml
appium-cli tap btn_login
appium-cli --raw snapshot > after.yml
diff before.yml after.yml
```

Raw snapshot output is the tree content. Raw actions return only a bare success/failure result and suppress post-action snapshot links.

## Observation commands

```bash
appium-cli snapshot                         # native metadata + artifacts
appium-cli snapshot main_list --depth=2     # element-scoped native snapshot
appium-cli web_snapshot                     # WebView metadata + artifacts
appium-cli web_snapshot web_form --depth=3  # element-scoped DOM snapshot
appium-cli --raw snapshot > screen.yml      # full tree for piping/diffing
appium-cli snapshot --filename=screen.yml   # save tree while printing metadata

appium-cli snapshot_show latest             # show compact artifact
appium-cli snapshot_show latest --artifact=full
appium-cli snapshot_show latest --ref=btn_login
appium-cli snapshot_search "Storage" --role=row
appium-cli snapshot_refs latest --role=button
appium-cli generate_locator btn_login

appium-cli describe btn_login
appium-cli find_by_text "Log in"
appium-cli screenshot                       # rarely needed
appium-cli get_page_source                  # token-heavy diagnostic escape hatch
```

`snapshot` is primary. Use `screenshot` only when visual pixels are necessary. Use `get_page_source` only for diagnostics when snapshot artifacts are insufficient.

## Actions

```bash
appium-cli tap btn_login
appium-cli type_text input_email "user@example.com" --submit
appium-cli scroll_down recycler_view
appium-cli scroll_down                      # full visible screen
appium-cli swipe_left carousel
appium-cli press_key back
appium-cli wait 1
```

Ref-first targeting is the default. Directional aliases accept an optional ref; omit it only for full-screen gestures. Compatibility commands such as `scroll down --ref=recycler_view` still exist, but prefer `scroll_down recycler_view`.

## WebView / Chrome

```bash
appium-cli list_contexts
appium-cli webview_switch
appium-cli web_snapshot
appium-cli web_query "input,button,a" --attrs=data-testid,autocomplete
appium-cli web_eval "el.getAttribute('data-testid')" web_btn_submit
appium-cli click web_btn_submit
appium-cli fill web_search "query"
appium-cli native_switch
```

Targeting layers:

1. Snapshot refs first (`web_...` refs from `web_snapshot`).
2. WebView CSS selectors / generated locators second (`web_query`, `generate_locator`, CSS-aware commands where available).
3. Legacy native locators only as expert-only recovery.

## Environment and lifecycle

```bash
appium-cli doctor
appium-cli devices --json
appium-cli server start --port 4723
appium-cli server stop
appium-cli session start
appium-cli session stop
appium-cli get_device_info
```

`doctor` is read-only. `server stop` only stops Appium servers started by `appium-cli`.

## Important rules

- Keep `--raw` global: `appium-cli --raw snapshot`, not after the command.
- Do not call `adb`, `appium`, `npm`, or installer commands directly unless the user explicitly asks.
- Prefer canonical snake_case tool names: `get_device_info`, `type_text`, `press_keycode`.
- Do not edit installed skill copies under `.agents/` or `~/.copilot/`; edit `skills/appium-cli/` and run `appium-cli install --skills`.

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
- [WebView and Chrome](references/webview.md)
- [Legacy locator tools](references/legacy-locator.md)
