from pathlib import Path

import pytest
from typer.testing import CliRunner

from appium_cli.__main__ import app
from appium_cli.resources import repository_root


pytestmark = pytest.mark.e2e


def test_install_skills_project_target_byte_equal(tmp_path: Path) -> None:
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        dry_run = runner.invoke(app, ["install", "--skills", "--target=project", "--dry-run"])
        assert dry_run.exit_code == 0
        assert not Path(".agents").exists()

        install = runner.invoke(app, ["install", "--skills", "--target=project", "--force"])
        assert install.exit_code == 0

        source = repository_root() / "skills" / "appium-cli"
        destination = Path(".agents") / "skills" / "appium-cli"
        for source_file in source.rglob("*"):
            if source_file.is_file():
                relative = source_file.relative_to(source)
                assert (destination / relative).read_bytes() == source_file.read_bytes()
