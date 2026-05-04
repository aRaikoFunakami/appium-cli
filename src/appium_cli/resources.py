"""Helpers for locating repository/package resources."""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def skills_source_root() -> Path | Traversable:
    """Return the source root containing appium-cli skill files.

    Editable installs use the repository-level ``skills/`` directory so changes
    are reflected immediately. Built wheels fall back to package resources.
    """

    repo_skills = repository_root() / "skills"
    if repo_skills.is_dir():
        return repo_skills
    return resources.files("appium_cli").joinpath("skills")
