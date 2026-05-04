# Actions

Action commands use refs from the latest snapshot. Refs are stable IDs like `tabbackground_4`, `login`, `btn_submit` (not sequential `e1`/`e2`).

When tapping, prefer `[clickable]` elements from the snapshot directly. If the target you want to tap is `[not-clickable]`, look for its clickable parent in the snapshot and tap that instead. Do not use `find_by_text` to re-search for something already visible in the snapshot.

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
appium-cli scroll up
appium-cli scroll up --ref=rv_tab_menu
appium-cli swipe left
appium-cli press_key back
appium-cli wait 1
```

For `scroll`, directions are finger movement directions. Internally Appium `scrollGesture` receives the reversed content direction.
