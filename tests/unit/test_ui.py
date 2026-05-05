"""Unit tests for ``theo ui`` -- graph visualization server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import click
import pytest

from theo._db import init_schema, upsert_edge, upsert_node

pytest.importorskip("flask", reason="Flask not installed (theo[ui] extra)")


@pytest.fixture()
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
            "description": "Parses input files",
            "notes": None,
            "git_revision": "abc123",
        },
    )
    upsert_node(
        db_path,
        "Concept",
        {
            "id": "deep",
            "name": "Deep",
            "level": 4,
            "description": "Something nested several layers down",
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


def test_level_tier_mapping() -> None:
    """_level_tier collapses any level >= 3 into the L3+ bucket."""
    from theo.cli.ui import _level_tier

    assert _level_tier(0) == "L0"
    assert _level_tier(1) == "L1"
    assert _level_tier(2) == "L2"
    assert _level_tier(3) == "L3+"
    assert _level_tier(7) == "L3+"
    assert _level_tier(None) == "L3+"


def _extract_nodes(html: str) -> list[dict[str, Any]]:
    """Pull the embedded vis.js nodesData JSON out of the rendered HTML."""
    marker = "const nodesData = "
    start = html.index(marker) + len(marker)
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
    return cast(list[dict[str, Any]], json.loads(html[start:end]))


def test_build_graph_concept_nodes_use_level_tier(theo_project: Path) -> None:
    """Concept nodes should be styled by their level tier (L0/L1/L2/L3+)."""
    from theo.cli.ui import _build_graph

    db_path = theo_project / ".theo" / "db" / "theo.db"
    html = _build_graph(db_path, "test-project")

    nodes = {n["id"]: n for n in _extract_nodes(html) if n["id"].startswith("c:")}

    # L0 (Core): largest red node
    assert nodes["c:core"]["_tier"] == "L0"
    assert nodes["c:core"]["color"]["background"] == "#FF6B6B"
    assert nodes["c:core"]["size"] == 45

    # L1 (Parser): orange
    assert nodes["c:parser"]["_tier"] == "L1"
    assert nodes["c:parser"]["color"]["background"] == "#FFA94D"
    assert nodes["c:parser"]["size"] == 32

    # L4 → collapsed into L3+
    assert nodes["c:deep"]["_tier"] == "L3+"
    assert nodes["c:deep"]["color"]["background"] == "#A0A8B0"
    assert nodes["c:deep"]["size"] == 18

    # No legacy `_kind` or `kind` attribute leaks into the rendered nodes.
    for n in nodes.values():
        assert "_kind" not in n
        assert "kind" not in n


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
    """Empty queries short-circuit to an empty result set without embedding."""
    from theo.cli import ui as ui_module
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"
    flask_app = _create_app(db_path, "test-project")

    with flask_app.test_client() as client:
        response = client.get("/search?q=")
        assert response.status_code == 200
        assert response.get_json() == {"results": []}

    # Whitespace-only queries behave the same way — and must not invoke the
    # embedding model (whose cold-start is ~2 s).
    assert hasattr(ui_module, "embed_query")
    with flask_app.test_client() as client:
        response = client.get("/search?q=%20%20%20")
        assert response.status_code == 200
        assert response.get_json() == {"results": []}


def test_search_maps_node_matches_to_vis_ids(
    theo_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Node matches from semantic_search map onto the c:/f: vis.js prefixes."""
    from theo.cli import ui as ui_module
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"

    monkeypatch.setattr(ui_module, "embed_query", lambda q: [0.0] * 768)
    monkeypatch.setattr(
        ui_module,
        "semantic_search",
        lambda *_args, **_kwargs: [
            {
                "kind": "node",
                "table": "Concept",
                "score": 0.91,
                "description": "The core system",
                "ref": {"id": "core", "name": "Core"},
            },
            {
                "kind": "node",
                "table": "SourceFile",
                "score": 0.73,
                "description": "Entry point",
                "ref": {"id": "src/main.py", "name": "main.py"},
            },
        ],
    )

    flask_app = _create_app(db_path, "test-project")
    with flask_app.test_client() as client:
        response = client.get("/search?q=anything")
        assert response.status_code == 200
        assert response.get_json() == {
            "results": [
                {"nodeId": "c:core", "score": 0.91},
                {"nodeId": "f:src/main.py", "score": 0.73},
            ]
        }


def test_search_edge_matches_light_up_both_endpoints(
    theo_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An edge match adds its two endpoints; the higher score wins per node."""
    from theo.cli import ui as ui_module
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"

    monkeypatch.setattr(ui_module, "embed_query", lambda q: [0.0] * 768)
    monkeypatch.setattr(
        ui_module,
        "semantic_search",
        lambda *_args, **_kwargs: [
            # BelongsTo runs SourceFile -> Concept. Both endpoints should appear.
            {
                "kind": "edge",
                "rel_type": "BelongsTo",
                "score": 0.85,
                "description": "main belongs to core",
                "ref": {"from_id": "src/main.py", "to_id": "core"},
            },
            # A weaker direct node match on c:core should not displace the 0.85.
            {
                "kind": "node",
                "table": "Concept",
                "score": 0.40,
                "description": "The core system",
                "ref": {"id": "core", "name": "Core"},
            },
        ],
    )

    flask_app = _create_app(db_path, "test-project")
    with flask_app.test_client() as client:
        response = client.get("/search?q=anything")
        assert response.status_code == 200
        results = response.get_json()["results"]

    by_id = {r["nodeId"]: r["score"] for r in results}
    assert by_id == {"f:src/main.py": 0.85, "c:core": 0.85}
    # Results must come back sorted by descending score.
    assert [r["score"] for r in results] == sorted((r["score"] for r in results), reverse=True)


def test_search_surfaces_backend_errors_as_500(
    theo_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exceptions from embed_query / semantic_search become an HTTP 500."""
    from theo.cli import ui as ui_module
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("model offline")

    monkeypatch.setattr(ui_module, "embed_query", _boom)

    flask_app = _create_app(db_path, "test-project")
    with flask_app.test_client() as client:
        response = client.get("/search?q=anything")
        assert response.status_code == 500
        data = response.get_json()
        assert data["results"] == []
        assert "model offline" in data["error"]


def test_search_top_k_is_clamped_and_forwarded(
    theo_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid/extreme top_k values are coerced before reaching semantic_search."""
    from theo.cli import ui as ui_module
    from theo.cli.ui import _create_app

    db_path = theo_project / ".theo" / "db" / "theo.db"
    seen: list[int] = []

    def _capture(_db: Path, _qvec: Any, _table: Any, top_k: int) -> list[Any]:
        seen.append(top_k)
        return []

    monkeypatch.setattr(ui_module, "embed_query", lambda q: [0.0] * 768)
    monkeypatch.setattr(ui_module, "semantic_search", _capture)

    flask_app = _create_app(db_path, "test-project")
    with flask_app.test_client() as client:
        client.get("/search?q=x&top_k=7")
        client.get("/search?q=x&top_k=notanumber")  # falls back to default 20
        client.get("/search?q=x&top_k=0")  # clamped up to 1
        client.get("/search?q=x&top_k=100000")  # clamped down to 1000

    assert seen == [7, 20, 1, 1000]
