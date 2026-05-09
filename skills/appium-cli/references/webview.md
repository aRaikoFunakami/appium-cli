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
appium-cli snapshot_search "Search" --role=textbox
appium-cli snapshot_refs latest --role=textbox
appium-cli web_query "input,textarea,button,a" --attrs=name,type,placeholder,aria-label,data-testid
appium-cli snapshot_show latest --ref=web_search
appium-cli snapshot_show latest              # fallback; can be large
appium-cli snapshot_show latest --artifact=full  # debugging only
```

Do not read the full compact artifact just to find a DOM element. Use `web_query` for CSS/attribute extraction, `snapshot_search` for text, and `snapshot_refs` for ref indexes.

Use scoped snapshots for large pages:

```bash
appium-cli web_snapshot web_results --depth=4
appium-cli --raw web_snapshot web_form > form.yml
appium-cli web_snapshot web_dialog --filename=dialog.yml
```

## web_query for selector discovery

`web_query` queries the current WebView/Chrome DOM with CSS and reports compact element identity, generated selector, optional attrs, and any matching snapshot ref.

```bash
appium-cli web_query "input, textarea, select, button, a" --attrs=name,type,placeholder,aria-label,data-testid,autocomplete,aria-describedby
appium-cli web_query "input[name=q]" --limit=5
appium-cli --raw web_query "button" > buttons.json
```

Use it to discover inputs, buttons, selectors, values, and test attributes without reading `compact.yml`. Normal output puts key fields on one line (`ref`, `role`, `name`, `type`, `placeholder`, `aria-label`, `data-testid`, `href`, selector). Raw output is JSON for `jq` or scripts.

## Attribute inspection with web_eval

When a ref exists but you need a specific DOM attribute, pass the ref as the second argument. The resolved element is available as `el`:

```bash
appium-cli web_eval "el.getAttribute('data-testid')" web_btn_submit
appium-cli web_eval "el.getAttribute('aria-describedby')" web_input_email
appium-cli web_eval "el.value" web_search
```

Use `web_eval` for diagnostics and attribute reads. Prefer ref actions for normal interaction.

## Targeting layers

1. **Refs first**: use `web_...` refs from `web_snapshot`/`snapshot_refs` with `click`, `fill`, `select`, `select_option`, `set_date`, and `press_key`.
2. **CSS/locator second**: use `css:` prefix (e.g. `appium-cli click "css:#submit"`) or `web_query` to discover CSS selectors and `generate_locator <ref>` to extract the best selector stored for a ref.
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
appium-cli select_option web_state "NCR"
appium-cli set_date web_dateofbirthinput "15 May 1990"
appium-cli scroll_down
appium-cli press_key Enter
```

WebView actions use Selenium methods and JavaScript scrolling. Native touch-only gestures are not supported in WebView context and fail with exit code 8.

## Navigation and dialogs

`goto` and other navigation commands auto-switch to WebView context if needed. No manual `webview_switch` is required before `goto`.

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

## Console messages

Read browser console logs from the WebView:

```bash
appium-cli console_messages
appium-cli console_messages --level error
appium-cli console_messages --level warning
```

Uses `driver.get_log('browser')`. Note: each call consumes (clears) the returned entries.

## Tab management

List, switch, close, and open WebView tabs/windows:

```bash
appium-cli tabs list
appium-cli tabs switch --index 1
appium-cli tabs close --index 0
appium-cli tabs new --url "https://example.com"
```

Uses `driver.window_handles` and `driver.switch_to.window()`. In embedded WebViews, tab creation depends on the app's `onCreateWindow()` implementation. CHROMIUM context (Chrome browser) fully supports multi-tab.

## Network requests

Capture and list HTTP requests made by the WebView page. Requires the session to be started with `--enable-network-log`:

```bash
appium-cli session start --enable-network-log
appium-cli goto "https://example.com"
appium-cli network_requests
appium-cli network_requests --filter "/api/"
appium-cli network_requests --static
```

Output is a numbered list (similar to Playwright `browser_network_requests`):

```
1. GET 200 https://example.com/ (text/html)
2. POST 201 https://example.com/api/data (application/json)
```

Static resources (images, fonts, scripts, stylesheets) are excluded by default. Use `--static` to include them. Use `--filter` to match URLs by regexp.

Note: `get_log("performance")` is consumptive — each call returns only new entries since the last call.

## Raw and diff workflow

```bash
appium-cli --raw web_snapshot > before.yml
appium-cli click web_btn_expand
appium-cli --raw web_snapshot > after.yml
diff before.yml after.yml
```

Filter large diffs to the lines that matter:

```bash
diff before.yml after.yml | grep -E "Qiita|検索|title|url|ref:"
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
