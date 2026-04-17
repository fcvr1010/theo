"""End-to-end tests for Theo CLI (subprocess invocation)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.e2e
class TestTheoUseE2E:
    def test_creates_theo_directory_structure(self, tmp_path: Path) -> None:
        # Initialise a git repo so head_commit works
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, text=True, check=True)
        git_result = subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test",
                "commit",
                "--allow-empty",
                "-m",
                "init",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert git_result.returncode == 0, f"git commit failed: {git_result.stderr}"

        result = subprocess.run(
            ["theo", "use", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        # .theo/ directory exists
        assert (tmp_path / ".theo").is_dir()

        # config.json is valid JSON with required fields
        config_path = tmp_path / ".theo" / "config.json"
        assert config_path.exists()
        config = json.loads(config_path.read_text())
        assert "project_slug" in config
        assert "db_path" in config
        assert "created" in config

        # All 7 CSV files exist
        expected_csvs = [
            "concepts.csv",
            "source_files.csv",
            "part_of.csv",
            "belongs_to.csv",
            "interacts_with.csv",
            "depends_on.csv",
            "imports.csv",
        ]
        for csv_name in expected_csvs:
            assert (tmp_path / ".theo" / csv_name).exists(), f"Missing: {csv_name}"

        # .gitignore contains .theo/db/
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert ".theo/db/" in gitignore.read_text()

        # .mcp.json is valid JSON with mcpServers.theo
        mcp_path = tmp_path / ".mcp.json"
        assert mcp_path.exists()
        mcp = json.loads(mcp_path.read_text())
        assert "theo" in mcp.get("mcpServers", {})


@pytest.mark.e2e
class TestTheoReloadE2E:
    def test_reload_picks_up_manual_csv_edit(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, text=True, check=True)
        git_result = subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test",
                "commit",
                "--allow-empty",
                "-m",
                "init",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert git_result.returncode == 0, f"git commit failed: {git_result.stderr}"
        subprocess.run(["theo", "use", str(tmp_path)], capture_output=True, text=True, check=True)

        # Simulate a manual edit to the CSV source-of-truth.
        concepts_csv = tmp_path / ".theo" / "concepts.csv"
        concepts_csv.write_text('manual,"Manual Concept",0,"","",""\n')

        result = subprocess.run(
            ["theo", "reload", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Reloaded" in result.stdout

        stats = subprocess.run(
            ["theo", "stats", str(tmp_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        # One Concept row (from the manual CSV edit) should now be in the DB.
        assert "Concept" in stats.stdout


@pytest.mark.e2e
class TestTheoStatsE2E:
    def test_stats_exits_zero(self, tmp_path: Path) -> None:
        # Init a git repo and theo project
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, text=True, check=True)
        git_result = subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test",
                "commit",
                "--allow-empty",
                "-m",
                "init",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert git_result.returncode == 0, f"git commit failed: {git_result.stderr}"
        subprocess.run(["theo", "use", str(tmp_path)], capture_output=True, text=True)

        result = subprocess.run(
            ["theo", "stats", str(tmp_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Theo Graph Statistics" in result.stdout
