# WebView and Chrome automation

Use context commands to inspect and switch between native and WebView contexts. When Appium detects a WebView or Chrome browser, a `WEBVIEW_*` or `CHROMIUM` context becomes available alongside `NATIVE_APP`.

## Context workflow

```bash
# Check available contexts
appium-cli list_contexts

# Switch to WebView
appium-cli webview_switch

# Take a web snapshot (indented DOM tree with web_ refs)
appium-cli snapshot --context=webview
# or equivalently:
appium-cli web_snapshot

# Act on web refs
appium-cli click web_link_news_1
appium-cli fill web_search_form "query text"

# Switch back to native
appium-cli native_switch
appium-cli snapshot
```

## Context commands

```bash
appium-cli list_contexts          # Show available contexts with current marker
appium-cli get_context            # Return current context name
appium-cli switch_context native  # Switch by selector: native, webview, auto, or exact name
appium-cli native_switch          # Shortcut for switch_context native
appium-cli webview_switch         # Shortcut for switch_context webview
appium-cli webview_status         # Diagnostic: WebView availability, URL, title, hints
```

## WebView observation

```bash
appium-cli snapshot --context=webview   # Tree snapshot with web_ refs
appium-cli web_snapshot                 # Alias for snapshot --context=webview
appium-cli web_snapshot --depth=10      # Limit tree depth
appium-cli web_snapshot --max-nodes=200 # Limit total nodes
appium-cli webview_url                  # Current page URL
appium-cli webview_title                # Current page title
appium-cli get_page_source --context=webview  # Raw HTML source
```

### Web snapshot output

```text
screen: CHROMIUM https://www.yahoo.co.jp/
screen_id: a3f2c1
context: CHROMIUM
source: web
title: Yahoo! JAPAN
url: https://www.yahoo.co.jp/

- document "Yahoo! JAPAN"
  - textbox "検索" [ref:web_search_form]
  - link "主要ニュース見出し..." [ref:web_link_news_1]
    - heading "主要ニュース見出し..."
    - text "5/5(火) 18:30"
  - button "ログイン" [ref:web_btn_login]
  - image "Yahoo! JAPAN"
```

All web refs start with `web_` to distinguish them from native refs. Refs are assigned to actionable/input/selectable nodes such as links, buttons, textboxes, and selects. Non-actionable headings/text are rendered as children without misleading click refs; click the nearest parent link/button ref.

Large pages are pruned by default (`--depth=15`, `--max-nodes=300`). Hidden, zero-area, and `aria-hidden=true` nodes are omitted. Use `--boxes` when bounds are useful for debugging.

## Web ref naming

| Source | Derivation | Example |
|---|---|---|
| HTML `id` | `web_` + snake_case(id) | `web_search_form` |
| `data-testid` | `web_` + snake_case(testid) | `web_login_button` |
| `aria-label` | `web_` + snake_case(label) | `web_submit` |
| tag + text fallback | `web_` + role_prefix + text | `web_link_news_article` |
| Duplicate | `_2`, `_3` suffix | `web_link_news_article_2` |

## WebView actions

Actions are context-aware. When you use a `web_` ref, the driver automatically switches to the ref's WebView context.

```bash
appium-cli tap web_btn_login        # Selenium element.click() in WebView
appium-cli click web_btn_login      # Alias for tap (web-friendly name)
appium-cli type_text web_search_form "hello" --submit
appium-cli fill web_search_form "hello"  # Alias for type_text
appium-cli select web_country "JP" --by=value  # HTML <select> element
appium-cli scroll_down              # window.scrollBy() in WebView context
appium-cli press_key Enter          # W3C key names in WebView (not Android keycodes)
```

### Unsupported gestures in WebView

These gestures fail with exit code 8 (`FEATURE_NOT_ENABLED`) in WebView context because UiAutomator2 gesture scripts are not available:

- `long_press`, `double_tap`, `drag`
- `fling_up`, `fling_down`, `fling_left`, `fling_right`
- `pinch_open`, `pinch_close`
- `swipe_up`, `swipe_down`, `swipe_left`, `swipe_right`

Switch to `native` context for these gestures.

## Navigation

```bash
appium-cli goto "https://example.com"  # Navigate to URL
appium-cli go_back                      # Browser back
appium-cli go_forward                   # Browser forward
appium-cli reload                       # Reload page
```

These commands require a WebView/CHROMIUM context.

## JavaScript evaluation

```bash
appium-cli web_eval "document.title"
appium-cli web_eval "el.textContent" web_link_news_1  # el = resolved element
```

Use `web_eval` for diagnostic observation only. Prefer snapshot/ref commands for normal workflows.

## Dialog handling

```bash
appium-cli dialog_text               # Read alert/confirm/prompt text
appium-cli dialog_accept             # Accept dialog
appium-cli dialog_accept "answer"    # Accept prompt with text
appium-cli dialog_dismiss            # Dismiss dialog
```

## Prerequisites

WebView automation requires:

1. **WebView debugging enabled** in the app (`WebView.setWebContentsDebuggingEnabled(true)` for Android)
2. **Compatible Chromedriver** version matching the device's Chrome/WebView version
3. Appium server feature `uiautomator2:chromedriver_autodownload` or a manually specified Chromedriver path

When `appium-cli server start` starts a new Appium server, Chromedriver autodownload is enabled by default. Use `appium-cli server start --no-chromedriver-autodownload` to opt out. For externally started Appium servers, start Appium with `--allow-insecure=uiautomator2:chromedriver_autodownload` or equivalent.

Use `appium-cli webview_status` to check availability and get diagnostic hints.

## Workflow: native app with embedded WebView

```bash
# 1. Start with native snapshot
appium-cli snapshot
# See a WebView element in native snapshot

# 2. Check if WebView context is available
appium-cli list_contexts
# ['NATIVE_APP', 'WEBVIEW_com.example']

# 3. Switch and snapshot the web content
appium-cli web_snapshot

# 4. Interact with web elements
appium-cli click web_btn_submit
appium-cli fill web_input_email "user@example.com"

# 5. Return to native when done
appium-cli native_switch
appium-cli snapshot
```

## Limitations

- WebView refs are only valid while in the same WebView context. After navigation or page reload, take a new `web_snapshot`.
- `find_by_text` and `assert_visible` search the current snapshot only. Run the appropriate snapshot first.
- Touch gestures (long press, pinch, fling, swipe) are not available in WebView context.
- `press_key` uses W3C key names (`Enter`, `Tab`, `ArrowDown`) in WebView, not Android keycodes.
