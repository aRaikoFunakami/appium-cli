"""OpenAI Skills API helpers.

This module is intentionally independent from the browser run path. Local
Appium automation continues to use the appium-cli daemon bridge.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import httpx


OPENAI_SKILLS_URL = "https://api.openai.com/v1/skills"


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    skill_id: str
    version: str | int | None
    source_hash: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "skill_id": self.skill_id,
                "version": self.version,
                "source_hash": self.source_hash,
            },
            indent=2,
            sort_keys=True,
        )


def skill_source_hash(skill_dir: Path) -> str:
    """Hash skill source content deterministically."""

    h = hashlib.sha256()
    for path in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(skill_dir).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def build_skill_zip(skill_dir: Path) -> bytes:
    """Build a zip payload for OpenAI Skills API upload."""

    skill_dir = skill_dir.resolve()
    manifest = skill_dir / "SKILL.md"
    if not manifest.exists():
        raise FileNotFoundError(f"SKILL.md not found in skill directory: {skill_dir}")

    buf = io.BytesIO()
    with ZipFile(buf, "w", compression=ZIP_DEFLATED) as zf:
        for path in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(skill_dir).as_posix())
    return buf.getvalue()


def read_skill_metadata(path: Path) -> SkillMetadata | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SkillMetadata(
        skill_id=str(payload["skill_id"]),
        version=payload.get("version"),
        source_hash=str(payload["source_hash"]),
    )


def write_skill_metadata(path: Path, metadata: SkillMetadata) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(metadata.to_json() + "\n", encoding="utf-8")


async def upload_openai_skill(
    skill_dir: Path,
    *,
    api_key: str,
    metadata_path: Path | None = None,
    force: bool = False,
    base_url: str = OPENAI_SKILLS_URL,
) -> SkillMetadata:
    """Upload a skill directory to OpenAI Skills API.

    Reuses existing metadata when the source hash is unchanged unless
    ``force=True``.
    """

    source_hash = skill_source_hash(skill_dir)
    if metadata_path is not None and not force:
        existing = read_skill_metadata(metadata_path)
        if existing is not None and existing.source_hash == source_hash:
            return existing

    zip_bytes = build_skill_zip(skill_dir)
    headers = {"Authorization": f"Bearer {api_key}"}
    files = {"files": (f"{skill_dir.name}.zip", zip_bytes, "application/zip")}
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(base_url, headers=headers, files=files)
    response.raise_for_status()
    payload = response.json()
    skill_id = str(payload.get("skill_id") or payload.get("id") or "")
    if not skill_id:
        raise ValueError(f"OpenAI Skills API response did not include skill_id: {payload}")
    metadata = SkillMetadata(
        skill_id=skill_id,
        version=payload.get("version"),
        source_hash=source_hash,
    )
    if metadata_path is not None:
        write_skill_metadata(metadata_path, metadata)
    return metadata
