# WebView and Chrome automation

Use WebView snapshots and refs first, then CSS selectors/locators when refs are not enough. Legacy native locator tools are not the normal WebView workflow.

## Quick reference — page-level commands in WebView context

Once `webview_switch` or `goto` succeeds, prefer these WebDriver/WebView commands for page-level work until `native_switch`:

```bash
# Observe
appium-cli web_snapshot                     # primary observation
appium-cli webview_url                      # current URL (fast, no snapshot)
appium-cli webview_title                    # page title (fast, no snapshot)
appium-cli web_refs latest             # refs from the latest web_snapshot, first page
appium-cli web_refs latest --offset=50 # next page when has_more=true
appium-cli snapshot_search "Search"         # search the latest web_snapshot artifact
appium-cli web_query "input,button,a" --attrs=name,type,placeholder,aria-label

# Act on refs
appium-cli click web_<ref>
appium-cli fill web_<ref> "text"
appium-cli select web_<ref> "value"
appium-cli press_key Enter

# Navigate (WebDriver native — always prefer over DOM manipulation)
appium-cli goto "https://..."
appium-cli go_back
appium-cli go_forward
appium-cli reload

# Tabs
appium-cli tabs list
appium-cli tabs switch --index 1
appium-cli tabs new --url "https://example.com"
appium-cli tabs close --index 1

# Dialogs
appium-cli dialog_accept
appium-cli dialog_dismiss

# Debug
appium-cli console_messages
appium-cli web_eval "document.title"
```

## Open a URL (Chrome / WebView)

`goto` is the standard WebDriver navigation command. It calls `driver.get(url)` and **auto-switches to WebView context** if the current context is native:

```bash
appium-cli activate_app com.android.chrome
appium-cli goto "https://www.yahoo.co.jp"   # auto-switches to WebView + driver.get()
appium-cli web_snapshot
```

Do **not** use `web_eval window.location.href`, try to tap the address bar, or use `tabs new --url` as a workaround when you simply want to navigate the current tab to a URL. Always use `goto` for that. Use `tabs new --url` when the task actually requires opening a new tab.

> Runtime guard: `web_eval` emits a non-fatal `[warning]` on stderr if the script string looks like `window.location =`, `location.href =`, or `history.pushState/replaceState`. Use `goto` instead, or pass `--no-lint` if you are only *reading* `window.location.href`.

## Inspecting a form's submit URL safely

When you only need to know *where a form would submit* (typical for task-completion shortcuts and debugging), use `web_form_url` instead of building a payload from `web_eval`:

```bash
appium-cli web_form_url "form[name=search]"
# or, with a ref from web_snapshot:
appium-cli web_form_url web_form_search
appium-cli web_form_url "form[name=search]" --names-only        # field names only, no values, no URL
appium-cli web_form_url "form[name=search]" --max-fields=200    # large forms
appium-cli --raw web_form_url "form[name=search]"               # full structured JSON
```

Properties:

- **Read-only.** No submit, no click, no DOM mutation, no navigation.
- **Redacts secrets by default.** Hidden inputs, `type=password`, fields whose name/id/label/placeholder/aria-label match `password`, `token`, `csrf`, `xsrf`, `nonce`, `secret`, `auth`, `session`, `cookie`, `credential`, `api_key`, `apikey`, `access_key`, `private`, `otp`, `mfa`, `2fa`, `verification_code`, and `autocomplete=current-password|new-password|one-time-code|cc-number|cc-csc` are emitted as `[REDACTED]`. There is no `--unredact` / `--show-secrets` option.
- **GET forms:** produces a navigable URL with non-sensitive values URL-encoded.
- **POST / `javascript:` / `mailto:` / non-http actions:** produces a payload summary only; never a URL.
- **Cross-origin actions:** still produces a URL, with a `cross_origin_action` warning.
- **Always** includes `frontend_interaction_skipped: true` and a bypass warning. When you use the result in your final reply, state plainly that the form was not actually exercised.

Decision rule:

- ✅ "Get the result", "look up X", "search and report": OK as a shortcut, especially after `fill`/`click` failed twice on the same form.
- ❌ "Test the form", "verify validation", "check submit handler", "check autocomplete": do NOT use `web_form_url`; drive the form with `fill`/`click`/`select_option`/`wait_for`.

## Context workflow

```bash
appium-cli list_contexts
appium-cli webview_switch
appium-cli goto "https://example.com"
appium-cli web_snapshot
appium-cli web_refs latest --role=textbox
appium-cli click web_btn_login
appium-cli native_switch
```

`web_snapshot` normal output is compact metadata plus artifact links. The full DOM tree is in `.appium-cli/snapshots/*.full.yml`; refs and locator strategies are in `*.refs.json`.

## Inspect DOM artifacts

```bash
appium-cli web_snapshot
appium-cli snapshot_search "Search" --role=textbox
appium-cli web_refs latest --role=textbox
appium-cli web_query "input,textarea,button,a" --attrs=name,type,placeholder,aria-label,data-testid
appium-cli snapshot_show latest --ref=web_search
appium-cli snapshot_show latest              # fallback; can be large
appium-cli snapshot_show latest --artifact=full  # debugging only
```

Do not read the full compact artifact just to find a DOM element. Use `web_query` for CSS/attribute extraction, `snapshot_search` for text, and `web_refs` for ref indexes.

Use scoped snapshots for large pages; avoid `--depth` unless you intentionally want a smaller debug subtree:

