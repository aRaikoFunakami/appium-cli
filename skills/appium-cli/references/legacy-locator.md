# Legacy Locator Tools

Legacy locator tools are expert-only recovery and smartestiroid compatibility tools. They are not primary guidance for new appium-cli workflows.

Use this order first:

1. Snapshot refs from `snapshot` / `web_snapshot`.
2. Artifact inspection with `snapshot_refs`, `snapshot_search`, and `snapshot_show`.
3. WebView CSS/locator discovery with `web_query` and `generate_locator`.
4. Legacy locators only if the above cannot target the element.

## Expert-only commands

```bash
appium-cli find_element xpath "//*[@text='Login']"
appium-cli click_element id "com.example:id/button"
appium-cli get_text accessibility_id "Login"
appium-cli send_keys xpath "//*[@class='android.widget.EditText']" "hello"
appium-cli press_keycode 4
appium-cli scroll_element xpath "//*[@scrollable='true']" --direction=up
appium-cli scroll_to_element xpath "//*[@text='Target']"
```

Avoid `wait_short_loading` in normal workflows. Prefer explicit observation with `snapshot`, action post-snapshot artifacts, `assert_visible`, or `wait` followed by a fresh snapshot.

## Common mistakes

Legacy locator tools use `<by> <value>` positionals. Extra behavior such as scroll direction is an option.

```bash
# Wrong
appium-cli scroll_element xpath "//*[@scrollable='true']" up

# Right
appium-cli scroll_element xpath "//*[@scrollable='true']" --direction=up
```

When a legacy command succeeds, return to the artifact-first loop immediately:

```bash
appium-cli snapshot
appium-cli snapshot_refs latest
```
