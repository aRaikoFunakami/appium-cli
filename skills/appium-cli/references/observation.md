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
stats: 8 nodes, 3 refs, 1 buttons, 1 containers
artifacts:
  compact: .appium-cli/snapshots/native-...compact.yml
  full: .appium-cli/snapshots/native-...full.yml
  refs: .appium-cli/snapshots/native-...refs.json
  index: .appium-cli/snapshots/native-...index.json
  meta: .appium-cli/snapshots/native-...meta.json
```

Use artifact navigation commands to inspect without refreshing device state. Prefer targeted extraction before reading a whole tree artifact:

```bash
appium-cli snapshot_search "Storage" --role=row
appium-cli snapshot_search "ログイン" --or-text Login --or-text "Sign in"  # OR search
appium-cli snapshot_refs latest --role=button
appium-cli snapshot_refs latest --role=button --offset=50
appium-cli snapshot_show latest --ref=btn_ok
appium-cli snapshot_show latest --artifact=meta
appium-cli snapshot_show latest              # fallback; can be large
appium-cli snapshot_show latest --artifact=full  # debugging only
appium-cli generate_locator btn_ok
```

For WebView pages where the task requires reading or summarizing article/body/page text, use `web_text` instead of reading full snapshot trees:

```bash
appium-cli web_text                         # auto-select article/main/body text
appium-cli web_text --selector=article      # read a known content container
appium-cli web_text --offset=6000           # continue truncated text
```

`compact.yml` intentionally remains a tree artifact so UI hierarchy is available on disk. Do not paste/read the whole artifact by default. Search it with `snapshot_search`, inspect paginated ref indexes with `snapshot_refs`, inspect one element with `snapshot_show --ref`, or use local grep/rg-style file extraction when available.

`snapshot_refs` returns 50 refs by default. If output says `has_more=true` or prints `next_offset=...`, narrow the role/search if possible or request the next page with `--offset=<next_offset>`.

## Raw tree output

Use global `--raw` before the command when you need bare tree content for piping or diffing:

```bash
appium-cli --raw snapshot > before.yml
appium-cli tap btn_ok
appium-cli --raw snapshot > after.yml
diff before.yml after.yml
```

Raw snapshot output is the rendered tree. Normal snapshot output remains metadata plus artifact links. Tool-calling agents should keep normal non-raw snapshot output in context and use targeted artifact commands instead of full raw trees.

## Element-scoped snapshots

Scope a snapshot to a specific ref when a full tree is too large:

```bash
appium-cli snapshot main_list
appium-cli snapshot row_settings
appium-cli web_snapshot web_form
appium-cli snapshot dialog_root --filename=dialog.yml
appium-cli web_snapshot web_results --filename=results.yml
```

`--filename` saves the rendered tree to a file while normal stdout still prints metadata. Do not use `--depth` for normal observations; full artifacts keep targets searchable, and token control should use `snapshot_search`, `snapshot_show --ref`, and paginated `snapshot_refs`. `--depth` is only a scoped/debug escape hatch when you intentionally want a smaller subtree. `--max-nodes` and `--boxes` are available for larger/debug sessions.

## Artifact types

- `compact` - tree artifact for UI hierarchy. Use targeted extraction first; read the whole file only when needed.
- `full` - complete rendered tree.
- `refs` - JSON ref map with roles, names, bounds, contexts, and locator strategies.
- `index` - searchable compact index.
- `meta` - snapshot id, source, context, screen id, and artifact paths.

Use `snapshot_refs` before choosing targets in a large screen, and `snapshot_search` to find likely refs or text snippets without re-querying the device.

## Targeted artifact extraction

```bash
appium-cli snapshot_search "Qiita"
appium-cli snapshot_refs latest --role=link
appium-cli snapshot_show latest --ref=web_link_qiita
```

For before/after files, compare and filter locally instead of reading both files into the model:

```bash
appium-cli --raw snapshot > before.yml
appium-cli tap btn_expand
appium-cli --raw snapshot > after.yml
diff before.yml after.yml | grep -E "expanded|selected|ref:"
```

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

`snapshot` is primary for structure and refs. `web_text` is primary for WebView page/article text. `screenshot` is rarely needed; use it only when visual pixels are necessary. Session-backed screenshots return an artifact path under `.appium-cli/<session-id>/`; reuse that path and do not save a duplicate copy. `get_page_source` can be very large and token-heavy; treat it as a diagnostic escape hatch after targeted artifact extraction, `web_text`, `snapshot_search`, and `snapshot_refs` are insufficient.
