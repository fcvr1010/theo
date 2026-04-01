"""Repository tracking and git operations for Theo.

    RepoManager(config) -- manages the repos.json tracking file and git clone/pull.

Provides:
- Tracking: add, remove, list, get, update repositories in a JSON manifest.
- Git ops: clone, pull, get_current_sha for managed repositories.

Slug generation is deterministic from URL: strip scheme/host, replace ``/`` and
``.`` with ``-``, lowercase, strip trailing ``-git``.

The tracking file uses atomic writes (write .tmp then rename) to avoid
corruption on crash.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import git as gitpython

from theo import get_logger
from theo.config import TheoConfig

_log = get_logger("repo_manager")


@dataclass
class RepoEntry:
    """A single tracked repository."""

    url: str
    slug: str
    clone_path: str
    db_path: str
    frequency_minutes: int
    last_checked_revision: str | None
    last_run_at: str | None
    enabled_lenses: list[str]
    added_at: str


@dataclass
class PullResult:
    """Result of a git pull operation."""

    sha_before: str
    sha_after: str
    changed_files: list[str]


def slug_from_url(url: str) -> str:
    """Derive a deterministic slug from a git URL.

    Examples::

        https://github.com/org/my-repo.git  -> org-my-repo
        git@github.com:org/repo.git         -> org-repo
        https://gitlab.com/g/sub/repo       -> g-sub-repo
        ssh://git@host:22/org/repo.git      -> org-repo

    Rules: strip scheme and host, replace ``/`` and ``.`` with ``-``,
    lowercase, strip trailing ``-git``, collapse repeated ``-``, strip
    leading/trailing ``-``.
    """
    raw = url.strip()

    # Handle SCP-style SSH URLs: git@host:path
    scp_match = re.match(r"^[\w.-]+@[\w.-]+:(.+)$", raw)
    if scp_match:
        path_part = scp_match.group(1)
    else:
        parsed = urlparse(raw)
        path_part = parsed.path
        # ssh://git@host:port/path -- urlparse puts path after port correctly

    # Strip leading slash
    path_part = path_part.lstrip("/")

    # Replace / and . with -
    slug = path_part.replace("/", "-").replace(".", "-")

    # Lowercase
    slug = slug.lower()

    # Strip trailing -git (from .git suffix)
    if slug.endswith("-git"):
        slug = slug[:-4]

    # Collapse repeated dashes and strip leading/trailing dashes
    slug = re.sub(r"-+", "-", slug).strip("-")

    if not slug:
        raise ValueError(f"Cannot derive slug from URL: {url!r}")

    return slug


class RepoManagerError(Exception):
    """Base exception for RepoManager operations."""


class RepoNotFoundError(RepoManagerError):
    """Raised when a repository is not found in the tracking file."""


class GitOperationError(RepoManagerError):
    """Raised when a git operation fails."""


class RepoManager:
    """Manages tracked repositories and their git operations.

    Args:
        config: Theo configuration. Defaults to ``TheoConfig()`` if not provided.
    """

    def __init__(self, config: TheoConfig | None = None) -> None:
        self._config = config or TheoConfig()
        self._tracking_path = self._config.base_dir / "repos.json"

    # ── Tracking file I/O ─────────────────────────────────────────────────

    def _load(self) -> list[dict[str, Any]]:
        """Load the tracking file. Returns an empty list if the file does not exist."""
        if not self._tracking_path.exists():
            return []
        try:
            data = json.loads(self._tracking_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                _log.warning("repos.json is not a list, resetting to empty")
                return []
            return data
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("Failed to read repos.json, resetting to empty: %s", exc)
            return []

    def _save(self, entries: list[dict[str, Any]]) -> None:
        """Atomically save the tracking file (write .tmp then rename)."""
        self._tracking_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._tracking_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.rename(str(tmp_path), str(self._tracking_path))
        except Exception:
            # Clean up the temp file on failure.
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    # ── CRUD operations ───────────────────────────────────────────────────

    def add(
        self,
        url: str,
        frequency_minutes: int | None = None,
        enabled_lenses: list[str] | None = None,
    ) -> RepoEntry:
        """Register a new repository for tracking.

        Args:
            url: Git clone URL (HTTPS or SSH).
            frequency_minutes: Polling interval. Defaults to config default.
            enabled_lenses: List of lens names to enable. Defaults to empty.

        Returns:
            The newly created ``RepoEntry``.

        Raises:
            ValueError: If a repository with the same URL or slug is already registered.
        """
        slug = slug_from_url(url)
        freq = (
            frequency_minutes
            if frequency_minutes is not None
            else self._config.default_frequency_minutes
        )

        entries = self._load()

        # Check for duplicates by URL or slug.
        for entry in entries:
            if entry.get("url") == url:
                raise ValueError(f"Repository already registered: {url}")
            if entry.get("slug") == slug:
                existing_url = entry.get("url")
                raise ValueError(
                    f"Repository with slug '{slug}' already registered (url: {existing_url})"
                )

        clone_path = str(self._config.base_dir / "repos" / slug)
        db_path = self._config.db_path_for_repo(slug)

        repo_entry = RepoEntry(
            url=url,
            slug=slug,
            clone_path=clone_path,
            db_path=db_path,
            frequency_minutes=freq,
            last_checked_revision=None,
            last_run_at=None,
            enabled_lenses=enabled_lenses or [],
            added_at=datetime.now(UTC).isoformat(),
        )

        entries.append(asdict(repo_entry))
        self._save(entries)

        _log.info("Added repository: %s (slug=%s)", url, slug)
        return repo_entry

    def remove(self, url_or_slug: str) -> RepoEntry:
        """Remove a repository from tracking.

        Args:
            url_or_slug: The repository URL or slug.

        Returns:
            The removed ``RepoEntry``.

        Raises:
            RepoNotFoundError: If no matching repository is found.
        """
        entries = self._load()
        removed: dict[str, Any] | None = None
        remaining: list[dict[str, Any]] = []

        for entry in entries:
            if entry.get("url") == url_or_slug or entry.get("slug") == url_or_slug:
                removed = entry
            else:
                remaining.append(entry)

        if removed is None:
            raise RepoNotFoundError(f"Repository not found: {url_or_slug}")

        self._save(remaining)
        _log.info("Removed repository: %s", url_or_slug)
        return RepoEntry(**removed)

    def list(self) -> list[RepoEntry]:
        """Return all tracked repositories."""
        entries = self._load()
        return [RepoEntry(**e) for e in entries]

    def get(self, url_or_slug: str) -> RepoEntry:
        """Look up a single repository by URL or slug.

        Raises:
            RepoNotFoundError: If no matching repository is found.
        """
        entries = self._load()
        for entry in entries:
            if entry.get("url") == url_or_slug or entry.get("slug") == url_or_slug:
                return RepoEntry(**entry)
        raise RepoNotFoundError(f"Repository not found: {url_or_slug}")

    def update(self, slug: str, **fields: Any) -> RepoEntry:
        """Update fields on a tracked repository.

        Args:
            slug: The repository slug.
            **fields: Fields to update (e.g. ``frequency_minutes=60``).

        Returns:
            The updated ``RepoEntry``.

        Raises:
            RepoNotFoundError: If no matching repository is found.
            ValueError: If an unknown field is provided.
        """
        valid_fields = {f.name for f in RepoEntry.__dataclass_fields__.values()}
        immutable_fields = {"url", "slug", "clone_path", "db_path", "added_at"}
        for key in fields:
            if key not in valid_fields:
                raise ValueError(f"Unknown field: {key!r}")
            if key in immutable_fields:
                raise ValueError(f"Cannot update immutable field: {key!r}")

        entries = self._load()
        found = False
        for entry in entries:
            if entry.get("slug") == slug:
                entry.update(fields)
                found = True
                break

        if not found:
            raise RepoNotFoundError(f"Repository not found: {slug}")

        self._save(entries)
        _log.info("Updated repository %s: %s", slug, list(fields.keys()))
        return self.get(slug)

    # ── Git operations ────────────────────────────────────────────────────

    def clone(self, slug: str) -> Path:
        """Clone a tracked repository.

        If the clone directory already exists and contains a valid git repo,
        logs a warning and returns the existing path without re-cloning.

        Args:
            slug: The repository slug.

        Returns:
            Path to the cloned repository.

        Raises:
            RepoNotFoundError: If the slug is not tracked.
            GitOperationError: If the git clone fails.
        """
        entry = self.get(slug)
        clone_dir = Path(entry.clone_path)

        # Already cloned?
        if clone_dir.exists():
            try:
                gitpython.Repo(str(clone_dir))
                _log.warning(
                    "Repository %s already cloned at %s, skipping clone",
                    slug,
                    clone_dir,
                )
                return clone_dir
            except gitpython.InvalidGitRepositoryError as exc:
                raise GitOperationError(
                    f"Directory {clone_dir} exists but is not a valid git repository"
                ) from exc

        clone_dir.parent.mkdir(parents=True, exist_ok=True)

        try:
            _log.info("Cloning %s into %s", entry.url, clone_dir)
            gitpython.Repo.clone_from(entry.url, str(clone_dir))
        except gitpython.GitCommandError as exc:
            raise GitOperationError(f"Failed to clone {entry.url}: {exc}") from exc

        return clone_dir

    def pull(self, slug: str) -> PullResult:
        """Pull latest changes for a tracked repository.

        Args:
            slug: The repository slug.

        Returns:
            ``PullResult`` with SHA before, SHA after, and list of changed files.

        Raises:
            RepoNotFoundError: If the slug is not tracked.
            GitOperationError: If the git pull fails or the repo is not cloned.
        """
        entry = self.get(slug)
        clone_dir = Path(entry.clone_path)

        if not clone_dir.exists():
            raise GitOperationError(
                f"Repository {slug} is not cloned yet (expected at {clone_dir})"
            )

        try:
            repo = gitpython.Repo(str(clone_dir))
        except gitpython.InvalidGitRepositoryError as exc:
            raise GitOperationError(
                f"Directory {clone_dir} is not a valid git repository"
            ) from exc

        sha_before = repo.head.commit.hexsha

        try:
            _log.info("Pulling %s", slug)
            repo.remotes.origin.pull()
        except gitpython.GitCommandError as exc:
            raise GitOperationError(f"Failed to pull {slug}: {exc}") from exc

        sha_after = repo.head.commit.hexsha

        # Compute changed files.
        changed_files: list[str] = []
        if sha_before != sha_after:
            try:
                diff_output: str = repo.git.diff("--name-only", sha_before, sha_after)
                if diff_output.strip():
                    changed_files = diff_output.strip().split("\n")
            except gitpython.GitCommandError as exc:
                _log.warning("Failed to compute changed files for %s: %s", slug, exc)

        return PullResult(
            sha_before=sha_before,
            sha_after=sha_after,
            changed_files=changed_files,
        )

    def get_current_sha(self, slug: str) -> str:
        """Return the HEAD commit SHA for a tracked repository.

        Args:
            slug: The repository slug.

        Returns:
            The full 40-character hex SHA of HEAD.

        Raises:
            RepoNotFoundError: If the slug is not tracked.
            GitOperationError: If the repo is not cloned or is invalid.
        """
        entry = self.get(slug)
        clone_dir = Path(entry.clone_path)

        if not clone_dir.exists():
            raise GitOperationError(
                f"Repository {slug} is not cloned yet (expected at {clone_dir})"
            )

        try:
            repo = gitpython.Repo(str(clone_dir))
        except gitpython.InvalidGitRepositoryError as exc:
            raise GitOperationError(
                f"Directory {clone_dir} is not a valid git repository"
            ) from exc

        return str(repo.head.commit.hexsha)
