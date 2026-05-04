# Gestures

Gesture commands also use refs from `snapshot`.

```bash
appium-cli long_press btn_photo
appium-cli double_tap btn_photo
appium-cli drag btn_photo 500 900
appium-cli fling up
appium-cli fling down --ref=recycler_view
appium-cli pinch_open image_preview
appium-cli pinch_close image_preview
```

Use gestures only when simpler actions such as `tap`, `type_text`, or `scroll` are insufficient.

## Argument order

Most gesture commands are ref-first, but `fling` is direction-first:

```bash
# Wrong
appium-cli fling recycler_view down

# Right
appium-cli fling down --ref=recycler_view
```
