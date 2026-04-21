"""Integration tests for ``theo reindex``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import click
import pytest

from theo._db import run_query, upsert_node
from theo.cli.reindex import run as reindex_run

pytestmark = pytest.mark.integration

pytest.importorskip("fastembed", reason="fastembed is not installed")


class TestReindexCli:
    def test_populates_embeddings(self, tmp_theo_project: Path) -> None:
        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        upsert_node(
            db_path,
            "Concept",
            {"id": "x", "name": "X", "description": "a thing", "git_revision": "r"},
        )

        reindex_run(str(tmp_theo_project))

        rows = run_query(
            db_path, "MATCH (n:Concept {id: 'x'}) RETURN n.embedding IS NULL AS is_null"
        )
        assert rows[0]["is_null"] is False

    def test_exits_when_no_config(self, tmp_path: Path) -> None:
        with pytest.raises(click.exceptions.Exit):
            reindex_run(str(tmp_path))

    def test_subprocess_invocation(self, tmp_theo_project: Path) -> None:
        theo_bin: str | None = shutil.which("theo")
        if theo_bin is None:
            pytest.skip("theo console script not on PATH")

        db_path = tmp_theo_project / ".theo" / "db" / "theo.db"
        upsert_node(
            db_path,
            "Concept",
            {"id": "y", "name": "Y", "description": "another", "git_revision": "r"},
        )

        # mypy needs help narrowing past the skip above
        assert theo_bin is not None
        result = subprocess.run(
            [theo_bin, "reindex", str(tmp_theo_project)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "Reindexing" in result.stdout
        assert "Concept" in result.stdout
