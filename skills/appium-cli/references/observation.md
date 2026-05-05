# Observation

Use observation commands to inspect the current Android screen and get refs for actions.

```bash
appium-cli snapshot
appium-cli snapshot --scope=inputs
appium-cli describe row_settings
appium-cli find_by_text "Log in"
appium-cli screenshot
appium-cli get_page_source
```

## Ref naming

Refs are stable IDs derived from the element's resource-id, content-desc, or role+name:

- `resource-id="com.example:id/login"` → `login`
- `content-desc="Search"` → `search`
- `role=button, name="Submit"` → `btn_submit`

When multiple elements share the same resource-id (e.g. tab buttons), suffixes `_2`, `_3`, `_4` are appended to keep refs unique. Pure text leaves never carry a ref — only ref-bearing nodes (containers, rows, buttons, inputs, tabs, …) can be the target of `describe`, `tap`, or other ref-based actions.

## Snapshot output

The native snapshot is a single indented tree that mirrors the WebView snapshot shape. Each line is one node:

```text
- <role> ["<name>"] [ref:<id>] [state] [scrollable:<axis>]
```

A header at the top reports the screen, a stable `screen_id`, the active context, and the source. Two trailers (`alerts:` and `nav:`) follow the tree.

Read the full snapshot before choosing a ref. A filtered scope can hide the clickable parent, the scrollable container, or nearby duplicate labels.

### Example: simple settings screen

```text
screen: NATIVE_APP
screen_id: c0116d
context: NATIVE_APP
source: native

- container
  - toolbar [ref:action_bar]
    - button "Navigate up" [ref:navigate_up]
    - text "Settings"
  - text "Wi-Fi"
  - text "Bluetooth"
  - text "Display"

alerts: none
nav: none
```

### Example: scrollable list

```text
- list [ref:recycler] [scrollable:vertical]
  - row [ref:row]
    - text "Row 1"
    - text "Subtitle 1"
  - row [ref:row_2]
    - text "Row 2"
    - text "Subtitle 2"
  - row [ref:row_3]
    - text "Row 3"
    - text "Subtitle 3"
```

How to use this output:

- `recycler` is the scrollable list container. Use it for scoped scrolling: `appium-cli scroll_down recycler`.
- `"Row 1"` is a pure text leaf and has no ref. Tap the parent `row` ref instead.
- Refs come from the latest snapshot only. After a tap, scroll, back, dialog, or app switch, run `snapshot` again before reusing refs.

### Example: bottom navigation tabs

```text
- tabs [ref:bottom_nav]
  - tab "Home" [ref:nav_home] [selected]
    - text "Home"
  - tab "Search" [ref:nav_search]
    - text "Search"
  - tab "Profile" [ref:nav_profile]
    - text "Profile"
```

`[selected]` and other state markers (e.g. `[disabled]`, `[checked]`) appear in brackets after the name.

### Example: dialog overlay

```text
- container
  - text "Home"
  - overlay [ref:dialog_root]
    - text "Delete file?"
    - text "This action cannot be undone."
    - button "Cancel" [ref:button2]
    - button "OK" [ref:button1]
```

Use `--scope=active_layer` to render only the topmost dialog/overlay/sheet subtree when one is present.

If a desired label is not clickable, inspect the nearby row/button/container in the same tree instead of trying to tap the text directly. Pure text nodes have no ref by design.

## describe

`appium-cli describe <ref>` renders a multi-line description of a ref-bearing node, including role, name, value, state, bounds, the owning container, and (when present) the rendered subtree.

```text
$ appium-cli describe button1
element: - button "OK" [ref:button1]
role: button
name: OK
state: none
bounds: (552, 1140, 936, 1296)
container: dialog dialog_root
```

`describe` only accepts refs that exist in the current snapshot. Calling it with a text leaf is not supported because text leaves do not carry refs — describe the parent container instead.

## find_by_text

`appium-cli find_by_text "<query>"` performs a fuzzy match against `name`, `value`, and visible text across the snapshot tree. Each match line uses one of two shapes:

- **Ref-bearing match** — the matched node itself has a ref:

  ```text
  [ref:nav_home] tab "Home" (score=100)
  ```

- **Text-leaf match** — a pure text node matched. The result resolves the nearest actionable ancestor (button, row, tab, link, input, …) and reports it as the action target:

  ```text
  text "Row 1" (score=100) -> action target [ref:row]
  text "Manage your account settings" (score=60) -> action target [ref:row_settings]
  ```

  If no actionable ancestor exists (for example, a static label inside a non-interactive container), the line is shown without an action target. In that case there is nothing to tap directly — run `describe` on the surrounding container or re-evaluate the screen.

Combine with `--scope=inputs` to restrict matches to text inputs only.

## Scope filters

`snapshot` and `web_snapshot` accept `--scope=<value>`:

- `full` (default) — entire tree.
- `inputs` — flat list of input/textbox nodes only.
- `active_layer` — first dialog/overlay/sheet subtree, when one is present.
- `near:<ref>` — the parent container subtree of the given ref.
- `depth:N` — render the full tree but cap depth at N levels.

Scope filters apply identically to native and WebView snapshots.

## Snapshot flags

These flags apply to both `snapshot` (native) and `web_snapshot` / `snapshot --context=webview`:

- `--scope=<value>` — see above.
- `--max-nodes=N` — cap the total number of rendered nodes. When the cap is reached, the header includes `truncated: true`.
- `--boxes` — append bounding box coordinates to each rendered node.
- `--filename=<path>` — save the rendered snapshot output to a file.

Native-only:

- `--context=native|current|webview|auto|<name>` — choose which context to snapshot (default: `native`).

Prefer `snapshot` and refs before taking screenshots. `screenshot` returns the smartestiroid-compatible JSON string containing `type`, `image_base64`, `region`, and saves a PNG file under `.appium-cli/session-XXXX/`.

## WebView snapshots

When a WebView or Chrome context is available, use `--context=webview` to get an indented DOM tree with `web_` prefixed refs on actionable nodes:

```bash
appium-cli snapshot --context=webview
appium-cli web_snapshot  # equivalent alias
```

Web snapshots use CSS selector and XPath locator strategies instead of native resource-id/accessibility_id. The `--scope`, `--max-nodes`, `--boxes`, and `--filename` flags work the same way as for native snapshots.

Nested text and headings usually do not carry refs. Use the nearest parent link/button/input ref shown in the tree when acting.

See [WebView reference](webview.md) for the full WebView workflow.
