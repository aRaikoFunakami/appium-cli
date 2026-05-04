# Observation

Use observation commands to inspect the current Android screen and get refs for actions.

```bash
appium-cli snapshot
appium-cli snapshot --scope=inputs
appium-cli describe e12
appium-cli find_by_text "Log in"
appium-cli screenshot
appium-cli get_page_source
```

Prefer `snapshot` and refs before taking screenshots. `screenshot` returns the smartestiroid-compatible JSON string containing `type`, `image_base64`, `region`, and saves a PNG file under `.appium-cli/session-XXXX/`. The `path`, `size_bytes`, and `mime_type` fields are included in the response when a session is active.
