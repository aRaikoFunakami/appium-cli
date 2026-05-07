"""Pure unit tests for the NativeSnapshot model."""

from __future__ import annotations

from appium_cli.core.native_snapshot import (
    NativeSnapshot,
    NativeSnapshotNode,
)


def _make_node(
    role: str = "text",
    name: str = "",
    ref: str | None = None,
    *,
    children: list[NativeSnapshotNode] | None = None,
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0),
    state: list[str] | None = None,
    value: str | None = None,
    container_kind: str = "",
    action_target_ref: str | None = None,
    omitted: bool = False,
) -> NativeSnapshotNode:
    return NativeSnapshotNode(
        role=role,
        name=name,
        ref=ref,
        children=children or [],
        bounds=bounds,
        state=state or [],
        value=value,
        container_kind=container_kind,
        action_target_ref=action_target_ref,
        omitted=omitted,
    )


def test_node_actionable():
    btn = _make_node(role="button", name="OK", ref="ok")
    txt = _make_node(role="text", name="hello")
    assert btn.actionable is True
    assert txt.actionable is False


def test_node_editable():
    tb = _make_node(role="textbox", ref="tb")
    btn = _make_node(role="button", ref="b")
    assert tb.editable is True
    assert btn.editable is False


def test_iter_nodes_depth_first():
    grand = _make_node(role="text", name="grand")
    c1 = _make_node(role="text", name="c1", children=[grand])
    c2 = _make_node(role="text", name="c2")
    root = _make_node(role="container", name="root", children=[c1, c2])
    order = [n.name for n in root.iter_nodes()]
    assert order == ["root", "c1", "grand", "c2"]


def test_find_ref_with_brackets_and_prefix():
    node = _make_node(role="button", name="OK", ref="ok")
    root = _make_node(role="container", children=[node])
    assert root.find_ref("ok") is node
    assert root.find_ref("[ref:ok]") is node
    assert root.find_ref("ref:ok") is node
    assert root.find_ref(" ok ") is node


def test_find_ref_missing():
    root = _make_node(role="container")
    assert root.find_ref("nope") is None


def test_to_line_basic():
    btn = _make_node(role="button", name="OK", ref="ok", state=["selected"])
    line = btn.to_line()
    assert '- button "OK" [ref:ok]' in line
    assert "[selected]" in line

    btn2 = _make_node(role="button", name="OK", ref="ok", state=["enabled"])
    line2 = btn2.to_line()
    assert "[enabled]" not in line2
    assert "[" not in line2.replace("[ref:ok]", "")


def test_to_line_omitted():
    n = _make_node(role="button", name="x", ref="r", omitted=True)
    assert n.to_line() == "- ..."


def test_to_line_bounds_optional():
    btn = _make_node(role="button", name="OK", ref="ok", bounds=(1, 2, 3, 4))
    assert "bounds=" not in btn.to_line(include_bounds=False)
    line = btn.to_line(include_bounds=True)
    assert "bounds=(1, 2, 3, 4)" in line


def test_to_ref_entry_skips_unref_nodes():
    n = _make_node(role="text", name="hello")
    assert n.to_ref_entry("NATIVE_APP") is None


def test_to_ref_entry_includes_action_target():
    n = _make_node(role="button", name="X", ref="x", action_target_ref="row1")
    entry = n.to_ref_entry("NATIVE_APP")
    assert entry is not None
    assert entry.action_target_ref == "row1"

    n2 = _make_node(role="button", name="Y", ref="y")
    entry2 = n2.to_ref_entry("NATIVE_APP")
    assert entry2 is not None
    assert entry2.action_target_ref is None


