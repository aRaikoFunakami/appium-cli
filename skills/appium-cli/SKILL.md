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
appium-cli snapshot_search "Welcome"
```

Default `snapshot` and `web_snapshot` output is compact metadata plus artifact links. Full trees live in files under `.appium-cli/snapshots/`. Action commands automatically append a post-action snapshot artifact link in normal output.

## Core workflow

1. Observe: `appium-cli snapshot` or `appium-cli web_snapshot`.
2. Extract only what you need: `snapshot_search`, `snapshot_refs`, or `web_query`.
3. Act on a current ref: `tap <ref>`, `type_text <ref> <text>`, `scroll_down [ref]`.
4. Read the post-action snapshot metadata printed by the action.
5. Use refs from the newest snapshot only.

Do not read whole snapshot artifacts by default. Treat `.compact.yml` as a file artifact that preserves UI hierarchy outside the prompt. Pull relevant fragments with `snapshot_search`, `snapshot_refs`, `web_query`, `snapshot_show --ref`, or local grep/rg-style extraction when available.

For piping, diffs, or full tree output, use global `--raw` before the command:

```bash
appium-cli --raw snapshot > before.yml
appium-cli tap btn_login
appium-cli --raw snapshot > after.yml
diff before.yml after.yml
```

Raw snapshot output is the tree content. Raw actions return only a bare success/failure result and suppress post-action snapshot links.

For before/after verification, filter diffs to relevant lines instead of pasting whole files:

```bash
diff before.yml after.yml | grep -E "Qiita|検索|title|url|ref:"
```

## Observation commands

```bash
appium-cli snapshot                         # native metadata + artifacts
appium-cli snapshot main_list --depth=2     # element-scoped native snapshot
appium-cli web_snapshot                     # WebView metadata + artifacts
appium-cli web_snapshot web_form --depth=3  # element-scoped DOM snapshot
appium-cli --raw snapshot > screen.yml      # full tree for piping/diffing
appium-cli snapshot --filename=screen.yml   # save tree while printing metadata

appium-cli snapshot_search "Storage" --role=row      # search saved artifact/index
appium-cli snapshot_refs latest --role=button        # list actionable refs
appium-cli snapshot_show latest --ref=btn_login      # targeted ref detail
appium-cli snapshot_show latest                      # targeted fallback; can be large
appium-cli snapshot_show latest --artifact=full      # debugging only
appium-cli generate_locator btn_login

appium-cli describe btn_login
appium-cli find_by_text "Log in"
appium-cli screenshot                       # rarely needed
appium-cli get_page_source                  # token-heavy diagnostic escape hatch
```

`snapshot` is primary. Use `screenshot` only when visual pixels are necessary. Use `get_page_source` only for diagnostics when snapshot artifacts are insufficient.

```bash
appium-cli console_messages                 # browser console logs
appium-cli console_messages --level error   # errors only
appium-cli network_requests                 # network requests (requires --enable-network-log)
appium-cli network_requests --filter "/api" # filter by URL
```

### depth parameter

`snapshot` and `web_snapshot` accept an optional `depth` parameter to limit the depth of the snapshot tree. By default, the full tree is returned with no depth limit.

Depth counts only **semantic levels** (interactive elements, landmarks, headings, lists, tables) — layout wrappers like `<div>` and `<span>` are automatically flattened. This means `depth=2` reaches inputs, buttons, and links directly:

```bash
appium-cli web_snapshot --depth=2     # form > textbox, button, combobox
appium-cli snapshot --depth=1         # top-level landmarks only
```

Do not set `depth` for full-page observations — the default (full tree) ensures all elements are visible.

## Actions

```bash
appium-cli tap btn_login
appium-cli type_text input_email "user@example.com" --submit
appium-cli scroll_down recycler_view
appium-cli scroll_down                      # full visible screen
appium-cli swipe_left carousel
appium-cli press_key back
appium-cli wait 1
appium-cli wait_for --text "Welcome"        # wait for text to appear
appium-cli wait_for --gone "Loading..."     # wait for text to disappear
appium-cli file_upload web_photo /path/to/photo.jpg  # upload file
```

Ref-first targeting is the default. Directional aliases accept an optional ref; omit it only for full-screen gestures. Compatibility commands such as `scroll down --ref=recycler_view` still exist, but prefer `scroll_down recycler_view`.

## WebView / Chrome

```bash
appium-cli list_contexts
appium-cli webview_switch
appium-cli web_snapshot
appium-cli web_query "input,button,a" --attrs=name,type,placeholder,aria-label,data-testid,autocomplete
appium-cli web_eval "el.getAttribute('data-testid')" web_btn_submit
appium-cli click web_btn_submit
appium-cli fill web_search "query"
appium-cli native_switch
appium-cli tabs list                        # list WebView tabs
appium-cli tabs switch --index 1            # switch to tab
appium-cli tabs new --url "https://example.com"  # open new tab
```

React Select / autocomplete inputs require special handling. Use `--slowly` to type one character at a time, then click the suggestion:

```bash
appium-cli fill web_subjects "Comp" --slowly
appium-cli web_snapshot
appium-cli click web_option_computer_science
```

Do not use `web_eval` to set `.value` directly on React-controlled inputs — React ignores DOM-level value changes.

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
- Prefer targeted extraction over reading whole artifacts: `snapshot_search`, `snapshot_refs`, `web_query`, then `snapshot_show --ref`; whole `snapshot_show compact` is a fallback.
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
