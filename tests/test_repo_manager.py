"""Tests for theo.repo_manager."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from theo.config import TheoConfig
from theo.repo_manager import (
    GitOperationError,
    PullResult,
    RepoEntry,
    RepoManager,
    RepoManagerError,
    RepoNotFoundError,
    slug_from_url,
)

# ── slug_from_url ─────────────────────────────────────────────────────────


class TestSlugFromUrl:
    """Test deterministic slug generation from git URLs."""

    def test_https_with_git_suffix(self) -> None:
        assert slug_from_url("https://github.com/org/my-repo.git") == "org-my-repo"

    def test_https_without_git_suffix(self) -> None:
        assert slug_from_url("https://github.com/org/my-repo") == "org-my-repo"

    def test_ssh_scp_style(self) -> None:
        assert slug_from_url("git@github.com:org/repo.git") == "org-repo"

    def test_ssh_scp_style_no_git(self) -> None:
        assert slug_from_url("git@github.com:org/repo") == "org-repo"

    def test_ssh_url_scheme(self) -> None:
        assert slug_from_url("ssh://git@host.com/org/repo.git") == "org-repo"

    def test_ssh_url_with_port(self) -> None:
        assert slug_from_url("ssh://git@host.com:22/org/repo.git") == "org-repo"

    def test_subgroups(self) -> None:
        assert slug_from_url("https://gitlab.com/g/sub/repo") == "g-sub-repo"

    def test_dots_in_name(self) -> None:
        assert slug_from_url("https://github.com/org/my.dotted.repo.git") == "org-my-dotted-repo"

    def test_uppercase_normalized(self) -> None:
        assert slug_from_url("https://github.com/Org/My-Repo.git") == "org-my-repo"

    def test_trailing_whitespace_stripped(self) -> None:
        assert slug_from_url("  https://github.com/org/repo.git  ") == "org-repo"

    def test_empty_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot derive slug"):
            slug_from_url("")

    def test_bare_host_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot derive slug"):
            slug_from_url("https://github.com/")


# ── Fixtures ──────────────────────────────────────────────────────────────


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

    This serves as a local "remote" for clone/pull tests without network calls.
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


def _add_commit_to_bare(bare_path: str, tmp_path: Path, filename: str, content: str) -> str:
    """Add a new commit to the bare repo and return the new SHA."""
    work_path = tmp_path / "push-work"
    if work_path.exists():
        shutil.rmtree(work_path)
    subprocess.run(
        ["git", "clone", bare_path, str(work_path)],
        check=True,
        capture_output=True,
    )
    (work_path / filename).write_text(content)
    subprocess.run(
        ["git", "-C", str(work_path), "add", filename],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(work_path), "commit", "-m", f"add {filename}"],
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
    result = subprocess.run(
        ["git", "-C", str(work_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


# ── Tracking file I/O ─────────────────────────────────────────────────────


class TestTrackingIO:
    """Test _load and _save mechanics."""

    def test_load_empty_when_no_file(self, manager: RepoManager) -> None:
        entries = manager._load()
        assert entries == []

    def test_save_and_load_roundtrip(self, manager: RepoManager) -> None:
        data = [{"url": "https://example.com/repo.git", "slug": "repo"}]
        manager._save(data)
        loaded = manager._load()
        assert loaded == data

    def test_atomic_write_no_tmp_leftover(self, manager: RepoManager) -> None:
        data = [{"url": "https://example.com/repo.git"}]
        manager._save(data)
        tmp_path = manager._tracking_path.with_suffix(".tmp")
        assert not tmp_path.exists()
        assert manager._tracking_path.exists()

    def test_load_handles_corrupt_json(self, manager: RepoManager) -> None:
        manager._tracking_path.parent.mkdir(parents=True, exist_ok=True)
        manager._tracking_path.write_text("{invalid json", encoding="utf-8")
        entries = manager._load()
        assert entries == []

    def test_load_handles_non_list_json(self, manager: RepoManager) -> None:
        manager._tracking_path.parent.mkdir(parents=True, exist_ok=True)
        manager._tracking_path.write_text('{"not": "a list"}', encoding="utf-8")
        entries = manager._load()
        assert entries == []

    def test_save_creates_parent_dir(self, config: TheoConfig) -> None:
        # Use a nested path that does not exist yet.
        mgr = RepoManager(config)
        mgr._tracking_path = config.base_dir / "nested" / "repos.json"
        mgr._save([{"test": True}])
        assert mgr._tracking_path.exists()


# ── CRUD operations ───────────────────────────────────────────────────────


class TestAdd:
    """Test adding repositories."""

    def test_add_basic(self, manager: RepoManager, config: TheoConfig) -> None:
        entry = manager.add("https://github.com/org/my-repo.git", frequency_minutes=60)
        assert isinstance(entry, RepoEntry)
        assert entry.url == "https://github.com/org/my-repo.git"
        assert entry.slug == "org-my-repo"
        assert entry.frequency_minutes == 60
        assert entry.clone_path == str(config.base_dir / "repos" / "org-my-repo")
        assert entry.db_path == str(config.base_dir / "db" / "org-my-repo")
        assert entry.last_checked_revision is None
        assert entry.last_run_at is None
        assert entry.enabled_lenses == []
        assert entry.added_at  # non-empty ISO string

    def test_add_uses_default_frequency(self, manager: RepoManager) -> None:
        entry = manager.add("https://github.com/org/repo")
        assert entry.frequency_minutes == 30  # TheoConfig default

    def test_add_with_lenses(self, manager: RepoManager) -> None:
        entry = manager.add("https://github.com/org/repo", enabled_lenses=["structure", "docs"])
        assert entry.enabled_lenses == ["structure", "docs"]

    def test_add_persists_to_disk(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        # Re-load from disk to verify persistence.
        entries = manager._load()
        assert len(entries) == 1
        assert entries[0]["slug"] == "org-repo"

    def test_add_duplicate_url_raises(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        with pytest.raises(ValueError, match="already registered"):
            manager.add("https://github.com/org/repo.git")

    def test_add_duplicate_slug_raises(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        # Same slug, different URL (unlikely but possible).
        with pytest.raises(ValueError, match="already registered"):
            manager.add("git@github.com:org/repo.git")

    def test_add_multiple(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo-a.git")
        manager.add("https://github.com/org/repo-b.git")
        assert len(manager.list()) == 2


class TestRemove:
    """Test removing repositories."""

    def test_remove_by_slug(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        removed = manager.remove("org-repo")
        assert removed.slug == "org-repo"
        assert len(manager.list()) == 0

    def test_remove_by_url(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        removed = manager.remove("https://github.com/org/repo.git")
        assert removed.url == "https://github.com/org/repo.git"
        assert len(manager.list()) == 0

    def test_remove_nonexistent_raises(self, manager: RepoManager) -> None:
        with pytest.raises(RepoNotFoundError, match="not found"):
            manager.remove("nonexistent")

    def test_remove_preserves_others(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/a.git")
        manager.add("https://github.com/org/b.git")
        manager.remove("org-a")
        remaining = manager.list()
        assert len(remaining) == 1
        assert remaining[0].slug == "org-b"


class TestList:
    """Test listing repositories."""

    def test_list_empty(self, manager: RepoManager) -> None:
        assert manager.list() == []

    def test_list_returns_entries(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/a.git")
        manager.add("https://github.com/org/b.git")
        entries = manager.list()
        assert len(entries) == 2
        assert all(isinstance(e, RepoEntry) for e in entries)


class TestGet:
    """Test getting a single repository."""

    def test_get_by_slug(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        entry = manager.get("org-repo")
        assert entry.slug == "org-repo"

    def test_get_by_url(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        entry = manager.get("https://github.com/org/repo.git")
        assert entry.url == "https://github.com/org/repo.git"

    def test_get_nonexistent_raises(self, manager: RepoManager) -> None:
        with pytest.raises(RepoNotFoundError, match="not found"):
            manager.get("nonexistent")


class TestUpdate:
    """Test updating repository fields."""

    def test_update_frequency(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        updated = manager.update("org-repo", frequency_minutes=120)
        assert updated.frequency_minutes == 120
        # Verify persistence.
        reloaded = manager.get("org-repo")
        assert reloaded.frequency_minutes == 120

    def test_update_last_checked_revision(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        updated = manager.update("org-repo", last_checked_revision="abc123")
        assert updated.last_checked_revision == "abc123"

    def test_update_enabled_lenses(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        updated = manager.update("org-repo", enabled_lenses=["structure"])
        assert updated.enabled_lenses == ["structure"]

    def test_update_nonexistent_raises(self, manager: RepoManager) -> None:
        with pytest.raises(RepoNotFoundError, match="not found"):
            manager.update("nonexistent", frequency_minutes=60)

    def test_update_unknown_field_raises(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        with pytest.raises(ValueError, match="Unknown field"):
            manager.update("org-repo", nonexistent_field="value")

    def test_update_immutable_field_raises(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        with pytest.raises(ValueError, match="immutable"):
            manager.update("org-repo", url="https://other.com/repo.git")

    def test_update_immutable_clone_path_raises(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        with pytest.raises(ValueError, match="immutable"):
            manager.update("org-repo", clone_path="/tmp/somewhere")

    def test_update_immutable_added_at_raises(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        with pytest.raises(ValueError, match="immutable"):
            manager.update("org-repo", added_at="2020-01-01T00:00:00")


# ── Git operations ────────────────────────────────────────────────────────


class TestClone:
    """Test cloning repositories."""

    def test_clone_success(self, manager: RepoManager, bare_repo: str, config: TheoConfig) -> None:
        manager.add(bare_repo, frequency_minutes=10)
        slug = slug_from_url(bare_repo)
        clone_dir = manager.clone(slug)
        assert clone_dir.exists()
        assert (clone_dir / ".git").exists()
        assert (clone_dir / "README.md").exists()

    def test_clone_already_cloned_no_error(self, manager: RepoManager, bare_repo: str) -> None:
        slug = slug_from_url(bare_repo)
        manager.add(bare_repo)
        manager.clone(slug)
        # Second clone should log a warning but not raise.
        clone_dir = manager.clone(slug)
        assert clone_dir.exists()

    def test_clone_nonexistent_slug_raises(self, manager: RepoManager) -> None:
        with pytest.raises(RepoNotFoundError):
            manager.clone("nonexistent")

    def test_clone_invalid_url_raises(self, manager: RepoManager, config: TheoConfig) -> None:
        url = "https://invalid-host.example.com/bad/repo.git"
        manager.add(url)
        slug = slug_from_url(url)
        with pytest.raises(GitOperationError, match="Failed to clone"):
            manager.clone(slug)

    def test_clone_dir_exists_but_not_git_raises(
        self, manager: RepoManager, bare_repo: str, config: TheoConfig
    ) -> None:
        slug = slug_from_url(bare_repo)
        manager.add(bare_repo)
        # Create the directory without git init.
        clone_path = Path(config.base_dir / "repos" / slug)
        clone_path.mkdir(parents=True)
        (clone_path / "some-file.txt").write_text("not a git repo")
        with pytest.raises(GitOperationError, match="not a valid git repository"):
            manager.clone(slug)


class TestPull:
    """Test pulling repositories."""

    def test_pull_no_changes(self, manager: RepoManager, bare_repo: str) -> None:
        slug = slug_from_url(bare_repo)
        manager.add(bare_repo)
        manager.clone(slug)
        result = manager.pull(slug)
        assert isinstance(result, PullResult)
        assert result.sha_before == result.sha_after
        assert result.changed_files == []

    def test_pull_with_changes(self, manager: RepoManager, bare_repo: str, tmp_path: Path) -> None:
        slug = slug_from_url(bare_repo)
        manager.add(bare_repo)
        manager.clone(slug)
        sha_before = manager.get_current_sha(slug)

        # Push a new commit to the bare repo.
        new_sha = _add_commit_to_bare(bare_repo, tmp_path, "new_file.txt", "hello")

        result = manager.pull(slug)
        assert result.sha_before == sha_before
        assert result.sha_after == new_sha
        assert "new_file.txt" in result.changed_files

    def test_pull_not_cloned_raises(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        with pytest.raises(GitOperationError, match="not cloned yet"):
            manager.pull("org-repo")

    def test_pull_nonexistent_slug_raises(self, manager: RepoManager) -> None:
        with pytest.raises(RepoNotFoundError):
            manager.pull("nonexistent")


class TestGetCurrentSha:
    """Test getting current HEAD SHA."""

    def test_get_sha_after_clone(self, manager: RepoManager, bare_repo: str) -> None:
        slug = slug_from_url(bare_repo)
        manager.add(bare_repo)
        manager.clone(slug)
        sha = manager.get_current_sha(slug)
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    def test_get_sha_not_cloned_raises(self, manager: RepoManager) -> None:
        manager.add("https://github.com/org/repo.git")
        with pytest.raises(GitOperationError, match="not cloned yet"):
            manager.get_current_sha("org-repo")

    def test_get_sha_nonexistent_slug_raises(self, manager: RepoManager) -> None:
        with pytest.raises(RepoNotFoundError):
            manager.get_current_sha("nonexistent")


# ── Exception hierarchy ───────────────────────────────────────────────────


class TestExceptions:
    """Verify the exception hierarchy."""

    def test_repo_not_found_is_repo_manager_error(self) -> None:
        assert issubclass(RepoNotFoundError, RepoManagerError)

    def test_git_operation_error_is_repo_manager_error(self) -> None:
        assert issubclass(GitOperationError, RepoManagerError)

    def test_repo_manager_error_is_exception(self) -> None:
        assert issubclass(RepoManagerError, Exception)


# ── RepoEntry dataclass ──────────────────────────────────────────────────


class TestRepoEntry:
    """Test the RepoEntry dataclass."""

    def test_round_trip_via_json(self) -> None:
        entry = RepoEntry(
            url="https://github.com/org/repo.git",
            slug="org-repo",
            clone_path="/tmp/repos/org-repo",
            db_path="/tmp/db/org-repo",
            frequency_minutes=30,
            last_checked_revision=None,
            last_run_at=None,
            enabled_lenses=["structure"],
            added_at="2026-01-01T00:00:00+00:00",
        )
        from dataclasses import asdict

        data = asdict(entry)
        restored = RepoEntry.from_dict(data)
        assert restored == entry

    def test_from_dict_ignores_extra_keys(self) -> None:
        """from_dict should silently drop keys that are not RepoEntry fields."""
        data = {
            "url": "https://github.com/org/repo.git",
            "slug": "org-repo",
            "clone_path": "/tmp/repos/org-repo",
            "db_path": "/tmp/db/org-repo",
            "frequency_minutes": 30,
            "last_checked_revision": None,
            "last_run_at": None,
            "enabled_lenses": [],
            "added_at": "2026-01-01T00:00:00+00:00",
            # Extra keys from a hypothetical future version.
            "new_future_field": "some-value",
            "another_unknown": 42,
        }
        entry = RepoEntry.from_dict(data)
        assert entry.slug == "org-repo"
        assert not hasattr(entry, "new_future_field")
        assert not hasattr(entry, "another_unknown")