def test_snapshot_from_root_computes_screen_id():
    a = _make_node(role="button", name="A", ref="a")
    b = _make_node(role="button", name="B", ref="b")
    root = _make_node(role="container", children=[a, b])
    snap1 = NativeSnapshot.from_root(root=root)
    assert isinstance(snap1.screen_id, str)
    assert len(snap1.screen_id) == 6
    int(snap1.screen_id, 16)  # hex

    a2 = _make_node(role="button", name="A", ref="a")
    b2 = _make_node(role="button", name="B", ref="b")
    root2 = _make_node(role="container", children=[a2, b2])
    snap2 = NativeSnapshot.from_root(root=root2)
    assert snap1.screen_id == snap2.screen_id


def test_snapshot_from_root_screen_id_changes_with_content():
    root = _make_node(
        role="container",
        children=[
            _make_node(role="button", name="A", ref="a"),
            _make_node(role="button", name="B", ref="b"),
        ],
    )
    snap1 = NativeSnapshot.from_root(root=root)

    root2 = _make_node(
        role="container",
        children=[
            _make_node(role="button", name="A", ref="a"),
            _make_node(role="button", name="B", ref="b"),
            _make_node(role="button", name="C", ref="c"),
        ],
    )
    snap2 = NativeSnapshot.from_root(root=root2)
    assert snap1.screen_id != snap2.screen_id


def test_snapshot_to_ref_map():
    root = _make_node(
        role="container",
        children=[
            _make_node(role="button", name="A", ref="a"),
            _make_node(role="button", name="B", ref="b"),
            _make_node(role="text", name="hello"),
        ],
    )
    snap = NativeSnapshot.from_root(root=root)
    refs = snap.to_ref_map()
    assert set(refs.keys()) == {"a", "b"}


def test_find_text_exact_prefix_contains():
    root = _make_node(
        role="container",
        children=[
            _make_node(role="text", name="Storage"),
            _make_node(role="text", name="Storage Settings"),
            _make_node(role="text", name="Network Storage"),
        ],
    )
    snap = NativeSnapshot.from_root(root=root)
    matches = snap.find_text("Storage")
    assert [m.score for m in matches] == [100, 80, 60]


def test_find_text_target_is_nearest_actionable_ancestor():
    inner = _make_node(role="text", name="Storage")
    row = _make_node(role="row", name="", ref="r1", children=[inner])
    root = _make_node(role="container", children=[row])
    snap = NativeSnapshot.from_root(root=root)
    matches = snap.find_text("Storage")
    assert matches
    assert matches[0].target is row


def test_find_text_target_none_when_no_actionable_ancestor():
    lone = _make_node(role="text", name="Storage")
    root = _make_node(role="container", children=[lone])
    snap = NativeSnapshot.from_root(root=root)
    matches = snap.find_text("Storage")
    assert matches
    assert matches[0].target is None


def test_find_text_inputs_only():
    tb = _make_node(role="textbox", name="Email", ref="email")
    other = _make_node(role="text", name="Email Settings")
    root = _make_node(role="container", children=[tb, other])
    snap = NativeSnapshot.from_root(root=root)
    matches = snap.find_text("Email", inputs_only=True)
    assert len(matches) == 1
    assert matches[0].node is tb


def test_describe_ref_unknown():
    root = _make_node(role="container")
    snap = NativeSnapshot.from_root(root=root)
    out = snap.describe_ref("[ref:missing]")
    assert out.startswith("ERROR:")
    assert "missing" in out


def test_describe_ref_basic():
    btn = _make_node(
        role="button", name="OK", ref="ok", state=["selected"], bounds=(1, 2, 3, 4)
    )
    root = _make_node(role="container", children=[btn])
    snap = NativeSnapshot.from_root(root=root)
    out = snap.describe_ref("ok")
    assert "role:" in out
    assert "name:" in out
    assert "state:" in out
    assert "bounds:" in out


def test_to_text_renders_header_and_tree():
    btn = _make_node(role="button", name="OK", ref="ok")
    root = _make_node(role="container", children=[btn])
    snap = NativeSnapshot.from_root(root=root, nav={"back": True})
    out = snap.to_text()
    assert "screen_id:" in out
    assert "context:" in out
    assert "source:" in out
    assert "\n\n" in out  # blank line between header and body
    assert '- button "OK"' in out
    assert "nav:" in out
    assert "alerts:" in out


