"""Tests for OpenAI Skills API helpers."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from agent_browser.skills import (
    SkillMetadata,
    build_skill_zip,
    read_skill_metadata,
    skill_source_hash,
    write_skill_metadata,
)


def test_build_skill_zip_requires_manifest(tmp_path: Path) -> None:
    try:
        build_skill_zip(tmp_path)
    except FileNotFoundError as exc:
        assert "SKILL.md" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected FileNotFoundError")


def test_build_skill_zip_contains_relative_files(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text("---\nname: appium-cli\n---\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.py").write_text("print('ok')\n", encoding="utf-8")

    zip_bytes = build_skill_zip(tmp_path)
    zip_path = tmp_path / "skill.zip"
    zip_path.write_bytes(zip_bytes)

    with ZipFile(zip_path) as zf:
        assert sorted(zf.namelist()) == ["SKILL.md", "scripts/run.py"]


def test_skill_metadata_roundtrip(tmp_path: Path) -> None:
    metadata = SkillMetadata(skill_id="skill_123", version=1, source_hash="abc")
    path = tmp_path / ".appium-cli" / "openai-skill.json"
    write_skill_metadata(path, metadata)
    assert read_skill_metadata(path) == metadata


def test_skill_source_hash_changes_with_content(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text("a", encoding="utf-8")
    h1 = skill_source_hash(tmp_path)
    (tmp_path / "SKILL.md").write_text("b", encoding="utf-8")
    assert skill_source_hash(tmp_path) != h1
