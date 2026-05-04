"""Install bundled agent skills."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Iterable, Literal

import typer

from appium_cli.resources import skills_source_root
from appium_cli.utils import exit_codes


Target = Literal["project", "claude-code", "copilot-cli", "all"]


@dataclass(frozen=True)
class CopyItem:
    relative_path: Path
    content: bytes


def _iter_files(root) -> Iterable[CopyItem]:
    def walk(node, prefix: Path) -> Iterable[CopyItem]:
        for child in node.iterdir():
            child_prefix = prefix / child.name
            if child.is_dir():
                yield from walk(child, child_prefix)
            elif child.is_file():
                yield CopyItem(child_prefix, child.read_bytes())

    yield from walk(root, Path())


def _skill_source():
    source = skills_source_root().joinpath("appium-cli")
    if not source.is_dir():
        raise FileNotFoundError("bundled appium-cli skill was not found")
    return source


def _project_destination() -> Path:
    return Path.cwd() / ".agents" / "skills" / "appium-cli"


def _claude_destination() -> Path:
    project_parent = Path.cwd() / ".claude" / "skills"
    if project_parent.exists():
        return project_parent / "appium-cli"
    return Path.home() / ".claude" / "skills" / "appium-cli"


def _copilot_destination() -> Path:
    return Path.home() / ".copilot" / "skills" / "appium-cli"


def _destinations(target: Target) -> list[Path]:
    if target == "project":
        return [_project_destination()]
    if target == "claude-code":
        return [_claude_destination()]
    if target == "copilot-cli":
        return [_copilot_destination()]

    destinations = [_project_destination()]
    for candidate in (_claude_destination(), _copilot_destination()):
        if candidate.parent.exists():
            destinations.append(candidate)
    return destinations


def _install_to(destination: Path, files: list[CopyItem], *, dry_run: bool, force: bool) -> None:
    typer.echo(f"{'would install' if dry_run else 'installing'}: {destination}")
    for item in files:
        target = destination / item.relative_path
        typer.echo(f"  {item.relative_path}")
        if dry_run:
            continue
        if target.exists():
            existing = target.read_bytes()
            if existing == item.content:
                continue
            if not force:
                typer.echo(f"ERROR: {target} differs; rerun with --force to overwrite", err=True)
                raise typer.Exit(exit_codes.GENERAL_ERROR)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.content)


def install(
    skills: Annotated[
        bool,
        typer.Option("--skills", help="Install bundled appium-cli agent skill."),
    ] = False,
    target: Annotated[
        Target,
        typer.Option("--target", help="Skill destination target."),
    ] = "project",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show planned writes without changing files."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite files that differ from bundled skill files."),
    ] = False,
) -> None:
    """Install optional appium-cli assets."""

    if not skills:
        typer.echo("ERROR: only --skills is currently supported", err=True)
        raise typer.Exit(exit_codes.GENERAL_ERROR)

    source = _skill_source()
    files = list(_iter_files(source))
    if not files:
        typer.echo("ERROR: bundled appium-cli skill is empty", err=True)
        raise typer.Exit(exit_codes.GENERAL_ERROR)

    for destination in _destinations(target):
        _install_to(destination, files, dry_run=dry_run, force=force)