def test_to_text_warns_when_truncated():
    root = _make_node(
        role="container",
        children=[_make_node(role="button", name="OK", ref="ok")],
    )
    snap = NativeSnapshot.from_root(root=root, truncated=True)
    out = snap.to_text()

    assert "truncated: true" in out
    assert "WARNING: Snapshot output is truncated; some nodes are omitted." in out
    assert "Increase --max-nodes/--depth or narrow the scope." in out


def test_to_text_scope_inputs():
    tb = _make_node(role="textbox", name="Email", ref="email")
    btn = _make_node(role="button", name="Submit", ref="submit")
    root = _make_node(role="container", children=[tb, btn])
    snap = NativeSnapshot.from_root(root=root)
    out = snap.to_text(scope="inputs")
    assert '- textbox "Email"' in out
    assert "Submit" not in out


def test_to_text_scope_depth():
    great = _make_node(role="text", name="great")
    grand = _make_node(role="text", name="grand", children=[great])
    child = _make_node(role="text", name="child", children=[grand])
    root = _make_node(role="container", name="root", children=[child])
    snap = NativeSnapshot.from_root(root=root)
    out = snap.to_text(scope="depth:1")
    assert '- container "root"' in out
    assert '- text "child"' in out
    assert "grand" not in out
    assert "great" not in out
    assert "- ..." in out


def test_to_text_scope_active_layer():
    in_dialog = _make_node(role="button", name="DialogBtn", ref="db")
    dialog = _make_node(
        role="container",
        name="dlg",
        container_kind="dialog",
        children=[in_dialog],
    )
    other = _make_node(role="button", name="OtherBtn", ref="ob")
    root = _make_node(role="container", children=[other, dialog])
    snap = NativeSnapshot.from_root(root=root)
    out = snap.to_text(scope="active_layer")
    assert "DialogBtn" in out
    assert "OtherBtn" not in out


def test_to_text_scope_near_ref():
    c1 = _make_node(role="text", name="c1")
    c2 = _make_node(role="text", name="c2")
    row = _make_node(role="row", name="row", ref="row1", children=[c1, c2])
    other = _make_node(role="button", name="Outside", ref="out")
    root = _make_node(role="container", children=[row, other])
    snap = NativeSnapshot.from_root(root=root)
    out = snap.to_text(scope="near:row1")
    assert "row1" in out
    assert "c1" in out
    assert "c2" in out
    assert "Outside" not in out


def test_to_text_scope_ref_renders_exact_subtree_with_depth():
    great = _make_node(role="text", name="great")
    child = _make_node(role="text", name="child", children=[great])
    row = _make_node(role="row", name="row", ref="row1", children=[child])
    other = _make_node(role="button", name="Outside", ref="out")
    root = _make_node(role="container", children=[row, other])
    snap = NativeSnapshot.from_root(root=root)

    out = snap.to_text(scope="ref:row1,depth:0")

    assert "row1" in out
    assert "child" not in out
    assert "great" not in out
    assert "Outside" not in out
    assert "- ..." in out


def test_compute_diff_added_removed_changed():
    root_a = _make_node(
        role="container",
        children=[
            _make_node(role="button", name="Old Name", ref="changed"),
            _make_node(role="button", name="Bye", ref="gone"),
        ],
    )
    root_b = _make_node(
        role="container",
        children=[
            _make_node(role="button", name="New Name", ref="changed"),
            _make_node(role="button", name="Hi", ref="newone"),
        ],
    )
    snap_a = NativeSnapshot.from_root(root=root_a)
    snap_b = NativeSnapshot.from_root(root=root_b)
    diff = snap_a.compute_diff(snap_b)
    assert "added" in diff
    assert "removed" in diff
    assert "Old Name" in diff
    assert "New Name" in diff
