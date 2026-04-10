"""Tests for theo.cli."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from theo import __version__
from theo.cli import _is_url, main
from theo.config import TheoConfig
from theo.repo_manager import RepoManager, slug_from_url

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def config(tmp_path: Path) -> TheoConfig:
    """Create a TheoConfig pointing to a temp directory."""
    cfg = TheoConfig(base_dir=tmp_path / "theo-home")
    cfg.ensure_dirs()
    return cfg


@pytest.fixture()
def manager(config: TheoConfig) -> RepoManager:
    """Create a RepoManager with a temp-dir config."""
    return RepoManager(config)


@pytest.fixture()
def bare_repo(tmp_path: Path) -> str:
    """Create a bare git repository with one commit, returning its path.

    This serves as a local "remote" for clone tests without network calls.
    """
    bare_path = tmp_path / "bare-remote.git"
    bare_path.mkdir()
    subprocess.run(["git", "init", "--bare", str(bare_path)], check=True, capture_output=True)

    # Create a temporary clone, add a commit, push back to bare.
    work_path = tmp_path / "bare-work"
    subprocess.run(
        ["git", "clone", str(bare_path), str(work_path)],
        check=True,
        capture_output=True,
    )
    (work_path / "README.md").write_text("# Test repo\n")
    subprocess.run(
        ["git", "-C", str(work_path), "add", "README.md"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work_path), "commit", "-m", "initial commit"],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        },
    )
    subprocess.run(
        ["git", "-C", str(work_path), "push"],
        check=True,
        capture_output=True,
    )
    return str(bare_path)


# ── URL detection ────────────────────────────────────────────────────────


class TestIsUrl:
    """Test the URL detection helper."""

    def test_https_url(self) -> None:
        assert _is_url("https://github.com/org/repo.git") is True

    def test_ssh_url(self) -> None:
        assert _is_url("ssh://git@host.com/repo.git") is True

    def test_scp_style(self) -> None:
        assert _is_url("git@github.com:org/repo.git") is True

    def test_local_path(self) -> None:
        assert _is_url("/some/local/path") is False

    def test_relative_path(self) -> None:
        assert _is_url("./relative/path") is False

    def test_file_url(self) -> None:
        assert _is_url("file:///some/path") is True


# ── Help / version (unchanged behaviour) ─────────────────────────────────


class TestHelpVersion:
    """Test CLI help and version output."""

    def test_help_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["--help"])
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "theo" in output
        assert "Usage" in output

    def test_version_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["--version"])
        output = capsys.readouterr().out
        assert exit_code == 0
        assert __version__ in output

    def test_version_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["version"])
        assert exit_code == 0
        assert __version__ in capsys.readouterr().out

    def test_no_args_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main([])
        assert exit_code == 0
        assert "Usage" in capsys.readouterr().out

    def test_unknown_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["foobar"])
        assert exit_code == 1
        assert "unknown command" in capsys.readouterr().err.lower()


# ── add command ──────────────────────────────────────────────────────────


class TestAddCommand:
    """Test the 'add' command."""

    def test_add_missing_arg(self, capsys: pytest.CaptureFixture[str], config: TheoConfig) -> None:
        exit_code = main(["add"], config=config)
        assert exit_code == 1
        assert "requires" in capsys.readouterr().err.lower()

    def test_add_url_success(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
        bare_repo: str,
    ) -> None:
        exit_code = main(["add", bare_repo], config=config)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "Added:" in output
        slug = slug_from_url(bare_repo)
        assert slug in output

        # Verify clone directory was created.
        clone_dir = config.base_dir / "repos" / slug
        assert clone_dir.exists()
        assert (clone_dir / ".git").exists()

        # Verify DB was initialised.
        db_path = Path(config.db_path_for_repo(slug))
        assert db_path.exists()

    def test_add_unknown_option(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
    ) -> None:
        exit_code = main(["add", "https://github.com/org/repo.git", "--unknown"], config=config)
        assert exit_code == 1
        assert "unknown option" in capsys.readouterr().err.lower()

    def test_add_duplicate_url(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
        bare_repo: str,
    ) -> None:
        main(["add", bare_repo], config=config)
        exit_code = main(["add", bare_repo], config=config)
        assert exit_code == 1
        assert "already registered" in capsys.readouterr().err.lower()

    def test_add_local_path(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
        bare_repo: str,
        tmp_path: Path,
    ) -> None:
        # Create a local git repo (not bare) to use as a local path.
        local_path = tmp_path / "local-repo"
        subprocess.run(
            ["git", "clone", bare_repo, str(local_path)],
            check=True,
            capture_output=True,
        )

        exit_code = main(["add", str(local_path)], config=config)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "Added:" in output

    def test_add_local_path_nonexistent(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
    ) -> None:
        exit_code = main(["add", "/tmp/nonexistent-path-abc123"], config=config)
        assert exit_code == 1
        assert "does not exist" in capsys.readouterr().err.lower()

    def test_add_clone_failure_rolls_back(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
    ) -> None:
        exit_code = main(
            ["add", "https://invalid-host.example.com/bad/repo.git"],
            config=config,
        )
        assert exit_code == 1
        assert "clone failed" in capsys.readouterr().err.lower()

        # Tracking entry should have been rolled back.
        manager = RepoManager(config)
        assert len(manager.list()) == 0


# ── remove command ───────────────────────────────────────────────────────


class TestRemoveCommand:
    """Test the 'remove' command."""

    def test_remove_missing_arg(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
    ) -> None:
        exit_code = main(["remove"], config=config)
        assert exit_code == 1
        assert "requires" in capsys.readouterr().err.lower()

    def test_remove_by_slug(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
        bare_repo: str,
    ) -> None:
        main(["add", bare_repo], config=config)
        slug = slug_from_url(bare_repo)

        exit_code = main(["remove", slug], config=config)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "Removed:" in output
        assert "tracking entry only" in output

        # Verify tracking entry is gone.
        manager = RepoManager(config)
        assert len(manager.list()) == 0

        # Clone and DB should still exist (no --delete-data).
        assert (config.base_dir / "repos" / slug).exists()

    def test_remove_nonexistent(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
    ) -> None:
        exit_code = main(["remove", "nonexistent"], config=config)
        assert exit_code == 1
        assert "not found" in capsys.readouterr().err.lower()

    def test_remove_unknown_option(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
        bare_repo: str,
    ) -> None:
        main(["add", bare_repo], config=config)
        slug = slug_from_url(bare_repo)
        exit_code = main(["remove", slug, "--force"], config=config)
        assert exit_code == 1
        assert "unknown option" in capsys.readouterr().err.lower()

    def test_remove_with_delete_data(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
        bare_repo: str,
    ) -> None:
        main(["add", bare_repo], config=config)
        slug = slug_from_url(bare_repo)

        clone_dir = config.base_dir / "repos" / slug
        db_dir = Path(config.db_path_for_repo(slug))
        assert clone_dir.exists()
        assert db_dir.exists()

        # Mock stdin.isatty() to return False (non-interactive).
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            exit_code = main(["remove", slug, "--delete-data"], config=config)

        output = capsys.readouterr().out
        assert exit_code == 0
        assert "data deleted" in output
        assert not clone_dir.exists()
        assert not db_dir.exists()

    def test_remove_with_delete_data_tty_confirm(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
        bare_repo: str,
    ) -> None:
        main(["add", bare_repo], config=config)
        slug = slug_from_url(bare_repo)

        with patch("sys.stdin") as mock_stdin, patch("builtins.input", return_value="y"):
            mock_stdin.isatty.return_value = True
            exit_code = main(["remove", slug, "--delete-data"], config=config)

        assert exit_code == 0
        assert "data deleted" in capsys.readouterr().out

    def test_remove_with_delete_data_tty_abort(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
        bare_repo: str,
    ) -> None:
        main(["add", bare_repo], config=config)
        slug = slug_from_url(bare_repo)

        clone_dir = config.base_dir / "repos" / slug
        with patch("sys.stdin") as mock_stdin, patch("builtins.input", return_value="n"):
            mock_stdin.isatty.return_value = True
            exit_code = main(["remove", slug, "--delete-data"], config=config)

        assert exit_code == 0
        assert "Aborted" in capsys.readouterr().out
        # Clone directory should still exist since the user declined.
        assert clone_dir.exists()
        # Tracking entry should also still exist.
        manager = RepoManager(config)
        assert len(manager.list()) == 1


# ── list command ─────────────────────────────────────────────────────────


class TestListCommand:
    """Test the 'list' command."""

    def test_list_empty(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
    ) -> None:
        exit_code = main(["list"], config=config)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "No repositories registered" in output

    def test_list_with_entries(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
        bare_repo: str,
    ) -> None:
        main(["add", bare_repo], config=config)
        slug = slug_from_url(bare_repo)

        exit_code = main(["list"], config=config)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert slug in output
        assert "URL:" in output
        assert "DB:" in output
        assert "Coverage:" in output
        assert "Last run:" in output

    def test_list_shows_never_for_unrun(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
        bare_repo: str,
    ) -> None:
        main(["add", bare_repo], config=config)
        exit_code = main(["list"], config=config)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "never" in output


# ── stats command ────────────────────────────────────────────────────────


class TestStatsCommand:
    """Test the 'stats' command."""

    def test_stats_empty(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
    ) -> None:
        exit_code = main(["stats"], config=config)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "No repositories registered" in output

    def test_stats_all_repos(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
        bare_repo: str,
    ) -> None:
        main(["add", bare_repo], config=config)
        slug = slug_from_url(bare_repo)

        exit_code = main(["stats"], config=config)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert slug in output
        assert "URL:" in output
        assert "Clone:" in output
        assert "DB:" in output
        assert "Last SHA:" in output
        assert "Last run:" in output
        assert "Coverage:" in output

    def test_stats_specific_repo(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
        bare_repo: str,
    ) -> None:
        main(["add", bare_repo], config=config)
        slug = slug_from_url(bare_repo)

        exit_code = main(["stats", slug], config=config)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert slug in output
        assert "Concepts:" in output
        assert "Files:" in output

    def test_stats_nonexistent_repo(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
    ) -> None:
        exit_code = main(["stats", "nonexistent"], config=config)
        assert exit_code == 1
        assert "not found" in capsys.readouterr().err.lower()

    def test_stats_missing_clone(
        self,
        capsys: pytest.CaptureFixture[str],
        config: TheoConfig,
    ) -> None:
        # Add a repo without cloning (directly via manager).
        manager = RepoManager(config)
        manager.add("https://github.com/org/some-repo.git")

        exit_code = main(["stats", "org-some-repo"], config=config)
        output = capsys.readouterr().out
        assert exit_code == 0
        assert "N/A" in output
        assert "missing" in output.lower()
