"""Observation tools."""

from __future__ import annotations

import json

from appium_cli.core.snapshot import SnapshotElement, compress_xml, element_to_ref_entry, generate_snapshot
from appium_cli.daemon import state


def _require_driver():
    if state.driver is None:
        raise ValueError("Driver is not initialized")
    return state.driver


def refresh_snapshot(scope: str = "full") -> str:
    driver = _require_driver()
    xml_source = driver.page_source
    snapshot_obj, ref_map = generate_snapshot(xml_source, scope=scope)
    state.current_snapshot = snapshot_obj
    state.current_ref_map = {ref: element_to_ref_entry(element) for ref, element in ref_map.items()}
    return snapshot_obj.to_text(scope=scope)


def snapshot(scope: str = "full") -> str:
    return refresh_snapshot(scope)


def _normalize_ref(ref: str) -> str:
    return ref.strip().strip("[]").removeprefix("ref:")


def _find_element(ref: str) -> SnapshotElement | None:
    normalized = _normalize_ref(ref)
    snapshot_obj = state.current_snapshot
    if not snapshot_obj:
        return None
    return next((element for element in snapshot_obj.elements if element.ref == normalized), None)


def describe(ref: str) -> str:
    if state.current_snapshot is None:
        return "ERROR: スナップショットがありません。先に snapshot() を呼んでください。"
    target = _find_element(ref)
    if not target:
        normalized = _normalize_ref(ref)
        return f"ERROR: ref '{normalized}' が見つかりません。snapshot() で画面を再確認してください。"

    lines = [
        f"要素: {target.to_text()}",
        f"role: {target.role}",
        f"name: {target.name}",
    ]
    if target.value is not None:
        lines.append(f"value: {target.value}")
    lines.append(f"state: {', '.join(target.state) if target.state else 'none'}")
    lines.append(f"bounds: {target.bounds}")

    snapshot_obj = state.current_snapshot
    if target.container_ref:
        container = next((item for item in snapshot_obj.containers if item.ref == target.container_ref), None)
        if container:
            lines.append(f"container: {container.region} ({container.ref})")
            if container.title:
                lines.append(f"container_title: {container.title}")
            siblings = [item for item in snapshot_obj.elements if item.container_ref == target.container_ref and item.ref != target.ref]
            if siblings:
                lines.append("近傍要素:")
                for sibling in siblings[:5]:
                    lines.append(f"  {sibling.to_text()}")
    return "\n".join(lines)


def find_by_text(text: str, scope: str = "full") -> str:
    if state.current_snapshot is None:
        return "ERROR: スナップショットがありません。先に snapshot() を呼んでください。"

    snapshot_obj = state.current_snapshot
    search_lower = text.lower()
    candidates: list[dict] = []
    target_elements = snapshot_obj.elements
    if scope == "inputs":
        target_elements = [element for element in snapshot_obj.elements if element.role == "textbox"]
    elif scope not in ("", "full", None):
        allowed_refs = {ref for container in snapshot_obj._filter_containers(scope) for ref in container.children_refs}
        if allowed_refs:
            target_elements = [element for element in snapshot_obj.elements if element.ref in allowed_refs]

    for element in target_elements:
        name_lower = element.name.lower()
        value_lower = (element.value or "").lower()
        if name_lower == search_lower or value_lower == search_lower:
            score = 100
        elif name_lower.startswith(search_lower) or value_lower.startswith(search_lower):
            score = 80
        elif search_lower in name_lower or search_lower in value_lower:
            score = 60
        else:
            continue
        candidates.append({"ref": element.ref, "role": element.role, "name": element.name, "score": score})

    candidates.sort(key=lambda item: item["score"], reverse=True)
    if not candidates:
        return f"'{text}' に一致する要素が見つかりません。"
    lines = [f"'{text}' の検索結果 ({len(candidates)} 件):"]
    for candidate in candidates[:10]:
        lines.append(f"  [ref:{candidate['ref']}] {candidate['role']} \"{candidate['name']}\" (score={candidate['score']})")
    return "\n".join(lines)


def screenshot(region: str = "full") -> str:
    import base64

    from appium_cli.utils.paths import read_current_session, screenshot_path, session_artifact_dir

    driver = _require_driver()
    b64 = driver.get_screenshot_as_base64()

    result: dict = {
        "type": "screenshot",
        "image_base64": b64,
        "region": region,
    }

    sid = read_current_session()
    if sid:
        artifact_dir = session_artifact_dir(sid)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        png_path = screenshot_path(sid)
        png_path.write_bytes(base64.b64decode(b64))
        result["path"] = str(png_path)
        result["size_bytes"] = png_path.stat().st_size
        result["mime_type"] = "image/png"

    return json.dumps(result)


def get_page_source() -> str:
    driver = _require_driver()
    return compress_xml(driver.page_source)