```bash
appium-cli web_snapshot web_results
appium-cli web_snapshot web_form --filename=form.yml
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

## DOM extraction with web_eval (Playwright browser_evaluate equivalent)

Use `web_eval` for read-only structured DOM extraction when snapshot_search/web_query cannot provide the needed data directly. Returns JSON for arrays/objects.

```bash
# Extract ordered article links as JSON array
appium-cli web_eval "return Array.from(document.querySelectorAll('a[href*=\"/articles/\"]')).map(a=>({title:a.innerText.trim(),url:a.href})).filter(x=>x.title).slice(0,5)"

# Extract page body text
appium-cli web_eval "return (document.querySelector('article')||document.querySelector('main')||document.body).innerText"

# Extract table data
appium-cli web_eval "return Array.from(document.querySelectorAll('table tr')).map(r=>Array.from(r.cells).map(c=>c.innerText))"
```

Prefer `web_eval` over keyword-based `snapshot_search` when:
- You need an ordered list of links/items matching a CSS pattern
- You need computed text content from a specific container
- Keyword matching would conflate category discovery with article selection

Use `web_eval` for diagnostics and attribute reads. Prefer ref actions for normal interaction.

> **Warning — do NOT use `web_eval` to set form input values.**
> Assigning `el.value = "..."` via JavaScript does not trigger the browser's internal input events (e.g. `input`, `change`, `compositionend`). Sites with autocomplete, React/Vue controlled inputs, or custom form serialization will ignore DOM-level value changes. Always use `fill` to type into inputs — it calls `clear()` + `send_keys()` which fires native input events correctly.
>
> ```bash
> # WRONG — value may be ignored by the site
> appium-cli web_eval "el.value = '秋葉原'" web_query_input
>
> # CORRECT — fires real input events
> appium-cli fill web_query_input "秋葉原"
> ```

## Targeting layers

1. **Refs first**: use `web_...` refs from `web_snapshot`/`web_refs` with `click`, `fill`, `select`, `select_option`, `set_date`, and `press_key`.
2. **CSS/locator second**: use `css:` prefix (e.g. `appium-cli click "css:#submit"`) or `web_query` to discover CSS selectors and `generate_locator <ref>` to extract the best selector stored for a ref.
3. **Legacy locators last**: use locator tools only for expert recovery or compatibility.

```bash
appium-cli web_snapshot
appium-cli generate_locator web_btn_submit
appium-cli --raw generate_locator web_btn_submit
```

## WebView actions

Preferred page-level actions:

```bash
appium-cli click web_btn_login
appium-cli fill web_search "query"
appium-cli select web_country "JP" --by=value
appium-cli select_option web_state "NCR"
appium-cli set_date web_dateofbirthinput "15 May 1990"
appium-cli scroll_down
appium-cli press_key Enter
```

Compatibility actions such as `tap web_<ref>` or `type_text web_<ref> ...` may work with web refs, but prefer `click` and `fill` for DOM interactions because they use Selenium/WebDriver semantics.

`fill --slowly` sends text character by character for inputs that depend on key events. It does not guarantee that the input value is committed or that suggestion/dropdown UI is closed. Use `web_snapshot` after slow typing when the next action depends on page state, then click a relevant option or dismiss unneeded transient UI with `press_key Escape`.

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
appium-cli --raw web_snapshot web_panel > before.yml
appium-cli click web_toggle
appium-cli --raw web_snapshot web_panel > after.yml
diff before.yml after.yml
```

## Prerequisites and diagnostics

WebView automation requires WebView debugging, a compatible Chromedriver, and an Appium server configured for WebView automation. Use `appium-cli webview_status`.

`get_page_source --context=webview` returns raw HTML and can be token-heavy. Use it only when `web_snapshot`, `web_query`, and artifact commands are insufficient.

## Apple Silicon (arm64) macOS + Linux arm64 container

Chrome / WebView automation needs a local ChromeDriver binary on the machine that runs Appium. In an arm64 Linux devcontainer on Apple Silicon Mac this cannot work directly because:

- Google publishes ChromeDriver only for `linux64` (x86_64 Linux), `mac-arm64` (Apple Silicon macOS Mach-O), `mac-x64`, `win32`, `win64`. There is no `linux-arm64` build.
- The `mac-arm64` binary cannot execute inside any Linux container (Mach-O is not ELF).
- The `linux64` binary cannot execute in an arm64 Linux container without an x86 emulator. Appium downloads it via autodownload and it fails with `Chromedriver --version exited with code 255`.
- Native Android (UiAutomator2) is unaffected and keeps working; the failure shows up only when switching context to WebView / fetching `webview_title` / `goto` / `web_query`.

Supported pattern: run Appium on the macOS host (where `mac-arm64` ChromeDriver works), keep the container arm64, and connect through `host.docker.internal`:

```bash
# On the macOS host (one-time, NOT installed by appium-cli)
npm install -g appium
appium driver install uiautomator2

# Start host Appium with insecure features needed for Chrome and shell.
appium --address 0.0.0.0 --port 4723 \
  --allow-insecure=uiautomator2:chromedriver_autodownload,uiautomator2:adb_shell

# Inside the arm64 Linux container
appium-cli session start --server-url http://host.docker.internal:4723
# or rely on env: APPIUM_SERVER_URL=http://host.docker.internal:4723
```

Do not enable `APPIUM_REMOTE_ADB_HOST` when Appium runs on the macOS host; that variable is only for the reverse case (Appium inside the container, adb on the host).

Rosetta / amd64 emulated devcontainers are not a supported workaround for this; keep the devcontainer arm64.
