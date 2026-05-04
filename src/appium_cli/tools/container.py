"""Container and verification tools."""

from __future__ import annotations

from appium_cli.daemon import state


def _snapshot_or_error():
    if state.current_snapshot is None:
        return None, "ERROR: スナップショットがありません。先に snapshot() を呼んでください。"
    return state.current_snapshot, ""


def list_containers() -> str:
    snapshot, error = _snapshot_or_error()
    if error:
        return error
    if not snapshot.containers:
        return "コンテナが検出されませんでした。"
    lines = [f"Containers on screen ({len(snapshot.containers)} total):", ""]
    for index, container in enumerate(snapshot.containers, 1):
        title = f' "{container.title}"' if container.title else ""
        lines.append(f"{index}. [ref:{container.ref}] {container.region}{title}")
        if container.scrollable:
            lines.append(f"   scrollable: yes ({container.scroll_direction or 'unknown'}) | ⚠ additional elements may be hidden off-screen")
        else:
            lines.append("   scrollable: no")
        visible_children = [item for item in snapshot.elements if item.ref in container.children_refs]
        lines.append(f"   children: {len(visible_children)} visible/total")
        sample = [item.name for item in visible_children[:3] if item.name]
        if sample:
            lines.append("   sample: " + ", ".join(sample))
        lines.append("")
    return "\n".join(lines).rstrip()


def find_container(text: str, role_hint: str = "") -> str:
    snapshot, error = _snapshot_or_error()
    if error:
        return error
    search = text.lower()
    matched_refs = {
        element.container_ref
        for element in snapshot.elements
        if search in element.name.lower() or search in (element.value or "").lower()
    }
    containers = [container for container in snapshot.containers if container.ref in matched_refs]
    if role_hint and role_hint != "full":
        containers = [container for container in containers if container.region == role_hint]
    if not containers:
        return f"'{text}' を含むコンテナが見つかりません。"
    lines: list[str] = []
    for container in containers:
        lines.append(f"container [ref:{container.ref}] {container.region}")
        if container.title:
            lines.append(f"  title: {container.title}")
        for child in [item for item in snapshot.elements if item.ref in container.children_refs]:
            lines.append(f"  {child.to_text()}")
        if container.scrollable:
            lines.append(f"⚠ This container is scrollable ({container.scroll_direction or 'unknown direction'}). Additional elements may exist off-screen. Scroll the container and re-check to discover all elements.")
        lines.append("")
    return "\n".join(lines).rstrip()


def within_container(container_ref: str, role: str = "", position: str = "first") -> str:
    snapshot, error = _snapshot_or_error()
    if error:
        return error
    normalized = container_ref.strip().strip("[]").removeprefix("ref:")
    container = next((item for item in snapshot.containers if item.ref == normalized), None)
    if container is None:
        return f"ERROR: container_ref '{normalized}' が見つかりません。"
    elements = [item for item in snapshot.elements if item.ref in container.children_refs]
    if role:
        elements = [item for item in elements if item.role == role]
    if not elements:
        return "条件に一致する要素が見つかりません。"
    if position == "last":
        return elements[-1].to_text()
    if position in {"right_most", "left_most"}:
        reverse = position == "right_most"
        elements = sorted(elements, key=lambda item: item.bounds.center[0] if item.bounds else 0, reverse=reverse)
        return elements[0].to_text()
    if len(elements) == 1:
        return elements[0].to_text()
    lines = [f"{len(elements)} 件の候補:"]
    lines.extend(f"  {item.to_text()}" for item in elements[:10])
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
        element = next((item for item in snapshot.elements if item.ref == normalized), None)
        if element:
            return f"visible=true\n{element.to_text()}"
        return f"visible=false\nref '{normalized}' が見つかりません。"
    search = text.lower()
    found = [item.to_text() for item in snapshot.elements if search in item.name.lower() or search in (item.value or "").lower()]
    if not found:
        return f"visible=false\n'{text}' が見つかりません。"
    lines = [f"visible=true ({len(found)} 件)"]
    lines.extend(f"  {item}" for item in found[:5])
    return "\n".join(lines)
