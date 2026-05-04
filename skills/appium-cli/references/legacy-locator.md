# Legacy Locator Tools

Use legacy locator tools when refs are not enough or when reproducing smartestiroid locator-based workflows.

```bash
appium-cli find_element xpath "//*"
appium-cli click_element id "com.example:id/button"
appium-cli get_text accessibility_id "Login"
appium-cli press_keycode 4
appium-cli double_tap --by=xpath --value="//*[@text='Login']"
appium-cli send_keys xpath "//*[@class='android.widget.EditText']" "hello"
appium-cli wait_short_loading 5
appium-cli scroll_element xpath "//*[@scrollable='true']" --direction=up
appium-cli scroll_to_element xpath "//*[@text='Target']"
```

Prefer snapshot refs for new workflows. Keep locator tools for compatibility and low-level recovery.

## Common mistakes

Legacy locator tools use `<by> <value>` as positionals. Extra behavior such as scroll direction is an option.

```bash
# Wrong
appium-cli scroll_element xpath "//*[@scrollable='true']" up

# Right
appium-cli scroll_element xpath "//*[@scrollable='true']" --direction=up
```
