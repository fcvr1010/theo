"""Unit tests for ``theo ui`` -- graph visualization server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click
import pytest

from theo._db import init_schema, upsert_edge, upsert_node

pytest.importorskip("flask", reason="Flask not installed (theo[ui] extra)")


@pytest.fixture()  # type: ignore[misc]
def theo_project(tmp_path: Path) -> Path:
    """Create a minimal .theo/ project with a populated DB."""
    theo_dir = tmp_path / ".theo"
    theo_dir.mkdir()

    db_dir = theo_dir / "db"
    db_dir.mkdir()
    db_path = db_dir / "theo.db"
    init_schema(db_path)

    # Seed some data
    upsert_node(
        db_path,
        "Concept",
        {
            "id": "core",
            "name": "Core",
            "level": 0,
            "kind": "system",
            "description": "The core system",
            "notes": None,
            "git_revision": "abc123",
        },
    )
    upsert_node(
        db_path,
        "Concept",
        {
            "id": "parser",
            "name": "Parser",
            "level": 1,
            "kind": "component",
            "description": "Parses input files",
            "notes": None,
            "git_revision": "abc123",
        },
    )
    upsert_node(
        db_path,
        "SourceFile",
        {
            "path": "src/main.py",
            "name": "main.py",
            "description": "Entry point",
            "notes": None,
            "git_revision": "abc123",
        },
    )
    upsert_edge(db_path, "PartOf", "parser", "core", git_revision="abc123")
    upsert_edge(db_path, "BelongsTo", "src/main.py", "core", git_revision="abc123")

    config = {
        "project_slug": "test-project",
        "db_path": ".theo/db/theo.db",
        "last_indexed_commit": None,
        "created": "2026-01-01T00:00:00+00:00",
    }
    (theo_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")

    return tmp_path


def test_run_raises_when_no_config(tmp_path: Path) -> None:
    """run() should exit with an error when .theo/config.json is missing."""
    from theo.cli.ui import run

    with pytest.raises(click.exceptions.Exit):
        run(str(tmp_path), port=0, no_browser=True)


def test_run_raises_when_db_missing(tmp_path: Path) -> None:
    """run() should exit with an error when the database file doesn't exist."""
    from theo.cli.ui import run

    theo_dir = tmp_path / ".theo"
    theo_dir.mkdir()
    config = {
        "project_slug": "test",
        "db_path": ".theo/db/theo.db",
        "last_indexed_commit": None,
        "created": "2026-01-01T00:00:00+00:00",
    }
    (theo_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")

    with pytest.raises(click.exceptions.Exit):
        run(str(tmp_path), port=0, no_browser=True)


def test_build_graph_returns_valid_html(theo_project: Path) -> None:
    """_build_graph should return an HTML string with vis.js data."""
    from theo.cli.ui import _build_graph

    db_path = theo_project / ".theo" / "db" / "theo.db"
    html = _build_graph(db_path, "test-project")

    assert "<!DOCTYPE html>" in html
    assert "Theo Knowledge Graph" in html
    assert "test-project" in html
    assert "vis.Network" in html
    # Check that our seeded nodes appear
    assert "Core" in html
    assert "Parser" in html
    assert "main.py" in html


def test_build_graph_contains_correct_legend(theo_project: Path) -> None:
    """Legend should say 'Theo Graph' and have 'Source file' (not language-specific)."""
    from theo.cli.ui import _build_graph

    db_path = theo_project / ".theo" / "db" / "theo.db"
    html = _build_graph(db_path, "test-project")

    assert "Theo Graph" in html
    assert "Source file" in html
    # Should NOT have language-specific legend items
    assert "Python file" not in html
    assert "Markdown file" not in html


def test_build_graph_file_nodes_use_unified_color(theo_project: Path) -> None:
    """All file nodes should use the unified color #C7CEEA, not language-based colors."""
    from theo.cli.ui import _build_graph

    db_path = theo_project / ".theo" / "db" / "theo.db"
    html = _build_graph(db_path, "test-project")

    # The nodesData JSON is embedded in the HTML; extract it and check file node colors
    # Find the JSON between "const nodesData = " and the next ";"
    marker = "const nodesData = "
    start = html.index(marker) + len(marker)
    # Find the matching closing bracket
    depth = 0
    end = start
    for i, ch in enumerate(html[start:], start=start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    nodes_json = html[start:end]
    nodes: list[dict[str, Any]] = json.loads(nodes_json)

    file_nodes = [n for n in nodes if n["id"].startswith("f:")]
    assert len(file_nodes) > 0
    for fn in file_nodes:
        assert fn["color"]["background"] == "#C7CEEA"
        assert fn["color"]["border"] == "#A8B2D8"
        assert fn["size"] == 10
        assert fn["shape"] == "square"


def test_flask_index_returns_html(theo_project: Path) -> None:
    """The Flask app's / route should return 200 with HTML content."""
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"
    flask_app = _create_app(db_path, "test-project")

    with flask_app.test_client() as client:
        response = client.get("/")
        assert response.status_code == 200
        assert b"<!DOCTYPE html>" in response.data
        assert b"Theo Knowledge Graph" in response.data


def test_flask_index_no_db(tmp_path: Path) -> None:
    """The / route should return the 'no data' page when DB doesn't exist."""
    from theo.cli.ui import _create_app

    db_path = tmp_path / "nonexistent.db"
    flask_app = _create_app(db_path, "test-project")

    with flask_app.test_client() as client:
        response = client.get("/")
        assert response.status_code == 200
        assert b"No graph data yet" in response.data


def test_flask_health(theo_project: Path) -> None:
    """The /health endpoint should return status ok."""
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"
    flask_app = _create_app(db_path, "test-project")

    with flask_app.test_client() as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "ok"


def test_search_empty_query(theo_project: Path) -> None:
    """Search with empty query should return empty results."""
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"
    flask_app = _create_app(db_path, "test-project")

    with flask_app.test_client() as client:
        response = client.get("/search?q=")
        assert response.status_code == 200
        data = response.get_json()
        assert data["results"] == []


def test_search_matching_query(theo_project: Path) -> None:
    """Search for 'core' should return the Core concept node."""
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"
    flask_app = _create_app(db_path, "test-project")

    with flask_app.test_client() as client:
        response = client.get("/search?q=core")
        assert response.status_code == 200
        data = response.get_json()
        results = data["results"]
        assert len(results) > 0
        node_ids = [r["nodeId"] for r in results]
        assert "c:core" in node_ids


def test_search_file_node(theo_project: Path) -> None:
    """Search for 'main' should return the main.py source file node."""
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"
    flask_app = _create_app(db_path, "test-project")

    with flask_app.test_client() as client:
        response = client.get("/search?q=main")
        assert response.status_code == 200
        data = response.get_json()
        results = data["results"]
        assert len(results) > 0
        node_ids = [r["nodeId"] for r in results]
        assert "f:src/main.py" in node_ids


def test_search_description_match_scores_lower(theo_project: Path) -> None:
    """A description-only match should score 0.6, lower than a name match (1.0)."""
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"
    flask_app = _create_app(db_path, "test-project")

    with flask_app.test_client() as client:
        # "entry" appears only in main.py's description ("Entry point")
        response = client.get("/search?q=entry")
        assert response.status_code == 200
        data = response.get_json()
        results = data["results"]
        assert len(results) > 0
        for r in results:
            if r["nodeId"] == "f:src/main.py":
                assert r["score"] == 0.6
                break
        else:
            pytest.fail("Expected main.py in results for 'entry' query")


def test_search_no_match(theo_project: Path) -> None:
    """Search for a nonexistent term should return empty results."""
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"
    flask_app = _create_app(db_path, "test-project")

    with flask_app.test_client() as client:
        response = client.get("/search?q=zzzznonexistent")
        assert response.status_code == 200
        data = response.get_json()
        assert data["results"] == []


def test_search_name_match_ranks_higher(theo_project: Path) -> None:
    """Name matches (1.0) should rank above description-only matches (0.6)."""
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"
    flask_app = _create_app(db_path, "test-project")

    with flask_app.test_client() as client:
        # "pars" matches both Parser (name) and "Parses input files" (description of Parser)
        response = client.get("/search?q=pars")
        assert response.status_code == 200
        data = response.get_json()
        results = data["results"]
        assert len(results) > 0
        # The parser concept should appear with score 1.0 (name match)
        parser_results = [r for r in results if r["nodeId"] == "c:parser"]
        assert len(parser_results) == 1
        assert parser_results[0]["score"] == 1.0
