"""Load normalized snapshots from appium-cli artifact files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_browser.world.model import Bounds, RefView, Snapshot, TextTarget


@dataclass(frozen=True, slots=True)
class SnapshotArtifacts:
    """Paths for the JSON/YAML files belonging to one snapshot."""

    base: Path
    index: Path
    meta: Path | None = None
    refs: Path | None = None
    compact: Path | None = None
    full: Path | None = None


def discover_snapshot_artifacts(snapshot_ref: str | Path, snapshots_dir: Path | None = None) -> SnapshotArtifacts:
    """Discover sidecar artifact files for a snapshot id or artifact path."""
    ref_path = Path(snapshot_ref)
    if snapshots_dir is not None and not ref_path.is_absolute():
        ref_path = snapshots_dir / ref_path

    base = _base_path(ref_path)
    index = base.with_suffix(".index.json")
    if not index.exists():
        raise FileNotFoundError(f"snapshot index artifact not found: {index}")

    return SnapshotArtifacts(
        base=base,
        index=index,
        meta=_optional(base.with_suffix(".meta.json")),
        refs=_optional(base.with_suffix(".refs.json")),
        compact=_optional(base.with_suffix(".compact.yml")),
        full=_optional(base.with_suffix(".full.yml")),
    )


def load_snapshot(snapshot_ref: str | Path, snapshots_dir: Path | None = None) -> Snapshot:
    """Load a normalized Snapshot from appium-cli JSON artifacts."""
    artifacts = discover_snapshot_artifacts(snapshot_ref, snapshots_dir=snapshots_dir)
    index_data = _load_json(artifacts.index)
    meta_data = _load_json(artifacts.meta) if artifacts.meta else {}
    refs_data = _load_json(artifacts.refs) if artifacts.refs else {}

    refs = _build_refs(index_data=index_data, refs_data=refs_data)
    _assign_parent_child_refs(refs)
    text_targets = _build_text_targets(index_data)
    screen_bounds = _screen_bounds(refs)

    return Snapshot(
        id=str(meta_data.get("snapshot_id") or index_data.get("snapshot_id") or artifacts.base.name),
        screen_id=str(meta_data.get("screen_id") or index_data.get("screen_id") or ""),
        context=str(meta_data.get("context") or index_data.get("context") or ""),
        refs=refs,
        text_targets=text_targets,
        containers=[
            item["ref"]
            for item in index_data.get("containers", [])
            if isinstance(item, dict) and isinstance(item.get("ref"), str)
        ],
        screen_bounds=screen_bounds,
        raw_artifact_paths={
            key: path
            for key, path in {
                "index": artifacts.index,
                "meta": artifacts.meta,
                "refs": artifacts.refs,
                "compact": artifacts.compact,
                "full": artifacts.full,
            }.items()
            if path is not None
        },
    )


def _base_path(path: Path) -> Path:
    name = path.name
    for suffix in (".index.json", ".meta.json", ".refs.json", ".compact.yml", ".full.yml"):
        if name.endswith(suffix):
            return path.with_name(name[: -len(suffix)])
    return path


def _optional(path: Path) -> Path | None:
    return path if path.exists() else None


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def _build_refs(index_data: dict[str, Any], refs_data: dict[str, Any]) -> dict[str, RefView]:
    refs: dict[str, RefView] = {}

    for item in index_data.get("refs", []):
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            continue
        ref = item["ref"]
        refs[ref] = RefView(
            ref=ref,
            role=str(item.get("role") or ""),
            name=str(item.get("name") or ""),
            bounds=_bounds(item.get("bounds")),
            actionable=bool(item.get("actionable", False)),
            editable=bool(item.get("editable", False)),
        )

    for item in index_data.get("containers", []):
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            continue
        ref = item["ref"]
        view = refs.get(ref)
        if view is None:
            view = RefView(ref=ref)
            refs[ref] = view
        view.role = str(item.get("role") or view.role)
        view.name = str(item.get("name") or view.name)
        view.bounds = _bounds(item.get("bounds")) or view.bounds
        view.actionable = bool(item.get("actionable", view.actionable))
        view.editable = bool(item.get("editable", view.editable))
        view.scrollable = bool(item.get("scrollable", True))
        view.scroll_direction = item.get("scroll_direction") or view.scroll_direction
        view.container_kind = item.get("container_kind") or view.container_kind

    raw_refs = refs_data.get("refs", {})
    if isinstance(raw_refs, dict):
        for ref, item in raw_refs.items():
            if not isinstance(item, dict):
                continue
            view = refs.get(ref)
            if view is None:
                view = RefView(ref=ref)
                refs[ref] = view
            view.role = str(item.get("role") or view.role)
            view.name = str(item.get("name") or view.name)
            view.bounds = view.bounds or _bounds(item.get("expected_bounds"))

    return refs


def _build_text_targets(index_data: dict[str, Any]) -> list[TextTarget]:
    targets: list[TextTarget] = []
    for item in index_data.get("text_targets", []):
        if not isinstance(item, dict):
            continue
        targets.append(
            TextTarget(
                text=str(item.get("text") or ""),
                bounds=_bounds(item.get("bounds")),
                tap_target_ref=item.get("tap_target_ref"),
                action_target_ref=item.get("action_target_ref"),
                target_role=str(item.get("target_role") or ""),
                target_bounds=_bounds(item.get("target_bounds")),
            )
        )
    return targets


def _bounds(value: Any) -> Bounds | None:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    try:
        return tuple(int(part) for part in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def _assign_parent_child_refs(refs: dict[str, RefView]) -> None:
    containers = [ref for ref in refs.values() if ref.scrollable or ref.container_kind is not None]
    for child in refs.values():
        parents = [container for container in containers if container.contains(child)]
        if not parents:
            continue
        parent = min(parents, key=lambda candidate: candidate.area)
        child.parent_ref = parent.ref
        parent.children.append(child.ref)


def _screen_bounds(refs: dict[str, RefView]) -> Bounds | None:
    bounds = [ref.bounds for ref in refs.values() if ref.bounds is not None]
    if not bounds:
        return None
    return (
        min(bound[0] for bound in bounds),
        min(bound[1] for bound in bounds),
        max(bound[2] for bound in bounds),
        max(bound[3] for bound in bounds),
    )
