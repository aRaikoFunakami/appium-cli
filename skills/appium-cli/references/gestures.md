# Gestures

Use gestures only when simpler ref actions (`tap`, `type_text`, `scroll_down`) are insufficient. Gesture commands use refs from the latest snapshot artifacts and normal output appends a post-gesture snapshot artifact link.

```bash
appium-cli snapshot
appium-cli long_press btn_photo
appium-cli double_tap btn_photo
appium-cli drag btn_photo 500 900
appium-cli fling_down recycler_view
appium-cli pinch_open image_preview
appium-cli snapshot_show latest
```

## Directional gestures

Direction-specific aliases take an optional ref. With a ref, the gesture is scoped; without a ref, it applies to the full visible screen.

```bash
appium-cli fling_up
appium-cli fling_down recycler_view
appium-cli swipe_left carousel
appium-cli swipe_left
```

Compatibility forms such as `fling down --ref=recycler_view` still work, but prefer `fling_down recycler_view` in new workflows.

## Raw mode and diffs

Raw gestures suppress post-action snapshot metadata:

```bash
appium-cli --raw swipe_left carousel
```

For verification, diff raw snapshots before and after:

```bash
appium-cli --raw snapshot carousel --depth=2 > before.yml
appium-cli swipe_left carousel
appium-cli --raw snapshot carousel --depth=2 > after.yml
diff before.yml after.yml
```

## WebView limitation

Native touch gestures (`long_press`, `double_tap`, `drag`, `fling_*`, `pinch_*`, `swipe_*`) are not supported in WebView context. Use WebView ref actions (`click`, `fill`, `select`) or JavaScript diagnostics via `web_eval`; switch to native for real touch gestures.
