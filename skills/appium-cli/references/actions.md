# Actions

Action commands use refs from the latest snapshot.

```bash
appium-cli snapshot
appium-cli tap e12
appium-cli type_text e8 "hello" --submit
appium-cli scroll up
appium-cli scroll up --ref=e20
appium-cli swipe left
appium-cli press_key back
appium-cli wait 1
```

For `scroll`, directions are finger movement directions. Internally Appium `scrollGesture` receives the reversed content direction.
