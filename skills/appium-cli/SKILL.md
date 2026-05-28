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
appium-cli session start

appium-cli snapshot
appium-cli snapshot_actionable_tree
appium-cli web_refs
appium-cli tap btn_login
appium-cli snapshot_search "Welcome"

appium-cli session stop
```

**Session lifecycle rule:** Always create a fresh session at the start of each task and stop it when done. Do not reuse sessions across tasks — stale WebDriver state causes errors. One task = one session.

```bash
# Task start
appium-cli session stop    # clean up any leftover session
appium-cli session start

# ... do work ...

# Task end
appium-cli session stop
```

Default `snapshot` and `web_snapshot` output is compact metadata plus artifact links. Full trees live in files under `.appium-cli/snapshots/`. For native screens with tabs, menus, lists, or duplicate labels, inspect the operable hierarchy with `snapshot_actionable_tree` before tapping. For other targeted lookups, use `snapshot_search`, paginated `web_refs`, or `snapshot_show --ref`.

## Core workflow

The command set you use depends on the current context. Always match commands to context.

### Native context (default)

1. Observe: `appium-cli snapshot`.
2. Understand operable structure: `snapshot_actionable_tree` when the screen has tabs, menus, lists, duplicate labels, or ambiguous regions.
3. Extract detail if needed: `snapshot_search`, `web_refs`, or `snapshot_show --ref`.
4. Act: `tap <ref>`, `type_text <ref> <text>`, `scroll_down [ref]`.
5. Observe again after actions that may change the screen.
6. Use refs from the newest snapshot only.

### WebView context (after `webview_switch` or `goto`)

Once in a WebView context, **prefer WebDriver/WebView commands** over native touch workflows. Use native commands again only after `native_switch`, or for device-level actions that intentionally leave the page context.

| Task | Command to use |
|------|----------------|
| Navigate to URL | `appium-cli goto "https://..."` |
| Observe page | `appium-cli web_snapshot` |
| Find elements | `appium-cli web_refs latest ...`, `snapshot_search ...`, or `web_query "input,button,a" --attrs=...` |
| Click element | `appium-cli click web_<ref>` |
| Fill input | `appium-cli fill web_<ref> "text"` |
| Check current URL | `appium-cli webview_url` |
| Check page title | `appium-cli webview_title` |
| Back / Forward | `appium-cli go_back` / `appium-cli go_forward` |
| Reload | `appium-cli reload` |
| Return to native | `appium-cli native_switch` |

> **Rule**: After `webview_switch` succeeds, treat page-level work as web automation until `native_switch` is called. Refer to [WebView and Chrome](references/webview.md) for the full reference.

Do not read whole snapshot artifacts by default. Treat `.compact.yml` as a file artifact that preserves UI hierarchy outside the prompt. Pull relevant fragments with `snapshot_search`, `web_refs`, `web_query`, `snapshot_show --ref`, or local grep/rg-style extraction when available.

For piping, diffs, or full tree output, use global `--raw` before the command:

```bash
appium-cli --raw snapshot > before.yml
appium-cli tap btn_login
appium-cli --raw snapshot > after.yml
diff before.yml after.yml
```

Raw snapshot output is the tree content. Avoid raw snapshot output in agent context unless the user explicitly needs a full tree for piping/diffing.

For before/after verification, filter diffs to relevant lines instead of pasting whole files:

```bash
diff before.yml after.yml | grep -E "Qiita|検索|title|url|ref:"
```

## Observation commands

```bash
appium-cli snapshot                         # native metadata + artifacts
appium-cli snapshot main_list               # element-scoped native snapshot
appium-cli web_snapshot                     # WebView metadata + artifacts
appium-cli web_snapshot web_form            # element-scoped DOM snapshot
appium-cli web_text                         # readable WebView page/article text
appium-cli web_text --selector=article      # text from a specific content container
appium-cli web_eval "return Array.from(document.querySelectorAll('a[href*=\"/articles/\"]')).map(a=>({title:a.innerText.trim(),url:a.href})).slice(0,5)"  # structured DOM extraction
appium-cli --raw snapshot > screen.yml      # full tree for piping/diffing
appium-cli snapshot --filename=screen.yml   # save tree while printing metadata

appium-cli snapshot_actionable_tree         # native operable UI hierarchy
appium-cli snapshot_search "Storage" --role=row      # search saved artifact/index
appium-cli snapshot_search "ログイン" --or-text Login --or-text "Sign in"  # OR search
appium-cli web_refs latest --role=button        # list refs, paginated by default
appium-cli web_refs latest --role=button --offset=50  # next page when has_more=true
appium-cli snapshot_show latest --ref=btn_login      # targeted ref detail
appium-cli snapshot_show latest                      # targeted fallback; can be large
appium-cli snapshot_show latest --artifact=full      # debugging only
appium-cli generate_locator btn_login

