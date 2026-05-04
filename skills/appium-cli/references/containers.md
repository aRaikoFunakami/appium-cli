# Containers and Verification

Use container tools when the same text appears in multiple areas.

```bash
appium-cli snapshot
appium-cli list_containers
appium-cli find_container "Settings"
appium-cli within_container c2 --role=button
appium-cli assert_visible --text "Log in"
appium-cli assert_visible --ref btn_login
```

`assert_visible` is intended to prevent hallucinated UI assumptions before and after actions.
