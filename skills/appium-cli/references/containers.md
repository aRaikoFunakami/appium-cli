# Containers and Verification

Containers are ref-bearing nodes in snapshot artifacts whose `container_kind` is set (`topbar`, `list`, `dialog`, `overlay`, `tabs`, `selection`). They are part of the tree, not a separate primary model.

```bash
appium-cli snapshot
appium-cli web_refs latest --role=list
appium-cli list_containers
appium-cli within_container recycler --role=button
appium-cli assert_visible --ref nav_home
```

Prefer `web_refs`, `snapshot_search`, and element-scoped snapshots for artifact-first inspection. Container commands are useful when duplicate labels appear in different screen regions.

## list_containers

Lists container nodes from the current snapshot with refs, kind, scrollability, and child counts:

```text
Containers on screen (1 total):

1. [ref:recycler] list
   scrollable: yes (vertical) | additional elements may be hidden off-screen
   children: 5 visible/total
```

Scroll containers by ref, then observe/search again:

```bash
appium-cli scroll_down recycler
appium-cli snapshot_search "Target" --role=row
appium-cli web_refs latest --role=row
```

## within_container

Lists ref-bearing descendants inside one container:

```bash
appium-cli within_container bottom_nav --role=tab
```

```text
3 candidates:
  - tab "Home" [ref:nav_home] [selected]
  - tab "Search" [ref:nav_search]
  - tab "Profile" [ref:nav_profile]
```

Filter with `--role=<role>` and `--position=first|last|<index>`.

## Element-scoped snapshots

For deep containers, prefer a scoped artifact:

```bash
appium-cli snapshot recycler
appium-cli --raw snapshot recycler > recycler.yml
appium-cli snapshot_search "Target" --role=row
```

This avoids printing full-screen trees while keeping a persisted artifact bundle. Avoid `--depth` unless you intentionally need a smaller debug subtree, because depth can hide searchable targets.

## assert_visible

`assert_visible` checks the current snapshot tree and is useful before or after actions:

```bash
appium-cli assert_visible --text "Home"
appium-cli assert_visible --ref nav_home
```

Text nodes may not have refs. Text search output annotates action targets when an actionable parent exists; tap the parent ref, not the static text.