appium-cli describe btn_login
appium-cli find_by_text "Log in"
appium-cli find_by_text "検索" --or-text Search      # OR search
appium-cli screenshot                       # rarely needed
appium-cli get_page_source                  # token-heavy diagnostic escape hatch
```

`snapshot` is primary for structure and refs. In native UI, `snapshot_actionable_tree` is the preferred low-token view for choosing what to operate because it preserves parent/child/sibling regions while showing only tappable/scrollable objects and required ancestors. Use `snapshot_search` as a targeted lookup after the hierarchy is understood; do not blindly tap the first search result when the same label appears in multiple containers. Use `web_text` when the task requires reading or summarizing WebView page/article/body text. Use `web_eval` for structured DOM extraction (ordered link lists, computed text, table data) — it works like Playwright's `browser_evaluate` and returns JSON for arrays/objects. Do not use `--depth` for normal full-page observations; snapshots are saved as artifacts, and depth can hide searchable targets. `web_refs` lists at most 50 refs by default and reports `has_more` / `next_offset`; request the next page or narrow the role/search instead of reading whole artifacts. Use `screenshot` only when visual pixels are necessary; reuse the returned artifact path and do not duplicate-save screenshots. Use `get_page_source` only for diagnostics when snapshot artifacts and `web_text` are insufficient.

For duplicate native labels such as a main tab and sub-tab both named "アプリ":

```bash
appium-cli snapshot
appium-cli snapshot_actionable_tree
appium-cli tap tabbtn_2
appium-cli snapshot
```

`--or-text` adds literal OR matching for text variants (synonyms, translations). It is not regex and does not support AND/NOT. Keep to 2-4 variants.

```bash
appium-cli console_messages                 # browser console logs
appium-cli console_messages --level error   # errors only
appium-cli network_requests                 # network requests (requires --enable-network-log)
appium-cli network_requests --filter "/api" # filter by URL
```

### depth parameter

`snapshot` and `web_snapshot` accept an optional `depth` parameter to limit the depth of the snapshot tree, but do not use it for normal full-page observations. By default, the full tree is saved to artifacts with no depth limit.

Depth is only a scoped/debug escape hatch when you intentionally want a smaller subtree. Token control should normally use `snapshot_search`, `snapshot_show --ref`, and paginated `web_refs`, not `depth`.

Depth counts only **semantic levels** (interactive elements, landmarks, headings, lists, tables) — layout wrappers like `<div>` and `<span>` are automatically flattened.

Do not set `depth` for normal observations — the default full artifact ensures all elements remain searchable. If the user explicitly asks for a smaller debug subtree, apply depth only to an already scoped snapshot.

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

To open a URL in Chrome or any WebView, use `goto`. It uses WebDriver's `driver.get()` and **auto-switches to WebView context** — no manual `webview_switch` needed:

```bash
appium-cli activate_app com.android.chrome
appium-cli goto "https://www.yahoo.co.jp"   # auto-switches to WebView + driver.get()
appium-cli web_snapshot
```

Do **not** try to find and interact with the address bar DOM element, use `web_eval window.location.href`, or use `tabs new --url` as a workaround when you simply want to navigate the current tab to a URL. Always use `goto` for that. Use tab commands when the task actually requires multiple tabs.

Full WebView workflow:

```bash
appium-cli list_contexts
appium-cli webview_switch
appium-cli web_snapshot
appium-cli goto "https://example.com"       # navigate; auto-switches to WebView
appium-cli go_back
appium-cli go_forward
appium-cli reload
appium-cli web_query "input,button,a" --attrs=name,type,placeholder,aria-label,data-testid,autocomplete
appium-cli web_eval "el.getAttribute('data-testid')" web_btn_submit
appium-cli click web_btn_submit
appium-cli fill web_search "query"
appium-cli native_switch
appium-cli tabs list                        # list WebView tabs
appium-cli tabs switch --index 1            # switch to tab
appium-cli tabs new --url "https://example.com"  # open new tab (embedded WebView only)
```

After any `fill`, **always take a `web_snapshot` before touching the next element or clicking a submit button**. Autocomplete suggestions, station dropdowns, or validation overlays may appear from regular `fill` (not just `--slowly`) — the previous snapshot is stale the moment transient UI may have changed the DOM. This is especially critical for station/address/location inputs (transit search, maps, etc.).

```bash
appium-cli fill web_via "品川"
appium-cli press_key escape                       # close autocomplete/dropdown if the typed value is enough
appium-cli web_snapshot                          # always: check for autocomplete
appium-cli click web_<matching_suggestion_ref>   # alternatively confirm if a visible option must be selected
```

Use `--slowly` when a site requires key-by-key input events (React-controlled inputs, search-as-you-type, comboboxes). The post-fill `web_snapshot` rule applies equally with or without `--slowly`:

```bash
appium-cli fill web_subjects "Comp" --slowly
appium-cli web_snapshot
appium-cli click web_option_computer_science
```

Do not use `web_eval` to set `.value` directly on controlled inputs — React and similar frameworks may ignore DOM-level value changes.

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

### External / host-side Appium server

`session start` can connect to an Appium server that is not local. Use either a CLI flag or the `APPIUM_SERVER_URL` env var:

```bash
appium-cli session start --server-url http://host.docker.internal:4723
# or
APPIUM_SERVER_URL=http://host.docker.internal:4723 appium-cli session start
```

External servers are treated as ownership `external` and are never stopped by `appium-cli`. This is the recommended way to run Chrome/WebView automation on Apple Silicon Mac with an arm64 Linux devcontainer (see [WebView and Chrome](references/webview.md) for why arm64 Linux Docker cannot launch ChromeDriver locally).

## Launch a known app

When you already know the package id of the target app (e.g. `com.android.chrome`), launch it directly with `activate_app` instead of taking a launcher/home-screen snapshot and tapping the app label. App icons on the launcher often surface only as text refs that are not actionable, which leads to wasted snapshot loops.

```bash
appium-cli activate_app com.android.chrome
appium-cli snapshot
```

For WebView work after launching Chrome:

```bash
appium-cli activate_app com.android.chrome
appium-cli list_contexts
appium-cli webview_switch
appium-cli web_snapshot
```

If the package id is unknown, use `appium-cli list_apps` to discover it (requires shell capability), then call `activate_app`. Do not loop on launcher snapshots searching for the icon.

## Important rules

- Keep `--raw` global: `appium-cli --raw snapshot`, not after the command.
- Prefer targeted extraction over reading whole artifacts: `snapshot_search`, `web_refs`, `web_query`, then `snapshot_show --ref`; whole `snapshot_show compact` is a fallback.
- Do not call `adb`, `appium`, `npm`, or installer commands directly unless the user explicitly asks.
- Prefer canonical snake_case tool names: `get_device_info`, `type_text`, `press_keycode`.
- Do not edit installed skill copies under `.agents/` or `~/.copilot/`; edit `skills/appium-cli/` and run `appium-cli install --skills`.

### WebView context rules (enforced after `webview_switch` or `goto`)

- **Use `goto` to navigate the current tab to a URL** — never tap the address bar, use `web_eval window.location.href`, or use `tabs new --url` as a workaround just to load a URL in the current tab.
- **Use `web_snapshot`** to observe the page — not `snapshot`.
- **Use `web_refs` / `snapshot_search` for refs from the latest `web_snapshot`; use `web_query` for CSS/attribute discovery.**
- **Use `fill`** to enter text in inputs — not `type_text` with a native ref.
- **Prefer `click web_<ref>`** to click links and buttons; avoid native touch/tap workflows unless intentionally interacting outside the DOM.
- **Use `webview_url` / `webview_title`** for quick URL/title checks before a full `web_snapshot`.
- **Use `go_back`, `go_forward`, `reload`** for browser navigation — not `press_key back`.
- **Use `tabs list`, `tabs switch`, `tabs new`, `tabs close`** for multi-tab workflows.
- After any navigation (`goto`, `go_back`, `go_forward`, `reload`), take a new `web_snapshot`; old refs are stale.
- **After every `fill`, take a `web_snapshot` before the next interaction.** Autocomplete suggestions or overlays can appear from any `fill` (not just `--slowly`) — station/address/location inputs are especially prone. If a suggestion is visible, click it to confirm. If none is needed, dismiss with `press_key Escape`. Do not click the next field or a submit button while a dropdown or overlay is still open. Do not bypass form input by assigning values with `web_eval`.

### Inspection-only shortcut: `web_form_url`

`appium-cli web_form_url "form[name=search]"` (or `web_form_url web_form_<ref>`) reports the form's submit URL/payload **without interacting with the page**. The CLI redacts hidden, password, token/csrf/otp-like, and `autocomplete=current-password|new-password|one-time-code|cc-number|cc-csc` fields; POST forms emit a payload summary instead of a URL.

When to use:

- ✅ Task says "get the result", "find the answer", "look up", "search and report": use after a normal `fill`/`click` attempt failed twice, or as a faster path for pure information retrieval.
- ✅ Debugging why a form submission did not produce the expected URL.
- ❌ Task says "test the form", "verify validation", or any frontend-behavior assertion: do **not** use; drive the form with `fill`/`click`/`select_option`/`wait_for` instead.

Every successful output includes `frontend_interaction_skipped: true`. Surface this in your final reply when the URL came from `web_form_url` rather than real interaction — never claim you tested the form.

### `web_eval` runtime warnings

`web_eval` now emits non-fatal `[warning]` lines on stderr when the script looks like:

- a navigation assignment (`window.location = ...`, `location.href = ...`, `history.pushState`) — use `appium-cli goto` instead.
- a direct DOM value injection (`.value = ...`, synthetic `input`/`change` event dispatch) — use `appium-cli fill` (or `fill --slowly`) so framework listeners fire.

Pass `--no-lint` only when you know the warning does not apply (e.g., reading `window.location.href`, not assigning to it).

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
