# Observation

Use snapshots as the primary observation primitive. `snapshot` (native) and `web_snapshot` (WebView/Chrome) are artifact-first: normal output is compact metadata plus links to persisted artifacts, not the full tree.

```bash
appium-cli snapshot
appium-cli web_snapshot
```

Typical normal output:

```text
snapshot_id: native-20250101-120000-abc123
source: native
screen_id: 8dd580
context: NATIVE_APP
artifacts:
  compact: .appium-cli/snapshots/native-...compact.yml
  full: .appium-cli/snapshots/native-...full.yml
  refs: .appium-cli/snapshots/native-...refs.json
  index: .appium-cli/snapshots/native-...index.json
  meta: .appium-cli/snapshots/native-...meta.json
```

Use artifact navigation commands to inspect without refreshing device state:

```bash
appium-cli snapshot_show latest
appium-cli snapshot_show latest --artifact=full
appium-cli snapshot_show latest --artifact=meta
appium-cli snapshot_show latest --ref=btn_ok
appium-cli snapshot_search "Storage" --role=row
appium-cli snapshot_refs latest --role=button
appium-cli generate_locator btn_ok
```

## Raw tree output

Use global `--raw` before the command when you need bare tree content for piping or diffing:

```bash
appium-cli --raw snapshot > before.yml
appium-cli tap btn_ok
appium-cli --raw snapshot > after.yml
diff before.yml after.yml
```

Raw snapshot output is the rendered tree. Normal snapshot output remains metadata plus artifact links. Raw action commands suppress post-action artifact links and return nothing/minimal success.

## Element-scoped snapshots

Scope a snapshot to a specific ref when a full tree is too large:

```bash
appium-cli snapshot main_list
appium-cli snapshot row_settings --depth=2
appium-cli web_snapshot web_form --depth=3
appium-cli snapshot dialog_root --filename=dialog.yml
appium-cli --raw web_snapshot web_results > results.yml
```

`--filename` saves the rendered tree to a file while normal stdout still prints metadata. `--depth` caps the rendered subtree depth. `--max-nodes` and `--boxes` are available for larger/debug sessions.

## Artifact types

- `compact` - compact tree for quick reading.
- `full` - complete rendered tree.
- `refs` - JSON ref map with roles, names, bounds, contexts, and locator strategies.
- `index` - searchable compact index.
- `meta` - snapshot id, source, context, screen id, and artifact paths.

Use `snapshot_refs` before choosing targets in a large screen, and `snapshot_search` to find likely refs without re-querying the device.

## Ref naming and targeting

Refs are stable IDs derived from element attributes, not sequential `e1`/`e2` IDs:

- `resource-id="com.example:id/login"` -> `login`
- `content-desc="Search"` -> `search`
- role `button` + name `Submit` -> `btn_submit`
- duplicates receive `_2`, `_3`, ... suffixes

Only actionable/editable/scrollable/container nodes get refs. Pure text leaves usually do not. If text has no ref, use the nearest row/button/container ref in the same tree or run `appium-cli find_by_text "Visible label"`.

## describe and generate_locator

`describe <ref>` reads the current in-memory snapshot. `snapshot_show latest --ref=<ref>` reads the persisted refs artifact. Prefer artifact commands when reviewing previous snapshots.

```bash
appium-cli describe btn_ok
appium-cli snapshot_show latest --ref=btn_ok
appium-cli generate_locator btn_ok
appium-cli --raw generate_locator btn_ok
```

`generate_locator` returns the best stored durable locator for a ref. For native refs it prefers accessibility/id-style strategies; for WebView refs it prefers CSS selectors.

## Screenshot and page source

`snapshot` is primary. `screenshot` is rarely needed; use it only when visual pixels are necessary. `get_page_source` can be very large and token-heavy; treat it as a diagnostic escape hatch after snapshot artifacts, `snapshot_search`, and `snapshot_refs` are insufficient.
