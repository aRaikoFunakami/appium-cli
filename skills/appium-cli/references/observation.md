# Observation

Use observation commands to inspect the current Android screen and get refs for actions.

```bash
appium-cli snapshot
appium-cli snapshot --scope=inputs
appium-cli describe tabbackground_4
appium-cli find_by_text "Log in"
appium-cli screenshot
appium-cli get_page_source
```

## Ref naming

Refs are stable IDs derived from the element's resource-id, content-desc, or role+name:

- `resource-id="com.example:id/login"` → `login`
- `content-desc="Search"` → `search`
- `role=button, name="Submit"` → `btn_submit`

When multiple elements share the same resource-id (e.g. tab buttons), suffixes `_2`, `_3`, `_4` are appended to keep refs unique.

## Snapshot output

The snapshot includes:
- **Layout summary**: visual map of containers with element counts
- **Containers**: semantic regions (topbar, list, tabs, overlay, content)
- **Elements**: `[ref:xxx] role "name" [state] (position_hint)`
- **Alerts**: detected toasts/dialogs
- **Nav**: back button availability

Read the full snapshot before choosing a ref. A filtered search can hide the clickable parent, the scrollable container, or nearby duplicate labels.

Example:

```text
┌ [ref:collapsing_toolbar] topbar
└ [ref:recycler_view] list [scrollable→vertical]
    text(2): "Storage", "83% used - 1.37 GB free"
    button(8): "", "", ...

── [ref:recycler_view] list [scrollable→vertical] ──
[ref:btn_7] button ""
[ref:title_7] text "Storage"
[ref:summary_7] text "83% used - 1.37 GB free"
```

How to use this output:

- `recycler_view` is the scrollable list container. Use it for scoped scrolling: `appium-cli scroll up --ref=recycler_view`.
- `title_7` is visible text, but it may not be the tappable target.
- `btn_7` is the associated clickable row/button ref. Prefer it for `tap`.
- Refs come from the latest snapshot only. After a tap, scroll, back, dialog, or app switch, run `snapshot` again before reusing refs.
- Position hints such as `(left-most)` or `(right-most)` help disambiguate repeated controls.

If a desired label is not clickable, inspect the nearby row/button/container in the same snapshot instead of tapping the text ref directly.

Prefer `snapshot` and refs before taking screenshots. `screenshot` returns the smartestiroid-compatible JSON string containing `type`, `image_base64`, `region`, and saves a PNG file under `.appium-cli/session-XXXX/`.
