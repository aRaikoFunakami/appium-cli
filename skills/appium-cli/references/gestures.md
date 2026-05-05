# Gestures

Gesture commands also use refs from `snapshot`.

```bash
appium-cli long_press btn_photo
appium-cli double_tap btn_photo
appium-cli drag btn_photo 500 900
appium-cli fling_up
appium-cli fling_down recycler_view
appium-cli pinch_open image_preview
appium-cli pinch_close image_preview
```

Use gestures only when simpler actions such as `tap`, `type_text`, or `scroll` are insufficient.

## Directional gestures

Use direction-specific aliases. The optional ref scopes the gesture; omitting ref gestures on the full visible screen.

```bash
# Full-screen fling
appium-cli fling_up

# Fling inside a container
appium-cli fling_down recycler_view
```

Compatibility command `fling <direction> --ref=<ref>` still works, but prefer `fling_down <ref>` style in new workflows.
