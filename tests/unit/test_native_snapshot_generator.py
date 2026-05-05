"""Tests for NativeSnapshotGenerator: drives the generator from XML fixtures."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from appium_cli.core.native_snapshot import NativeSnapshot, NativeSnapshotNode
from appium_cli.core.native_snapshot_generator import NativeSnapshotGenerator


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "native"


def load(name: str) -> str:
    return (FIXTURE_DIR / name).read_text()


def _walk(node: NativeSnapshotNode):
    yield node
    for child in node.children:
        yield from _walk(child)


def _max_depth(node: NativeSnapshotNode, depth: int = 0) -> int:
    if not node.children:
        return depth
    return max(_max_depth(c, depth + 1) for c in node.children)


def test_parses_simple_screen():
    snap = NativeSnapshotGenerator().generate(load("simple_screen.xml"))
    assert isinstance(snap, NativeSnapshot)
    assert snap.root is not None
    assert isinstance(snap.root, NativeSnapshotNode)
    assert len(snap.screen_id) == 6
    assert all(ch in "0123456789abcdef" for ch in snap.screen_id)
    refs = {n.ref for n in _walk(snap.root) if n.ref}
    assert "navigate_up" in refs


def test_pruning_removes_pure_layout_wrappers():
    snap = NativeSnapshotGenerator().generate(load("nested_wrappers.xml"))
    # Raw XML has 7 nested wrappers above the Button -> after collapse,
    # depth must be very small.
    assert _max_depth(snap.root) <= 3
    # Leaf button reachable.
    button_nodes = [n for n in _walk(snap.root) if n.role == "button"]
    assert button_nodes, "Continue button must survive pruning"
    assert any(n.name == "Continue" for n in button_nodes)
    # No surviving frame/linear layouts as 'container' wrappers.
    for n in _walk(snap.root):
        assert not (
            n.role == "container"
            and not n.name
            and not n.state
            and len(n.children) == 1
        ), f"transparent wrapper survived: {n.class_name}"


def test_single_child_promotion():
    snap = NativeSnapshotGenerator().generate(load("nested_wrappers.xml"))
    for n in _walk(snap.root):
        if n.role == "container" and len(n.children) == 1:
            assert n.name or n.state or n.scrollable or n.container_kind, (
                f"container with single child should have been promoted: {n}"
            )


def test_duplicate_resource_id_disambiguation():
    snap = NativeSnapshotGenerator().generate(load("duplicate_resource_id.xml"))
    refs = [n.ref for n in _walk(snap.root) if n.ref]
    tab_refs = [r for r in refs if r.startswith("tabbackground")]
    assert sorted(tab_refs) == [
        "tabbackground",
        "tabbackground_2",
        "tabbackground_3",
        "tabbackground_4",
    ]


def test_recycler_view_rows_get_refs_text_does_not():
    snap = NativeSnapshotGenerator().generate(load("recycler_view.xml"))
    rows = [n for n in _walk(snap.root) if n.role == "row"]
    texts = [n for n in _walk(snap.root) if n.role == "text"]
    assert len(rows) == 5
    assert len(texts) == 10
    for row in rows:
        assert row.ref is not None
    for text_node in texts:
        assert text_node.ref is None


def test_recycler_view_text_action_target():
    snap = NativeSnapshotGenerator().generate(load("recycler_view.xml"))
    # Build a parent map.
    parent: dict[int, NativeSnapshotNode] = {}

    def walk(node: NativeSnapshotNode) -> None:
        for c in node.children:
            parent[id(c)] = node
            walk(c)

    walk(snap.root)
    for text_node in (n for n in _walk(snap.root) if n.role == "text"):
        # Find nearest row ancestor.
        ancestor = parent.get(id(text_node))
        while ancestor is not None and ancestor.role != "row":
            ancestor = parent.get(id(ancestor))
        assert ancestor is not None, "text node without row ancestor"
        assert text_node.action_target_ref == ancestor.ref


def test_recycler_container_kind():
    snap = NativeSnapshotGenerator().generate(load("recycler_view.xml"))
    lists = [n for n in _walk(snap.root) if n.container_kind == "list"]
    assert lists, "RecyclerView must be detected as list container"
    recycler = lists[0]
    assert recycler.scrollable is True
    assert recycler.scroll_direction in {"vertical", "horizontal", ""}
    assert recycler.scroll_direction == "vertical"


def test_mixed_text_content_desc_naming():
    snap = NativeSnapshotGenerator().generate(load("mixed_text_content_desc.xml"))
    by_name: dict[str, NativeSnapshotNode] = {n.name: n for n in _walk(snap.root) if n.name}
    # text-only
    assert "Welcome back" in by_name
    # content-desc only (avatar -> image+clickable -> button)
    assert "User profile picture" in by_name
    # both -> text wins
    assert "Submit" in by_name
    assert "Submit form" not in by_name
    # content-desc only on icon button
    assert "Search" in by_name
    # text-only Cancel
    assert "Cancel" in by_name


def test_offscreen_nodes_pruned():
    snap = NativeSnapshotGenerator().generate(load("offscreen_nodes.xml"))
    resource_ids = {
        n.resource_id for n in _walk(snap.root) if n.resource_id
    }
    # Zero-size and negative-bounds nodes must be pruned.
    assert "com.example.app:id/zero_size" not in resource_ids
    assert "com.example.app:id/negative_bounds" not in resource_ids
    # No surviving node has zero-area bounds.
    for n in _walk(snap.root):
        if n.omitted:
            continue
        x1, y1, x2, y2 = n.bounds
        # root container after promotion may legitimately keep bounds; just
        # ensure non-degenerate area when bounds are non-default.
        if (x1, y1, x2, y2) == (0, 0, 0, 0):
            continue
        assert x2 > x1 and y2 > y1, f"zero-area node survived: {n}"


def test_clickable_row_text_only_row_has_ref():
    snap = NativeSnapshotGenerator().generate(load("clickable_row_with_text.xml"))
    rows = [n for n in _walk(snap.root) if n.role == "row"]
    assert len(rows) == 1
    row = rows[0]
    assert row.ref is not None
    texts = [n for n in _walk(snap.root) if n.role == "text"]
    assert len(texts) == 2
    for text_node in texts:
        assert text_node.ref is None
        assert text_node.action_target_ref == row.ref


def test_form_with_input_textbox_ref():
    snap = NativeSnapshotGenerator().generate(load("form_with_input.xml"))
    textboxes = [n for n in _walk(snap.root) if n.role == "textbox"]
    assert len(textboxes) == 1
    textbox = textboxes[0]
    assert textbox.ref is not None
    # Reachable via find_ref.
    assert snap.find_ref(textbox.ref) is textbox
    # Label text should not crash and have either None or the textbox ref.
    labels = [n for n in _walk(snap.root) if n.role == "text" and n.name == "Email"]
    assert len(labels) == 1
    assert labels[0].action_target_ref in (None, textbox.ref)


def test_dialog_overlay_container_kind():
    snap = NativeSnapshotGenerator().generate(load("dialog_overlay.xml"))
    layers = [n for n in _walk(snap.root) if n.container_kind in {"dialog", "overlay"}]
    assert layers, "dialog/overlay container must be detected"
    layer = layers[0]
    button_names = {n.name for n in _walk(layer) if n.role == "button"}
    assert "OK" in button_names
    assert "Cancel" in button_names


def test_bottom_navigation_tabs():
    snap = NativeSnapshotGenerator().generate(load("bottom_navigation.xml"))
    tab_containers = [n for n in _walk(snap.root) if n.container_kind == "tabs"]
    assert tab_containers
    tab_nodes = [n for n in _walk(snap.root) if n.role == "tab"]
    assert len(tab_nodes) == 3
    home = [n for n in tab_nodes if any(c.name == "Home" for c in n.children)]
    assert home, "Home tab must exist"
    assert "selected" in home[0].state


def test_locator_strategies_priority():
    snap = NativeSnapshotGenerator().generate(load("simple_screen.xml"))
    # action_bar: has resource_id, no content-desc
    action_bar = next(
        n for n in _walk(snap.root) if n.ref == "action_bar"
    )
    assert action_bar.strategies, "action_bar must have strategies"
    assert action_bar.strategies[0].by == "id"
    last = action_bar.strategies[-1]
    assert last.by == "coordinates"
    assert re.match(r"^\d+,\d+$", last.value)

    # navigate_up: has content-desc, no resource_id
    nav = next(n for n in _walk(snap.root) if n.ref == "navigate_up")
    assert any(s.by == "accessibility_id" for s in nav.strategies)
    assert nav.strategies[-1].by == "coordinates"


def test_screen_id_stable():
    xml = load("simple_screen.xml")
    snap_a = NativeSnapshotGenerator().generate(xml)
    snap_b = NativeSnapshotGenerator().generate(xml)
    assert snap_a.screen_id == snap_b.screen_id
    # Modify a ref-bearing node's name (Navigate up content-desc).
    modified = xml.replace('content-desc="Navigate up"', 'content-desc="Go back"')
    assert modified != xml
    snap_c = NativeSnapshotGenerator().generate(modified)
    assert snap_c.screen_id != snap_a.screen_id


def test_to_text_round_trip():
    snap = NativeSnapshotGenerator().generate(load("simple_screen.xml"))
    text = snap.to_text()
    lines = text.splitlines()
    assert any(line.startswith("screen_id:") for line in lines)
    assert any(line.startswith("context:") for line in lines)
    assert "[ref:" in text
    assert lines[-1].startswith("nav:")


def test_max_nodes_truncates():
    gen = NativeSnapshotGenerator(max_nodes=5)
    snap = gen.generate(load("recycler_view.xml"))
    assert snap.truncated is True
    omitted = [n for n in _walk(snap.root) if n.omitted]
    assert omitted, "max_nodes truncation should mark some nodes as omitted"
    total = sum(1 for _ in _walk(snap.root))
    # Allow budget plus omitted markers as breathing room.
    assert total <= 5 + len(omitted) + 1


def test_app_info_passthrough():
    snap = NativeSnapshotGenerator().generate(
        load("simple_screen.xml"),
        app_info="com.example/.MainActivity",
    )
    assert snap.app_info == "com.example/.MainActivity"
    assert "com.example/.MainActivity" in snap.to_text()


def test_invalid_xml_raises():
    with pytest.raises(ValueError) as exc:
        NativeSnapshotGenerator().generate("<not xml")
    msg = str(exc.value).lower()
    assert "parse" in msg or "xml" in msg


def test_empty_hierarchy():
    xml = "<hierarchy rotation=\"0\"></hierarchy>"
    try:
        snap = NativeSnapshotGenerator().generate(xml)
    except ValueError:
        return
    # If no error, root must be a real node, not None.
    assert snap.root is not None
    assert isinstance(snap.root, NativeSnapshotNode)
