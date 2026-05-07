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

## WebView selector discovery

```bash
appium-cli webview_switch
appium-cli web_snapshot
appium-cli web_query "button, a, input" --attrs=name,type,placeholder,aria-label,data-testid,href
appium-cli web_eval "el.getAttribute('data-testid')" web_btn_submit
appium-cli generate_locator web_btn_submit
```

Use refs first. Use CSS selectors and generated locators as the second layer when refs need explanation or when writing a durable selector for later.

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
