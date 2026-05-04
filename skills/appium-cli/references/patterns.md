# Common Patterns

Use these patterns as defaults. Observe first, act on refs from the latest snapshot, then verify.

## Launch an app and inspect it

```bash
appium-cli terminate_app com.example.app
appium-cli activate_app com.example.app
appium-cli snapshot
```

Use `terminate_app` only when a clean start is needed. Otherwise `activate_app` is enough.

## Tap a visible item

```bash
appium-cli snapshot
appium-cli tap btn_7
appium-cli snapshot
```

Choose the clickable row/button ref from the snapshot. If the visible label is a not-clickable text ref, tap the clickable parent, row, or adjacent button in the same container.

## Navigate a scrollable list

```bash
appium-cli snapshot
appium-cli scroll up --ref=recycler_view
appium-cli snapshot
appium-cli tap btn_12
```

Use the scrollable container ref marked `[scrollable→vertical]` or `[scrollable→horizontal]`. Do not tap a ref from before the scroll; run `snapshot` again and use the new current ref.

`scroll` is direction-first. Use `appium-cli scroll up --ref=recycler_view`, not `appium-cli scroll recycler_view up`.

## Settings/storage style workflow

```bash
appium-cli activate_app com.android.settings
appium-cli snapshot
appium-cli tap btn_7
appium-cli snapshot
```

If `Storage` is already visible, tap its associated clickable row/button directly. Do not scroll first unless the full snapshot shows that the target is not visible.

## Text input

```bash
appium-cli snapshot
appium-cli type_text input_search "hello" --submit
appium-cli snapshot
```

Use `type_text` with an input ref from the latest snapshot.

## WebView EditText fallback

Some WebView text fields cannot be targeted reliably by ref-based `type_text`. When that happens, use the legacy locator tool as a fallback:

```bash
appium-cli send_keys xpath "//android.widget.EditText" "hello"
appium-cli press_key enter
appium-cli snapshot
```

Prefer ref-based tools first. Use locator tools for compatibility and recovery.

## Recovery

```bash
appium-cli session stop
appium-cli session start
appium-cli snapshot
```

Use this when the session expires or the daemon loses the WebDriver session. If the screen is wrong, use `press_key back`, `activate_app`, or `restart_app`, then `snapshot` again.
