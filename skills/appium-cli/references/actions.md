# Actions

Action commands use refs from the latest snapshot. Refs are stable IDs like `tabbackground_4`, `login`, `btn_submit` (not sequential `e1`/`e2`).

When tapping, prefer clickable elements from the snapshot directly. If the target text is not clickable, tap the clickable parent, row, or adjacent button in the same container. Do not use `find_by_text` to re-search for something already visible in the snapshot.

Tap target decision tree:

1. If the desired target is a clickable button/list row ref, tap it directly.
2. If the desired target is visible text but not clickable, choose the clickable row/button near it in the same container.
3. If unsure which ref owns the bounds, run `appium-cli describe <ref>`.
4. After the action, run `snapshot` again before using another ref.

## Ref resolution

Each ref is resolved through multiple strategies with bounds verification:
1. **resource-id** → find element, verify bounds ±20px
2. **accessibility_id** (content-desc) → find element, verify bounds
3. **xpath** (text match) → find element, verify bounds
4. **coordinates** (center of bounds) → fallback

This ensures that even when multiple elements share the same resource-id (e.g. all tab buttons have `tabBackground`), the correct one is tapped.

```bash
appium-cli snapshot
appium-cli tap tabbackground_4
appium-cli type_text input_search "hello" --submit
appium-cli scroll_down recycler_view
appium-cli scroll_left rv_tab_menu
appium-cli swipe_left
appium-cli press_key back
appium-cli wait 1
```

## Safe scrolling

Prefer scoped scrolling with a ref:

```bash
appium-cli snapshot
appium-cli scroll_down main_content_scrollable_container
appium-cli snapshot
```

Use the container marked `[scrollable→vertical]` or `[scrollable→horizontal]` in the snapshot. Omitting the ref scrolls the full visible screen. Use no-ref only when you intend a full-screen scroll and no obvious scrollable container exists.

Directional aliases take an optional ref:

```bash
# Scroll inside a known container
appium-cli scroll_down recycler_view

# Scroll the whole visible screen
appium-cli scroll_down
```

For compatibility, `scroll <direction> --ref=<ref>` still works, but prefer `scroll_down <ref>` style in new workflows.

## Common mistakes

```bash
# Avoid legacy direction-first syntax in new workflows
appium-cli scroll up --ref=recycler_view

# Preferred
appium-cli scroll_down recycler_view
```

## WebView context actions

Actions are context-aware. When a `web_` ref is used, the driver switches to the ref's WebView context automatically. Web context uses Selenium methods instead of UiAutomator2 gesture scripts:

- `tap` / `click` → `element.click()`
- `type_text` / `fill` → `element.clear(); element.send_keys()`
- `select` → Selenium `Select` for HTML `<select>` elements
- `scroll_down/up` → `window.scrollBy()` JavaScript
- `press_key` → W3C key names (`Enter`, `Tab`, `ArrowDown`) instead of Android keycodes

Touch gestures (`long_press`, `double_tap`, `drag`, `fling_*`, `pinch_*`, `swipe_*`) are not supported in WebView context and fail with exit code 8. Switch to native context for these.

See [WebView reference](webview.md) for the full WebView workflow.
