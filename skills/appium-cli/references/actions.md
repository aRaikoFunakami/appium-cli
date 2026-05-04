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
appium-cli scroll up --ref=recycler_view
appium-cli scroll left --ref=rv_tab_menu
appium-cli swipe left
appium-cli press_key back
appium-cli wait 1
```

## Safe scrolling

Prefer scoped scrolling with `--ref`:

```bash
appium-cli snapshot
appium-cli scroll up --ref=main_content_scrollable_container
appium-cli snapshot
```

Use the container marked `[scrollable→vertical]` or `[scrollable→horizontal]` in the snapshot. Omitting `--ref` scrolls from a generic screen area and may target the wrong region or trigger system UI such as notifications/quick settings.

For `scroll`, directions are finger movement directions. `scroll up` is a finger-up gesture and usually reveals lower list content; `scroll down` moves back toward the top. Internally Appium `scrollGesture` receives the reversed content direction.
