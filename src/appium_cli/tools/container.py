"""Container and verification tools."""

from __future__ import annotations

from appium_cli.core.native_snapshot import NativeSnapshot, NativeSnapshotNode
from appium_cli.core.web_snapshot import WebSnapshot
from appium_cli.daemon import state


def _snapshot_or_error():
    if state.current_snapshot is None:
        return None, "ERROR: スナップショットがありません。先に snapshot() を呼んでください。"
    return state.current_snapshot, ""


def _iter_containers(snapshot: NativeSnapshot) -> list[NativeSnapshotNode]:
    """All nodes with non-empty container_kind."""
    return [n for n in snapshot.iter_nodes() if n.container_kind]


def _container_children(node: NativeSnapshotNode) -> list[NativeSnapshotNode]:
    """Return all descendants (with refs) belonging to the container subtree."""
    result: list[NativeSnapshotNode] = []
    for descendant in node.iter_nodes(include_self=False):
        if descendant.ref:
            result.append(descendant)
    return result


def list_containers() -> str:
    snapshot, error = _snapshot_or_error()
    if error:
        return error
    if isinstance(snapshot, WebSnapshot):
        return "WebView snapshots use the DOM tree as structure; container commands are native-only."
    containers = _iter_containers(snapshot)
    if not containers:
        return "コンテナが検出されませんでした。"
    lines = [f"Containers on screen ({len(containers)} total):", ""]
    for index, container in enumerate(containers, 1):
        ref_display = container.ref or "-"
        name_display = f' "{container.name}"' if container.name else ""
        lines.append(f"{index}. [ref:{ref_display}] {container.container_kind}{name_display}")
        if container.scrollable:
            lines.append(f"   scrollable: yes ({container.scroll_direction or 'unknown'}) | ⚠ additional elements may be hidden off-screen")
        else:
            lines.append("   scrollable: no")
        visible_children = _container_children(container)
        lines.append(f"   children: {len(visible_children)} visible/total")
        sample = [child.name for child in visible_children[:3] if child.name]
        if sample:
            lines.append("   sample: " + ", ".join(sample))
        lines.append("")
    return "\n".join(lines).rstrip()


def find_container(text: str, role_hint: str = "") -> str:
    snapshot, error = _snapshot_or_error()
    if error:
        return error
    if isinstance(snapshot, WebSnapshot):
        return "WebView snapshots use the DOM tree as structure; find_container is native-only."
    search = text.lower()
    matched: list[NativeSnapshotNode] = []
    for container in _iter_containers(snapshot):
        if role_hint and role_hint != "full" and container.container_kind != role_hint:
            continue
        for child in _container_children(container):
            if search in child.name.lower() or search in (child.value or "").lower():
                matched.append(container)
                break
    if not matched:
        return f"'{text}' を含むコンテナが見つかりません。"
    lines: list[str] = []
    for container in matched:
        ref_display = container.ref or "-"
        lines.append(f"container [ref:{ref_display}] {container.container_kind}")
        if container.name:
            lines.append(f"  title: {container.name}")
        for child in _container_children(container):
            lines.append(f"  {child.to_line()}")
        if container.scrollable:
            lines.append(f"⚠ This container is scrollable ({container.scroll_direction or 'unknown direction'}). Additional elements may exist off-screen. Scroll the container and re-check to discover all elements.")
        lines.append("")
    return "\n".join(lines).rstrip()


def within_container(container_ref: str, role: str = "", position: str = "first") -> str:
    snapshot, error = _snapshot_or_error()
    if error:
        return error
    if isinstance(snapshot, WebSnapshot):
        return "WebView snapshots use the DOM tree as structure; within_container is native-only."
    normalized = container_ref.strip().strip("[]").removeprefix("ref:")
    container = snapshot.find_ref(normalized)
    if container is None or container.container_kind == "":
        return f"ERROR: container_ref '{normalized}' が見つかりません。"
    elements = _container_children(container)
    if role:
        elements = [item for item in elements if item.role == role]
    if not elements:
        return "条件に一致する要素が見つかりません。"
    if position == "last":
        return elements[-1].to_line()
    if position in {"right_most", "left_most"}:
        reverse = position == "right_most"
        elements = sorted(elements, key=lambda item: item.bounds[0] if item.bounds else 0, reverse=reverse)
        return elements[0].to_line()
    if len(elements) == 1:
        return elements[0].to_line()
    lines = [f"{len(elements)} 件の候補:"]
    lines.extend(f"  {item.to_line()}" for item in elements[:10])
    lines.append("→ Use tap(ref) with the desired ref.")
    return "\n".join(lines)


def assert_visible(text: str = "", ref: str = "") -> str:
    snapshot, error = _snapshot_or_error()
    if error:
        return error
    if not text and not ref:
        return "ERROR: text または ref のいずれかを指定してください。"
    if ref:
        normalized = ref.strip().strip("[]").removeprefix("ref:")
        if isinstance(snapshot, WebSnapshot):
            node = snapshot.find_ref(normalized)
            if node:
                return f"visible=true\n{node.to_text()}"
            return f"visible=false\nref '{normalized}' が見つかりません。"
        node = snapshot.find_ref(normalized)
        if node:
            return f"visible=true\n{node.to_line()}"
        return f"visible=false\nref '{normalized}' が見つかりません。"
    if isinstance(snapshot, WebSnapshot):
        matches = snapshot.find_text(text)
        if not matches:
            return f"visible=false\n'{text}' が見つかりません。"
        lines = [f"visible=true ({len(matches)} 件)"]
        for match in matches[:5]:
            target_ref = match.target.ref if match.target and match.target.ref else ""
            suffix = f" -> action target [ref:{target_ref}]" if target_ref and target_ref != match.node.ref else ""
            lines.append(f"  {match.node.to_text()}{suffix}")
        return "\n".join(lines)
    matches = snapshot.find_text(text)
    if not matches:
        return f"visible=false\n'{text}' が見つかりません。"
    lines = [f"visible=true ({len(matches)} 件)"]
    for match in matches[:5]:
        target_ref = match.target.ref if match.target and match.target.ref else ""
        suffix = f" -> action target [ref:{target_ref}]" if target_ref and target_ref != match.node.ref else ""
        lines.append(f"  {match.node.to_line()}{suffix}")
    return "\n".join(lines)
