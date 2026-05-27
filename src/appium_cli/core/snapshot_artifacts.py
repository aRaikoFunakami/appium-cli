"""Serializable artifact bundle helpers for tree-first snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from appium_cli.core.snapshot import LocatorStrategy, RefEntry
from appium_cli.utils.paths import generate_snapshot_id, snapshot_bundle_paths


@dataclass(frozen=True)
class SnapshotBundlePayload:
    """In-memory content for one snapshot artifact bundle."""

    snapshot_id: str
    paths: dict[str, Path]
    meta_json: dict[str, Any]
    compact_yml: str
    full_yml: str
    refs_json: dict[str, Any]
    index_json: dict[str, Any]

    def artifacts(self) -> dict[str, dict[str, Any] | str]:
        """Return artifact content keyed by standard artifact name."""
        return {
            "meta": self.meta_json,
            "compact": self.compact_yml,
            "full": self.full_yml,
            "refs": self.refs_json,
            "index": self.index_json,
        }


def compute_snapshot_stats(index: dict[str, Any]) -> dict[str, int]:
    """Compute compact, agent-facing counts from a snapshot index artifact."""
    roles = index.get("roles", {})
    if not isinstance(roles, dict):
        roles = {}

    def role_count(role: str) -> int:
        value = roles.get(role, 0)
        return value if isinstance(value, int) else 0

    headings = 0
    for role, count in roles.items():
        if str(role).startswith("heading") and isinstance(count, int):
            headings += count

    containers = index.get("containers", [])
    inputs = index.get("inputs", [])
    return {
        "nodes": int(index.get("node_count") or 0),
        "refs": int(index.get("ref_count") or 0),
        "links": role_count("link"),
        "headings": headings,
        "buttons": role_count("button"),
        "textboxes": len(inputs) if isinstance(inputs, list) else 0,
        "containers": len(containers) if isinstance(containers, list) else 0,
    }


def create_snapshot_bundle_payload(
    snapshot_obj: Any,
    *,
    snapshot_id: str | None = None,
    source: str | None = None,
    context: str | None = None,
    screen_id: str | None = None,
    title: str | None = None,
    url: str | None = None,
    scope: str | None = None,
) -> SnapshotBundlePayload:
    """Build serializable snapshot artifact content without writing files."""
    metadata = _snapshot_metadata(
        snapshot_obj,
        snapshot_id=snapshot_id,
        source=source,
        context=context,
        screen_id=screen_id,
        title=title,
        url=url,
        scope=scope,
    )
    paths = snapshot_bundle_paths(metadata["snapshot_id"])
    metadata["artifacts"] = {name: str(path) for name, path in paths.items()}

    ref_entries = snapshot_obj.to_ref_map()
    refs_json = _serialize_refs(ref_entries, metadata)
    index_json = _build_index(snapshot_obj, ref_entries, metadata)

    return SnapshotBundlePayload(
        snapshot_id=metadata["snapshot_id"],
        paths=paths,
        meta_json=metadata,
        compact_yml=_snapshot_text(snapshot_obj, scope=scope, boxes=False),
        full_yml=_snapshot_text(snapshot_obj, scope=scope, boxes=True),
        refs_json=refs_json,
        index_json=index_json,
    )


def _snapshot_metadata(
    snapshot_obj: Any,
    *,
    snapshot_id: str | None,
    source: str | None,
    context: str | None,
    screen_id: str | None,
    title: str | None,
    url: str | None,
    scope: str | None,
) -> dict[str, Any]:
    resolved_source = source or getattr(snapshot_obj, "source_type", "unknown")
    resolved_screen_id = screen_id or getattr(snapshot_obj, "screen_id", "")
    resolved_snapshot_id = snapshot_id or generate_snapshot_id(
        resolved_source, resolved_screen_id or None
    )

    metadata: dict[str, Any] = {
        "snapshot_id": resolved_snapshot_id,
        "source": resolved_source,
        "screen_id": resolved_screen_id,
    }

    resolved_context = (
        context if context is not None else getattr(snapshot_obj, "context", None)
    )
    if resolved_context:
        metadata["context"] = resolved_context

    resolved_title = title if title is not None else getattr(snapshot_obj, "title", None)
    if resolved_title:
        metadata["title"] = resolved_title

    resolved_url = url if url is not None else getattr(snapshot_obj, "url", None)
    if resolved_url:
        metadata["url"] = resolved_url

    if getattr(snapshot_obj, "truncated", False):
        metadata["truncated"] = True
    if scope and scope != "full":
        metadata["scope"] = scope

    return metadata


def _snapshot_text(snapshot_obj: Any, *, scope: str | None = None, boxes: bool) -> str:
    text = snapshot_obj.to_text(scope=scope if scope != "full" else None, boxes=boxes)
    return text if text.endswith("\n") else text + "\n"


def _serialize_refs(
    ref_entries: dict[str, RefEntry], metadata: dict[str, Any]
) -> dict[str, Any]:
    return {
        "snapshot_id": metadata["snapshot_id"],
        "source": metadata["source"],
        "screen_id": metadata["screen_id"],
        **({"context": metadata["context"]} if "context" in metadata else {}),
        "refs": {
            ref: _serialize_ref_entry(entry)
            for ref, entry in sorted(ref_entries.items(), key=lambda item: item[0])
        },
    }


def _serialize_ref_entry(entry: RefEntry) -> dict[str, Any]:
    serialized: dict[str, Any] = {
        "role": entry.role,
        "name": entry.name,
        "context": entry.context,
        "source_type": entry.source_type,
        "expected_bounds": list(entry.expected_bounds),
        "strategies": [_serialize_strategy(strategy) for strategy in entry.strategies],
    }
    if entry.action_target_ref:
        serialized["action_target_ref"] = entry.action_target_ref
    return serialized


def _serialize_strategy(strategy: LocatorStrategy) -> dict[str, str]:
    return {"by": strategy.by, "value": strategy.value}


def _build_index(
    snapshot_obj: Any,
    ref_entries: dict[str, RefEntry],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    nodes = list(snapshot_obj.iter_nodes())
    roles: dict[str, int] = {}
    refs_by_tree: list[dict[str, Any]] = []
    containers: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []

    seen_refs: set[str] = set()
    for node in nodes:
        role = getattr(node, "role", "")
        if role:
            roles[role] = roles.get(role, 0) + 1

        ref = getattr(node, "ref", None)
        if ref:
            seen_refs.add(ref)
            refs_by_tree.append(_index_ref(node, ref_entries.get(ref)))

        if getattr(node, "container_kind", "") or getattr(node, "scrollable", False):
            containers.append(_index_container(node))

        if role == "textbox":
            inputs.append(_index_node_ref(node))

    for ref, entry in sorted(ref_entries.items(), key=lambda item: item[0]):
        if ref not in seen_refs:
            refs_by_tree.append(
                {
                    "ref": ref,
                    "role": entry.role,
                    "name": entry.name,
                    "bounds": list(entry.expected_bounds),
                    "actionable": True,
                    "editable": entry.role == "textbox",
                }
            )

    text_targets = _build_text_targets(nodes, refs_by_tree, metadata)

    return {
        "snapshot_id": metadata["snapshot_id"],
        "source": metadata["source"],
        "screen_id": metadata["screen_id"],
        **({"context": metadata["context"]} if "context" in metadata else {}),
        **({"title": metadata["title"]} if "title" in metadata else {}),
        **({"url": metadata["url"]} if "url" in metadata else {}),
        "node_count": len(nodes),
        "ref_count": len(ref_entries),
        "roles": dict(sorted(roles.items())),
        "refs": refs_by_tree,
        "containers": containers,
        "inputs": inputs,
        "text_targets": text_targets,
    }


def _build_text_targets(
    nodes: list[Any],
    refs_by_tree: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    """Persist native text leaves with their nearest real tap target."""
    if metadata.get("source") != "native":
        return []

    target_by_ref = {
        str(item.get("ref")): item for item in refs_by_tree if item.get("ref")
    }
    seen: set[tuple[str, str, tuple[int, int, int, int]]] = set()
    text_targets: list[dict[str, Any]] = []

    for node in nodes:
        action_target_ref = getattr(node, "action_target_ref", None)
        if not action_target_ref:
            continue
        text = str(getattr(node, "name", "") or getattr(node, "value", "") or "")
        if not text:
            continue
        bounds = tuple(getattr(node, "bounds", (0, 0, 0, 0)))
        key = (text, str(action_target_ref), bounds)
        if key in seen:
            continue
        seen.add(key)

        item: dict[str, Any] = {
            "text": text,
            "role": getattr(node, "role", ""),
            "bounds": list(bounds),
            "action_target_ref": str(action_target_ref),
            "tap_target_ref": str(action_target_ref),
        }
        target_item = target_by_ref.get(str(action_target_ref))
        if target_item:
            item["target_role"] = target_item.get("role", "")
            item["target_name"] = target_item.get("name", "")
            item["target_bounds"] = target_item.get("bounds")
            item["target_actionable"] = bool(target_item.get("actionable", False))
            item["target_editable"] = bool(target_item.get("editable", False))
        text_targets.append(item)

    return text_targets


def _index_ref(node: Any, entry: RefEntry | None) -> dict[str, Any]:
    item = _index_node_ref(node)
    if entry is not None:
        item["selector_count"] = len(entry.strategies)
        item["primary_strategy"] = (
            _serialize_strategy(entry.strategies[0]) if entry.strategies else None
        )
    return item


def _index_node_ref(node: Any) -> dict[str, Any]:
    role = getattr(node, "role", "")
    item: dict[str, Any] = {
        "ref": getattr(node, "ref", None),
        "role": role,
        "name": getattr(node, "name", ""),
        "bounds": list(getattr(node, "bounds", (0, 0, 0, 0))),
        "actionable": bool(getattr(node, "actionable", False)),
        "editable": bool(getattr(node, "editable", role == "textbox")),
    }
    value = getattr(node, "value", None)
    if value is not None:
        item["value"] = value
    state = getattr(node, "state", None)
    if state:
        item["state"] = list(state)
    action_target_ref = getattr(node, "action_target_ref", None)
    if action_target_ref:
        item["action_target_ref"] = action_target_ref
    return item


def _index_container(node: Any) -> dict[str, Any]:
    item = _index_node_ref(node)
    container_kind = getattr(node, "container_kind", "")
    if container_kind:
        item["container_kind"] = container_kind
    if getattr(node, "scrollable", False):
        item["scrollable"] = True
        direction = getattr(node, "scroll_direction", "")
        if direction:
            item["scroll_direction"] = direction
    return item
