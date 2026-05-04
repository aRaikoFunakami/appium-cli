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

Prefer `snapshot` and refs before taking screenshots. `screenshot` returns the smartestiroid-compatible JSON string containing `type`, `image_base64`, `region`, and saves a PNG file under `.appium-cli/session-XXXX/`.
