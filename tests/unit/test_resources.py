from pathlib import Path

from appium_cli.resources import skills_source_root


def test_skills_source_root_contains_skill_file() -> None:
    root = skills_source_root()
    skill_file = Path(root) / "appium-cli" / "SKILL.md"
    assert skill_file.is_file()
    text = skill_file.read_text(encoding="utf-8")
    assert "name: appium-cli" in text
    assert "allowed-tools: Bash(appium-cli:*)" in text


def test_skill_top_level_documents_command_catalog() -> None:
    root = skills_source_root()
    text = (Path(root) / "appium-cli" / "SKILL.md").read_text(encoding="utf-8")

    assert "## Observation commands" in text
    assert "## Actions" in text
    assert "## Core workflow" in text
    assert "appium-cli --raw snapshot > before.yml" in text
    assert "appium-cli snapshot_show latest" in text
    assert "appium-cli web_refs latest --role=button" in text
    assert "appium-cli web_text" in text
    assert "appium-cli web_query \"input,button,a\"" in text
    assert "appium-cli scroll_down recycler_view" in text
    assert "Observe again after actions" in text
    assert '--or-text' in text
