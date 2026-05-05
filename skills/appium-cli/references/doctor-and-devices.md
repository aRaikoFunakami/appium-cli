# Doctor and Devices

Use these commands before starting a mobile automation session.

```bash
appium-cli doctor
appium-cli doctor --json
appium-cli devices
appium-cli devices --platform android
appium-cli devices --platform ios
appium-cli devices --json
```

`doctor` observes the environment and reports `PASS`, `WARN`, or `FAIL`. It never installs or fixes tools.

`devices` observes `adb devices -l` for Android and `xcrun` on macOS for iOS/simulator information. Android automation commands require an Android device with status `device`.
