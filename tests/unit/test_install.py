from pathlib import Path
import json

from typer.testing import CliRunner

from appium_cli.__main__ import app
from appium_cli.cli import install as install_module


def _make_skill_source(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    skill = root / "appium-cli"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: appium-cli\nallowed-tools: Bash(appium-cli:*)\n---\n", encoding="utf-8")
    (skill / "references" / "device-info.md").write_text("# Device Info\n", encoding="utf-8")
    return root


def test_install_skills_dry_run_does_not_write(monkeypatch, tmp_path: Path) -> None:
    source = _make_skill_source(tmp_path)
    monkeypatch.setattr(install_module, "skills_source_root", lambda: source)
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["install", "--skills", "--target=project", "--dry-run"])
        assert result.exit_code == 0
        assert "would install" in result.output
        assert not Path(".agents").exists()


def test_install_skills_force_writes_files(monkeypatch, tmp_path: Path) -> None:
    source = _make_skill_source(tmp_path)
    monkeypatch.setattr(install_module, "skills_source_root", lambda: source)
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["install", "--skills", "--target=project", "--force"])
        assert result.exit_code == 0
        assert Path(".agents/skills/appium-cli/SKILL.md").is_file()
        assert Path(".agents/skills/appium-cli/references/device-info.md").is_file()


def test_install_skills_json_output(monkeypatch, tmp_path: Path) -> None:
    source = _make_skill_source(tmp_path)
    monkeypatch.setattr(install_module, "skills_source_root", lambda: source)
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(app, ["install", "--skills", "--target=project", "--dry-run", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["target"] == "project"
        assert payload["results"][0]["files"][0]["status"] == "would_install"
        assert not Path(".agents").exists()
