# WebView and Chrome automation

Use WebView snapshots and refs first, then CSS selectors/locators when refs are not enough. Legacy native locator tools are not the normal WebView workflow.

## Context workflow

```bash
appium-cli list_contexts
appium-cli webview_switch
appium-cli web_snapshot
appium-cli snapshot_refs latest --role=textbox
appium-cli click web_btn_login
appium-cli native_switch
```

`web_snapshot` normal output is compact metadata plus artifact links. The full DOM tree is in `.appium-cli/snapshots/*.full.yml`; refs and locator strategies are in `*.refs.json`.

## Inspect DOM artifacts

```bash
appium-cli web_snapshot
appium-cli snapshot_show latest
appium-cli snapshot_show latest --artifact=full
appium-cli snapshot_refs latest
appium-cli snapshot_search "Search" --role=textbox
appium-cli snapshot_show latest --ref=web_search
```

Use scoped snapshots for large pages:

```bash
appium-cli web_snapshot web_results --depth=4
appium-cli --raw web_snapshot web_form > form.yml
appium-cli web_snapshot web_dialog --filename=dialog.yml
```

## web_query for selector discovery

`web_query` queries the current WebView/Chrome DOM with CSS and reports compact element identity, generated selector, optional attrs, and any matching snapshot ref.

```bash
appium-cli web_query "input, textarea, select, button, a" --attrs=data-testid,autocomplete,aria-describedby
appium-cli web_query "input[name=q]" --limit=5
appium-cli --raw web_query "button" > buttons.json
```

Use it to discover inputs, buttons, selectors, and test attributes when the snapshot tree is too compact or when you need a CSS selector for a second-layer target.

## Attribute inspection with web_eval

When a ref exists but you need a specific DOM attribute, pass the ref as the second argument. The resolved element is available as `el`:

```bash
appium-cli web_eval "el.getAttribute('data-testid')" web_btn_submit
appium-cli web_eval "el.getAttribute('aria-describedby')" web_input_email
appium-cli web_eval "el.value" web_search
```

Use `web_eval` for diagnostics and attribute reads. Prefer ref actions for normal interaction.

## Targeting layers

1. **Refs first**: use `web_...` refs from `web_snapshot`/`snapshot_refs` with `click`, `fill`, `select`, and `press_key`.
2. **CSS/locator second**: use `web_query` to discover CSS selectors and `generate_locator <ref>` to extract the best selector stored for a ref.
3. **Legacy locators last**: use locator tools only for expert recovery or compatibility.

```bash
appium-cli web_snapshot
appium-cli generate_locator web_btn_submit
appium-cli --raw generate_locator web_btn_submit
```

## WebView actions

```bash
appium-cli click web_btn_login
appium-cli tap web_btn_login
appium-cli fill web_search "query"
appium-cli type_text web_search "query" --submit
appium-cli select web_country "JP" --by=value
appium-cli scroll_down
appium-cli press_key Enter
```

WebView actions use Selenium methods and JavaScript scrolling. Native touch-only gestures are not supported in WebView context and fail with exit code 8.

## Navigation and dialogs

```bash
appium-cli goto "https://example.com"
appium-cli go_back
appium-cli go_forward
appium-cli reload
appium-cli webview_url
appium-cli webview_title
appium-cli dialog_text
appium-cli dialog_accept
appium-cli dialog_dismiss
```

After navigation or reload, take a new `web_snapshot`; old web refs may be stale.

## Raw and diff workflow

```bash
appium-cli --raw web_snapshot > before.yml
appium-cli click web_btn_expand
appium-cli --raw web_snapshot > after.yml
diff before.yml after.yml
```

Use element-scoped raw snapshots for smaller diffs:

```bash
appium-cli --raw web_snapshot web_panel --depth=3 > before.yml
appium-cli click web_toggle
appium-cli --raw web_snapshot web_panel --depth=3 > after.yml
diff before.yml after.yml
```

## Prerequisites and diagnostics

WebView automation requires WebView debugging, a compatible Chromedriver, and an Appium server configured for WebView automation. Use `appium-cli webview_status`.

`get_page_source --context=webview` returns raw HTML and can be token-heavy. Use it only when `web_snapshot`, `web_query`, and artifact commands are insufficient.
