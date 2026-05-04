from pathlib import Path

from appium_cli.resources import skills_source_root


def test_skills_source_root_contains_skill_file() -> None:
    root = skills_source_root()
    skill_file = Path(root) / "appium-cli" / "SKILL.md"
    assert skill_file.is_file()
    text = skill_file.read_text(encoding="utf-8")
    assert "name: appium-cli" in text
    assert "allowed-tools: Bash(appium-cli:*)" in text
