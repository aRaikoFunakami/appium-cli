# App Management

App management commands operate through the active Appium session.

```bash
appium-cli get_current_app
appium-cli activate_app com.example.app
appium-cli terminate_app com.example.app
appium-cli restart_app com.example.app
appium-cli list_apps
appium-cli is_locked
appium-cli get_orientation
appium-cli set_orientation PORTRAIT
```

`list_apps` requires shell capability. Local external Appium servers may use adb fallback when safe.
