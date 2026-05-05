# Containers and Verification

Containers are tree nodes inside the snapshot whose `container_kind` is set
(`topbar`, `list`, `dialog`, `overlay`, `tabs`, `selection`). They are not a
separate flat list — they are regular nodes in the snapshot tree, and their
descendants are the elements you can act on inside that region.

Use container tools when the same text appears in multiple areas, or when you
need to scope a search to one region of the screen.

```bash
appium-cli snapshot
appium-cli list_containers
appium-cli find_container "Item"
appium-cli within_container recycler --role=button
appium-cli assert_visible --text "Home"
appium-cli assert_visible --ref nav_home
```

## list_containers

Walks the snapshot tree and lists every node with a non-empty
`container_kind`, with its ref, kind, scrollability, and child count.

```text
Containers on screen (1 total):

1. [ref:recycler] list
   scrollable: yes (vertical) | ⚠ additional elements may be hidden off-screen
   children: 5 visible/total
```

A scrollable container may have additional children off-screen. Scroll it
(`appium-cli scroll_down recycler`) and re-snapshot to discover more.

## find_container

Returns containers whose subtree contains a matching descendant. If nothing
matches, you'll see a short "not found" message:

```text
'Item' を含むコンテナが見つかりません。
```

When matches exist, each container is printed with its title (if any), its
ref-bearing descendants, and a scroll warning when applicable.

## within_container

Lists every ref-bearing descendant of the given container subtree. Selection
state is part of each node's state list (e.g. `[selected]`), not a separate
container kind.

```text
3 件の候補:
  - tab "Home" [ref:nav_home] [selected]
  - tab "Search" [ref:nav_search]
  - tab "Profile" [ref:nav_profile]
→ Use tap(ref) with the desired ref.
```

For a plain list:

```text
5 件の候補:
  - row [ref:row]
  - row [ref:row_2]
  - row [ref:row_3]
  - row [ref:row_4]
  - row [ref:row_5]
→ Use tap(ref) with the desired ref.
```

Filter the result with `--role=<role>` (e.g. `button`, `tab`) and
`--position=first|last|<index>` to narrow down candidates.

## Selection state

There is no separate "selection container". A selected tab, chip, or list
item carries `[selected]` in its state list directly on the tree node, so
both `list_containers`/`within_container` output and `assert_visible` will
show it inline. To check which tab is active, look for the `[selected]`
state on the candidate refs.

## assert_visible

`assert_visible` walks the current snapshot tree and reports whether the
target is present. It is intended to prevent hallucinated UI assumptions
before and after actions.

```bash
appium-cli assert_visible --text "Home"
```

```text
visible=true (2 件)
  - tab "Home" [ref:nav_home] [selected]
  - text "Home" -> action target [ref:nav_home]
```

```bash
appium-cli assert_visible --ref nav_home
```

```text
visible=true
- tab "Home" [ref:nav_home] [selected]
```

When the target is missing:

```text
visible=false
'Nope' が見つかりません。
```

Text nodes themselves do not carry refs. When you search by text, the result
is annotated with the actionable parent (`-> action target [ref:...]`) so you
can tap that parent directly. Use `find_by_text` (see observation.md) when
you specifically need the action target for a label.
