# Common Patterns

Default loop: observe with artifact-first snapshot, inspect artifacts, act on refs, then use the post-action snapshot artifact.

## Observe, act, inspect post-action snapshot

```bash
appium-cli snapshot
appium-cli snapshot_refs latest --role=button
appium-cli tap btn_login
appium-cli snapshot_search "Welcome"
```

Normal actions append the new snapshot metadata. Do not reuse refs from before navigation, scrolling, dialogs, or screen changes.

## Before/after diff

```bash
appium-cli --raw snapshot > before.yml
appium-cli tap btn_expand
appium-cli --raw snapshot > after.yml
diff before.yml after.yml
```

If the diff is large, filter it locally and read only relevant lines:

```bash
diff before.yml after.yml | grep -E "expanded|selected|visible|ref:"
```

For WebView:

```bash
appium-cli --raw web_snapshot > before.yml
appium-cli click web_btn_expand
appium-cli --raw web_snapshot > after.yml
diff before.yml after.yml
```

For focused diffs:

```bash
appium-cli --raw snapshot settings_panel --depth=3 > before.yml
appium-cli tap toggle_wifi
appium-cli --raw snapshot settings_panel --depth=3 > after.yml
diff before.yml after.yml
```

## Search a large screen without refreshing

```bash
appium-cli snapshot
appium-cli snapshot_search "Storage"
appium-cli snapshot_refs latest --role=row
appium-cli snapshot_show latest --ref=storage_row
appium-cli tap storage_row
```

`snapshot_search`, `snapshot_refs`, and `snapshot_show --ref` read persisted artifacts. They do not query the device. Prefer these targeted commands over reading the whole compact tree.

## Navigate a scrollable list

```bash
appium-cli snapshot
appium-cli snapshot_refs latest --role=list
appium-cli scroll_down recycler_view
appium-cli snapshot_search "Settings"
appium-cli tap row_settings
```

Use scoped scrolling with the scrollable container ref. Omit the ref only for intentional full-screen scrolling.

## Text input

```bash
appium-cli snapshot
appium-cli snapshot_refs latest --role=textbox
appium-cli type_text input_search "hello" --submit
appium-cli snapshot_search "hello"
```

For WebView forms, use `web_query` if inputs are hard to identify:

```bash
appium-cli web_snapshot
appium-cli web_query "input,textarea,select" --attrs=name,type,placeholder,aria-label,data-testid,autocomplete
appium-cli fill web_search "query"
```

## Slow typing and transient UI

Use `--slowly` when a site needs real key-by-key input events (autocomplete, comboboxes, validation, search-as-you-type, React-controlled inputs, etc.):

```bash
appium-cli web_snapshot
appium-cli fill web_search "query" --slowly
```

After slow typing, the site may show suggestions, dropdowns, validation UI, or nothing at all. Before moving to another field or button, observe and stabilize the UI when needed. Do not use `web_eval` to set values directly on controlled inputs.

### If suggestions/options appear

Click the matching option ref to confirm the value and close the transient UI before continuing:

```bash
appium-cli fill web_first_input "first value" --slowly
appium-cli web_snapshot
appium-cli click web_<matching_first_option_ref>

appium-cli fill web_second_input "second value" --slowly
appium-cli web_snapshot
appium-cli click web_<matching_second_option_ref>
```

### If no option must be selected but UI remains open

Dismiss the dropdown/overlay before moving on:

```bash
appium-cli fill web_first_input "first value" --slowly
appium-cli web_snapshot
appium-cli press_key Escape

appium-cli fill web_second_input "second value" --slowly
appium-cli web_snapshot
appium-cli press_key Escape
```

### If no transient UI is visible

Continue normally:

```bash
appium-cli fill web_first_input "first value" --slowly
appium-cli web_snapshot
appium-cli fill web_second_input "second value" --slowly
```

Do not start interacting with another element while a previous dropdown or overlay is still open. If the next element is not clickable after slow typing, inspect with `web_snapshot` and resolve the overlay before retrying.

For React Select / autocomplete inputs, this commonly looks like:

```bash
appium-cli fill web_subjects "Comp" --slowly
appium-cli web_snapshot
appium-cli click web_option_computer_science
```

## Chrome / Web browser automation

After switching to WebView, prefer WebDriver/WebView commands for page-level work. Do not fall back to native `snapshot` or touch workflows for DOM interaction unless you intentionally return to native context.

```bash
# Open Chrome and navigate
appium-cli activate_app com.android.chrome
appium-cli goto "https://www.yahoo.co.jp"   # auto-switches to WebView + driver.get()
appium-cli webview_title                    # quick check: title without full snapshot
appium-cli webview_url                      # quick check: current URL

# Observe and interact
appium-cli web_snapshot
appium-cli snapshot_refs latest --role=textbox
appium-cli fill web_search "appium"
appium-cli press_key Enter
appium-cli web_snapshot

# Navigate
appium-cli go_back
appium-cli go_forward
appium-cli reload

# Return to native
appium-cli native_switch
appium-cli snapshot
```

**Command mapping** — native vs web context:

| Goal | Native context | WebView context |
|------|---------------|-----------------|
| Observe screen | `snapshot` | `web_snapshot` |
| Find elements | `snapshot_search`, `snapshot_show --ref`, narrow `snapshot_refs` | `snapshot_search`, `snapshot_show --ref`, narrow `snapshot_refs`; `web_query` only for CSS/href fallback |
| Click | `tap <ref>` | Prefer `click web_<ref>` |
| Type text | `type_text <ref> "text"` | `fill web_<ref> "text"` |
| Navigate | — | `goto "https://..."` |
| New tab | — | `tabs new --url "https://..."` |
| Browser back | — | `go_back` |
| Check URL/title | — | `webview_url` / `webview_title` |

Use refs first. Use CSS selectors, `web_query`, and `generate_locator web_<ref>` as the second layer when refs need explanation or when writing a durable selector for later.

## Launch a known app

Prefer `activate_app <package>` over tapping the app icon on the launcher. App icons on Android launchers are commonly exposed only as text elements, not actionable refs, so snapshot-driven taps will loop.

```bash
appium-cli activate_app com.android.chrome
appium-cli snapshot
appium-cli webview_switch                 # only if doing WebView work
appium-cli web_snapshot
```

For an unknown package id:

```bash
appium-cli list_apps | grep -i chrome
appium-cli activate_app com.android.chrome
```

## Launch or reset an app

```bash
appium-cli activate_app com.example.app
appium-cli snapshot
```

Use `terminate_app` or `restart_app` only when a clean start is required:

```bash
appium-cli restart_app com.example.app
appium-cli snapshot
```

## Recovery

```bash
appium-cli session status
appium-cli session stop
appium-cli session start
appium-cli snapshot
```

If the UI is wrong, use `press_key back`, `activate_app`, or `restart_app`, then observe again. Avoid legacy locator fallbacks until snapshot refs, WebView refs, and CSS/locator discovery have failed.

Do not loop on launcher snapshots to find an app icon. If `snapshot_refs` does not return an actionable ref for the app you want to start, switch to `activate_app <package>`.
