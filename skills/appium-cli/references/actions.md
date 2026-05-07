# Actions

Actions use refs from the latest snapshot artifacts. Run `snapshot` or `web_snapshot`, choose a ref, act, then read the post-action snapshot metadata that normal action output appends.

```bash
appium-cli snapshot
appium-cli tap btn_login
# OK
# snapshot_id: native-after-...
# artifacts:
#   compact: .appium-cli/snapshots/...
```

The post-action artifact link is the next observation point. Use `snapshot_search`, `snapshot_refs`, or targeted `snapshot_show latest --ref=<ref>` to inspect it without taking another device snapshot.

## Raw action mode

Global `--raw` goes before the command:

```bash
appium-cli --raw tap btn_login
appium-cli --raw type_text input_search "hello"
```

Raw actions return only bare success/failure output and suppress post-action snapshot artifact metadata. Use raw mode for scripts; use normal mode for agent workflows.

## Ref-first action commands

```bash
appium-cli tap btn_login
appium-cli click web_btn_login
appium-cli type_text input_email "user@example.com" --submit
appium-cli fill web_search "query"
appium-cli select web_country "JP" --by=value
appium-cli press_key back
appium-cli wait 1
```

Target decision tree:

1. Use a visible ref from the latest snapshot or refs artifact.
2. If the label is text-only, tap the actionable parent row/button/container.
3. If there are duplicates, inspect `snapshot_show latest --ref=<ref>` or `snapshot_refs latest --role=<role>`.
4. After any action, use the new post-action snapshot artifacts before acting again.

## Scrolling and swiping

Prefer direction-specific aliases. The optional ref scopes the gesture; omitting it targets the full visible screen.

```bash
appium-cli scroll_down recycler_view
appium-cli scroll_up main_content
appium-cli scroll_down
appium-cli swipe_left carousel
appium-cli swipe_left
```

Use the container marked scrollable in the snapshot. Compatibility syntax still works but is not preferred: `appium-cli scroll down --ref=recycler_view`.

## Before/after diff workflow

Use raw snapshots to compare UI changes exactly:

```bash
appium-cli --raw snapshot > before.yml
appium-cli tap btn_expand
appium-cli --raw snapshot > after.yml
diff before.yml after.yml
```

Filter large diffs to relevant lines instead of reading entire files:

```bash
diff before.yml after.yml | grep -E "expanded|selected|visible|ref:"
```

For smaller diffs, scope the snapshot:

```bash
appium-cli --raw snapshot settings_panel --depth=3 > before.yml
appium-cli tap toggle_wifi
appium-cli --raw snapshot settings_panel --depth=3 > after.yml
diff before.yml after.yml
```

## WebView actions

Web refs (`web_...`) switch to the stored WebView context automatically:

```bash
appium-cli web_snapshot
appium-cli click web_btn_submit
appium-cli fill web_input_email "user@example.com"
appium-cli select web_country "JP" --by=value
appium-cli press_key Enter
```

Web actions use Selenium/DOM behavior. Touch gestures (`long_press`, `drag`, `pinch_*`, `fling_*`, native `swipe_*`) are not available in WebView context; switch to native if you need real touch gestures.

## Targeting layers

1. Snapshot refs first.
2. WebView CSS selectors/generated locators second (`web_query`, `generate_locator`).
3. Legacy locator tools only for expert recovery or smartestiroid compatibility.
