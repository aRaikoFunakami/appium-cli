# App Management

App management commands operate through the active Appium session. Observe with `snapshot` after changing app state; normal action/app outputs that change UI may provide post-action snapshot artifacts where supported.

```bash
appium-cli get_current_app
appium-cli activate_app com.example.app
appium-cli terminate_app com.example.app
appium-cli restart_app com.example.app
appium-cli list_apps
appium-cli is_locked
appium-cli get_orientation
appium-cli set_orientation PORTRAIT
appium-cli snapshot
```

Use `activate_app` for normal app switching, including the first launch of a known app such as Chrome. Do not search a launcher snapshot for the app icon — launcher labels are usually text-only refs that are not actionable. Use `terminate_app` or `restart_app` only when a clean state is required, then take a fresh `snapshot` before choosing refs.

```bash
appium-cli activate_app com.android.chrome
appium-cli snapshot
appium-cli webview_switch
appium-cli web_snapshot
```

`list_apps` requires shell capability. Local external Appium servers may use safe adb fallback; remote external servers without shell support fail with exit code 8.
