"""``theo ui`` -- interactive vis.js visualization of the Theo knowledge graph.

Starts a local HTTP server and opens a browser to explore the graph.

    run(project_dir_str, port=7777, no_browser=False) -> None

The HTML/CSS/JS layer is copied verbatim from Vito's ``graph_server.py``
(the reference implementation that works well). The data layer is adapted to
Theo's SourceFile schema (no ``language`` / ``line_count``), and the
``/search`` endpoint is a stub -- semantic search will be added later.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from pathlib import Path
from typing import Any, cast

import real_ladybug as lb
import typer

from theo._git import find_theo_root

# ── Color palette ────────────────────────────────────────────────────────────

CONCEPT_COLORS: dict[str, dict[str, Any]] = {
    "system": {
        "background": "#FF6B6B",
        "border": "#E05555",
        "highlight": {"background": "#FF8A8A", "border": "#FF6B6B"},
    },
    "subsystem": {
        "background": "#FFA94D",
        "border": "#E89040",
        "highlight": {"background": "#FFC07A", "border": "#FFA94D"},
    },
    "component": {
        "background": "#FFD93D",
        "border": "#E0C030",
        "highlight": {"background": "#FFE56A", "border": "#FFD93D"},
    },
}

FILE_COLOR: dict[str, Any] = {
    "background": "#C7CEEA",
    "border": "#A8B2D8",
    "highlight": {"background": "#D8DEF2", "border": "#C7CEEA"},
}

EDGE_COLORS: dict[str, str] = {
    "PartOf": "#999999",
    "BelongsTo": "#666666",
    "InteractsWith": "#FF6B6B",
    "DependsOn": "#FFA94D",
    "Imports": "#4ECDC4",
}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _query(conn: lb.Connection, cypher: str) -> list[dict[str, Any]]:
    result = cast(lb.QueryResult, conn.execute(cypher))
    columns = result.get_column_names()
    rows: list[dict[str, Any]] = []
    while result.has_next():
        row = result.get_next()
        rows.append(dict(zip(columns, row, strict=False)))
    return rows


def _esc_html(text: str | None) -> str:
    """Escape for HTML display inside the inspector panel."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "<br>")
    )


# ── Graph building ───────────────────────────────────────────────────────────


def _build_graph(db_path: Path, project_slug: str) -> str:
    """Query the Theo KuzuDB and return a self-contained HTML page."""
    # Fresh connection every request -- the indexer uses COW atomic rename,
    # so a cached handle would read stale data.
    db = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(db)

    concepts = _query(
        conn,
        """
        MATCH (c:Concept)
        RETURN c.id AS id, c.name AS name, c.level AS level, c.kind AS kind,
               c.description AS description, c.notes AS notes
        ORDER BY c.level, c.name
        """,
    )
    files = _query(
        conn,
        """
        MATCH (f:SourceFile)
        RETURN f.path AS path, f.name AS name,
               f.description AS description, f.notes AS notes
        ORDER BY f.path
        """,
    )
    part_of = _query(
        conn, "MATCH (a:Concept)-[:PartOf]->(b:Concept) RETURN a.id AS src, b.id AS dst"
    )
    belongs_to = _query(
        conn,
        "MATCH (f:SourceFile)-[:BelongsTo]->(c:Concept) RETURN f.path AS src, c.id AS dst",
    )
    interacts = _query(
        conn,
        "MATCH (a:Concept)-[r:InteractsWith]->(b:Concept) "
        "RETURN a.id AS src, b.id AS dst, r.description AS description",
    )
    depends = _query(
        conn,
        "MATCH (a:Concept)-[r:DependsOn]->(b:Concept) "
        "RETURN a.id AS src, b.id AS dst, r.description AS description",
    )
    imports = _query(
        conn,
        "MATCH (a:SourceFile)-[r:Imports]->(b:SourceFile) "
        "RETURN a.path AS src, b.path AS dst, r.description AS description",
    )

    # ── Build vis.js data ──

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    size_map = {"system": 45, "subsystem": 32, "component": 24}
    inspector_map: dict[str, str] = {}

    for c in concepts:
        kind = c["kind"]
        colors = CONCEPT_COLORS.get(kind, CONCEPT_COLORS["component"])
        nid = f"c:{c['id']}"

        tip_parts = [
            f'<div class="insp-header">{_esc_html(c["name"])}</div>',
            f'<div class="insp-badge insp-badge-{kind}">{kind} &middot; L{c["level"]}</div>',
        ]
        if c["description"]:
            tip_parts.append(
                f'<div class="insp-section"><span class="insp-label">Description</span>'
                f"{_esc_html(c['description'])}</div>"
            )
        if c.get("notes"):
            tip_parts.append(
                f'<div class="insp-section"><span class="insp-label">Notes</span>'
                f"{_esc_html(c['notes'])}</div>"
            )
        inspector_map[nid] = "\n".join(tip_parts)

        nodes.append(
            {
                "id": nid,
                "label": c["name"],
                "color": colors,
                "size": size_map.get(kind, 20),
                "shape": "dot",
                "font": {
                    "size": 16 if kind == "system" else 13,
                    "color": "white",
                    "strokeWidth": 3,
                    "strokeColor": "#111",
                },
                "mass": 3 if kind == "system" else 2,
                "_kind": kind,
                "_level": c["level"],
            }
        )

    for f in files:
        nid = f"f:{f['path']}"

        tip_parts = [
            f'<div class="insp-header">{_esc_html(f["name"])}</div>',
            f'<div class="insp-meta">{_esc_html(f["path"])}</div>',
        ]
        if f["description"]:
            tip_parts.append(
                f'<div class="insp-section"><span class="insp-label">Description</span>'
                f"{_esc_html(f['description'])}</div>"
            )
        if f.get("notes"):
            tip_parts.append(
                f'<div class="insp-section"><span class="insp-label">Notes</span>'
                f"{_esc_html(f['notes'])}</div>"
            )
        inspector_map[nid] = "\n".join(tip_parts)

        nodes.append(
            {
                "id": nid,
                "label": f["name"],
                "color": FILE_COLOR,
                "size": 10,
                "shape": "square",
                "font": {
                    "size": 9,
                    "color": "#ccc",
                    "strokeWidth": 2,
                    "strokeColor": "#111",
                },
                "mass": 1,
            }
        )

    edge_counter = 0

    def make_edge_id() -> str:
        nonlocal edge_counter
        edge_counter += 1
        return f"e{edge_counter}"

    for e in part_of:
        eid = make_edge_id()
        inspector_map[eid] = (
            f'<div class="insp-header">PartOf</div>'
            f'<div class="insp-meta">{_esc_html(e["src"])} &rarr; {_esc_html(e["dst"])}</div>'
        )
        edges.append(
            {
                "id": eid,
                "from": f"c:{e['src']}",
                "to": f"c:{e['dst']}",
                "color": {"color": EDGE_COLORS["PartOf"], "highlight": "#bbbbbb"},
                "width": 2.5,
                "dashes": False,
                "_type": "PartOf",
                "arrows": {"to": {"enabled": True, "scaleFactor": 0.6}},
            }
        )

    for e in belongs_to:
        eid = make_edge_id()
        inspector_map[eid] = (
            f'<div class="insp-header">BelongsTo</div>'
            f'<div class="insp-meta">{_esc_html(e["src"])} &rarr; {_esc_html(e["dst"])}</div>'
        )
        edges.append(
            {
                "id": eid,
                "from": f"f:{e['src']}",
                "to": f"c:{e['dst']}",
                "color": {"color": EDGE_COLORS["PartOf"], "highlight": "#bbbbbb"},
                "width": 2.5,
                "dashes": [2, 4],
                "_type": "BelongsTo",
                "arrows": {"to": {"enabled": True, "scaleFactor": 0.6}},
                "hidden": False,
            }
        )

    for e in interacts:
        eid = make_edge_id()
        desc = e.get("description", "") or ""
        inspector_map[eid] = (
            f'<div class="insp-header">InteractsWith</div>'
            f'<div class="insp-meta">{_esc_html(e["src"])} &rarr; {_esc_html(e["dst"])}</div>'
            + (f'<div class="insp-section">{_esc_html(desc)}</div>' if desc else "")
        )
        edges.append(
            {
                "id": eid,
                "from": f"c:{e['src']}",
                "to": f"c:{e['dst']}",
                "color": {
                    "color": EDGE_COLORS["InteractsWith"],
                    "highlight": "#FF8A8A",
                },
                "width": 3.5,
                "dashes": False,
                "_type": "InteractsWith",
                "arrows": {"to": {"enabled": True, "scaleFactor": 0.8}},
            }
        )

    for e in depends:
        eid = make_edge_id()
        desc = e.get("description", "") or ""
        inspector_map[eid] = (
            f'<div class="insp-header">DependsOn</div>'
            f'<div class="insp-meta">{_esc_html(e["src"])} &rarr; {_esc_html(e["dst"])}</div>'
            + (f'<div class="insp-section">{_esc_html(desc)}</div>' if desc else "")
        )
        edges.append(
            {
                "id": eid,
                "from": f"c:{e['src']}",
                "to": f"c:{e['dst']}",
                "color": {"color": EDGE_COLORS["DependsOn"], "highlight": "#FFC07A"},
                "width": 2.5,
                "dashes": [10, 5],
                "_type": "DependsOn",
                "arrows": {"to": {"enabled": True, "scaleFactor": 0.6}},
            }
        )

    for e in imports:
        eid = make_edge_id()
        desc = e.get("description", "") or ""
        inspector_map[eid] = (
            f'<div class="insp-header">Imports</div>'
            f'<div class="insp-meta">{_esc_html(e["src"])} &rarr; {_esc_html(e["dst"])}</div>'
            + (f'<div class="insp-section">{_esc_html(desc)}</div>' if desc else "")
        )
        edges.append(
            {
                "id": eid,
                "from": f"f:{e['src']}",
                "to": f"f:{e['dst']}",
                "color": {
                    "color": EDGE_COLORS["Imports"],
                    "opacity": 0.4,
                    "highlight": "#6FE0D8",
                },
                "width": 0.8,
                "dashes": [2, 3],
                "_type": "Imports",
                "arrows": {"to": {"enabled": True, "scaleFactor": 0.3}},
            }
        )

    nodes_json = json.dumps(nodes)
    edges_json = json.dumps(edges)
    inspector_json = json.dumps(inspector_map, ensure_ascii=False)

    stats = {
        "concepts": len(concepts),
        "files": len(files),
        "partOf": len(part_of),
        "belongsTo": len(belongs_to),
        "interactsWith": len(interacts),
        "dependsOn": len(depends),
        "imports": len(imports),
        "total_edges": len(part_of)
        + len(belongs_to)
        + len(interacts)
        + len(depends)
        + len(imports),
    }

    title = f"Theo Knowledge Graph — {_esc_html(project_slug)}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/dist/vis-network.min.js"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/dist/dist/vis-network.min.css"/>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0f0f23; font-family: Inter, system-ui, -apple-system, sans-serif; overflow: hidden; }}
  #graph {{ width: 100vw; height: 100vh; }}

  #legend {{
    position: fixed; top: 16px; left: 16px; z-index: 100;
    background: rgba(15, 15, 35, 0.92); padding: 18px 22px;
    border-radius: 14px; border: 1px solid rgba(255,255,255,0.08);
    color: #ddd; font-size: 12.5px; max-width: 260px;
    backdrop-filter: blur(12px); box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  }}
  #legend h3 {{ margin: 0 0 14px 0; font-size: 15px; color: #fff; letter-spacing: 0.5px; }}
  .legend-section {{ margin-bottom: 6px; font-weight: 600; color: #aaa; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }}
  .legend-item {{ display: flex; align-items: center; gap: 8px; margin: 5px 0; }}
  .legend-swatch {{ flex-shrink: 0; }}
  .legend-line {{ flex-shrink: 0; }}
  .legend-stats {{ margin-top: 14px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.08); font-size: 11px; color: #777; }}

  #controls {{
    position: fixed; top: 16px; right: 16px; z-index: 100;
    background: rgba(15, 15, 35, 0.92); padding: 14px 18px;
    border-radius: 14px; border: 1px solid rgba(255,255,255,0.08);
    color: #ddd; font-size: 12px;
    backdrop-filter: blur(12px); box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  }}
  #controls label {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; cursor: pointer; }}
  #controls input[type="checkbox"] {{ accent-color: #4ECDC4; }}
  #controls button {{
    margin-top: 8px; padding: 6px 14px; border: 1px solid rgba(255,255,255,0.15);
    background: rgba(78, 205, 196, 0.15); color: #4ECDC4; border-radius: 8px;
    cursor: pointer; font-size: 11px; width: 100%;
  }}
  #controls button:hover {{ background: rgba(78, 205, 196, 0.25); }}

  /* Search bar — top center */
  #searchBar {{
    position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
    z-index: 100; display: flex; align-items: center; gap: 0;
    background: rgba(15, 15, 35, 0.92); border-radius: 14px;
    border: 1px solid rgba(255,255,255,0.08);
    backdrop-filter: blur(12px); box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    padding: 4px 8px; min-width: 320px;
  }}
  #searchInput {{
    flex: 1; background: transparent; border: none; outline: none;
    color: #ddd; font-size: 13px; padding: 8px 10px;
    font-family: Inter, system-ui, sans-serif;
  }}
  #searchInput::placeholder {{ color: #555; }}
  #searchClear {{
    background: none; border: none; color: #666; font-size: 16px;
    cursor: pointer; padding: 4px 8px; line-height: 1;
    display: none;
  }}
  #searchClear:hover {{ color: #aaa; }}
  #searchCount {{
    font-size: 11px; color: #4ECDC4; padding: 2px 10px;
    white-space: nowrap; display: none;
  }}
  #searchSpinner {{
    display: none; width: 14px; height: 14px; margin-right: 6px;
    border: 2px solid rgba(78,205,196,0.3); border-top-color: #4ECDC4;
    border-radius: 50%; animation: spin 0.6s linear infinite;
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}

  .insp-search-score {{
    display: inline-block; font-size: 10px; font-weight: 600;
    padding: 2px 8px; border-radius: 4px; margin-left: 8px;
    background: rgba(78,205,196,0.2); color: #4ECDC4;
    vertical-align: middle;
  }}

  /* Inspector panel — fixed bottom-right */
  #inspector {{
    position: fixed;
    bottom: 16px;
    right: 16px;
    z-index: 200;
    width: 350px;
    max-height: 40vh;
    display: flex;
    flex-direction: column;
    background: rgba(15, 15, 35, 0.92);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
    font-size: 12.5px;
    color: #ddd;
    line-height: 1.5;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    backdrop-filter: blur(12px);
  }}

  .inspector-title {{
    padding: 10px 16px 6px;
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
    color: #aaa;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    flex-shrink: 0;
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }}
  .inspector-lock {{
    font-size: 12px;
    color: #4ECDC4;
  }}

  .inspector-body {{
    padding: 10px 16px 14px;
    overflow-y: auto;
    flex: 1;
    min-height: 0;
  }}
  .inspector-body::-webkit-scrollbar {{ width: 6px; }}
  .inspector-body::-webkit-scrollbar-track {{ background: transparent; }}
  .inspector-body::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.15); border-radius: 3px; }}
  .inspector-body::-webkit-scrollbar-thumb:hover {{ background: rgba(255,255,255,0.25); }}

  .insp-placeholder {{
    color: #555;
    font-size: 12px;
    text-align: center;
    padding: 24px 12px;
  }}

  .insp-header {{
    font-size: 14px; font-weight: 700; color: #fff;
    margin-bottom: 6px; padding-bottom: 6px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
  }}
  .insp-badge {{
    display: inline-block; font-size: 10px; font-weight: 600;
    padding: 2px 8px; border-radius: 4px; margin-bottom: 8px;
    text-transform: uppercase; letter-spacing: 0.5px;
  }}
  .insp-badge-system {{ background: rgba(255,107,107,0.25); color: #FF6B6B; }}
  .insp-badge-subsystem {{ background: rgba(255,169,77,0.25); color: #FFA94D; }}
  .insp-badge-component {{ background: rgba(255,217,61,0.25); color: #FFD93D; }}
  .insp-meta {{
    font-size: 11px; color: #999; margin-bottom: 8px;
    font-family: "SF Mono", "Fira Code", monospace;
    word-break: break-all;
  }}
  .insp-section {{
    margin-top: 8px; padding-top: 8px;
    border-top: 1px solid rgba(255,255,255,0.06);
    white-space: pre-wrap; word-wrap: break-word;
  }}
  .insp-label {{
    display: block; font-size: 10px; font-weight: 600;
    color: #4ECDC4; text-transform: uppercase; letter-spacing: 0.8px;
    margin-bottom: 4px;
  }}
</style>
</head>
<body>

<div id="legend">
  <h3>Theo Graph</h3>

  <div class="legend-section">Nodes</div>
  <div class="legend-item">
    <svg class="legend-swatch" width="16" height="16"><circle cx="8" cy="8" r="7" fill="#FF6B6B" stroke="#E05555" stroke-width="1.5"/></svg>
    <span>System (top-level)</span>
  </div>
  <div class="legend-item">
    <svg class="legend-swatch" width="14" height="14"><circle cx="7" cy="7" r="6" fill="#FFA94D" stroke="#E89040" stroke-width="1.5"/></svg>
    <span>Subsystem</span>
  </div>
  <div class="legend-item">
    <svg class="legend-swatch" width="12" height="12"><circle cx="6" cy="6" r="5" fill="#FFD93D" stroke="#E0C030" stroke-width="1.5"/></svg>
    <span>Component</span>
  </div>
  <div class="legend-item">
    <svg class="legend-swatch" width="12" height="12"><rect x="1" y="1" width="10" height="10" rx="2" fill="#C7CEEA" stroke="#A8B2D8" stroke-width="1"/></svg>
    <span>Source file</span>
  </div>

  <div class="legend-section" style="margin-top:12px;">Edges</div>
  <div class="legend-item">
    <svg class="legend-line" width="30" height="6"><line x1="0" y1="3" x2="30" y2="3" stroke="#999" stroke-width="2.5"/></svg>
    <span>PartOf (hierarchy)</span>
  </div>
  <div class="legend-item">
    <svg class="legend-line" width="30" height="6"><line x1="0" y1="3" x2="30" y2="3" stroke="#999" stroke-width="2.5" stroke-dasharray="2,4"/></svg>
    <span>BelongsTo (membership)</span>
  </div>
  <div class="legend-item">
    <svg class="legend-line" width="30" height="6"><line x1="0" y1="3" x2="30" y2="3" stroke="#FF6B6B" stroke-width="3"/></svg>
    <span>InteractsWith (runtime)</span>
  </div>
  <div class="legend-item">
    <svg class="legend-line" width="30" height="6"><line x1="0" y1="3" x2="30" y2="3" stroke="#FFA94D" stroke-width="2.5" stroke-dasharray="10,5"/></svg>
    <span>DependsOn</span>
  </div>
  <div class="legend-item">
    <svg class="legend-line" width="30" height="6"><line x1="0" y1="3" x2="30" y2="3" stroke="#4ECDC4" stroke-width="1" stroke-dasharray="2,3"/></svg>
    <span>Imports (file-to-file)</span>
  </div>

  <div class="legend-stats">
    {stats["concepts"]} concepts &middot; {stats["files"]} files &middot; {stats["total_edges"]} edges<br>
    Inspector panel shows details on hover &middot; Drag to rearrange &middot; Scroll to zoom
  </div>
</div>

<div id="controls">
  <div class="legend-section">Filter concepts</div>
  <label><input type="checkbox" id="togL0" checked> L0</label>
  <label><input type="checkbox" id="togL1" checked> L1</label>
  <label><input type="checkbox" id="togL2" checked> L2</label>
  <label><input type="checkbox" id="togL3plus" checked> L3+</label>
  <div class="legend-section" style="margin-top:10px;">Toggle layers</div>
  <label><input type="checkbox" id="togFiles" checked> Source files</label>
  <label><input type="checkbox" id="togBelongsTo" checked> BelongsTo edges</label>
  <label><input type="checkbox" id="togImports" checked> Import edges</label>
  <label><input type="checkbox" id="togInteracts" checked> InteractsWith</label>
  <label><input type="checkbox" id="togDepends" checked> DependsOn</label>
  <button onclick="network.fit({{animation:true}})">Fit to screen</button>
  <button onclick="togglePhysics()">Toggle physics</button>
</div>

<div id="searchBar">
  <div id="searchSpinner"></div>
  <input id="searchInput" type="text" placeholder="Search nodes..." autocomplete="off" spellcheck="false">
  <span id="searchCount"></span>
  <button id="searchClear" title="Clear search">&times;</button>
</div>

<div id="graph"></div>

<div id="inspector">
  <div class="inspector-title">
    <span>Inspector</span>
    <span class="inspector-lock" id="lockBadge" style="display:none">&#128274;</span>
  </div>
  <div class="inspector-body" id="inspectorBody">
    <div class="insp-placeholder">Hover over a node or edge to see details</div>
  </div>
</div>

<script>
const nodesData = {nodes_json};
const edgesData = {edges_json};
const inspectorData = {inspector_json};

nodesData.forEach(n => {{
  n._isFile = n.id.startsWith("f:");
  if (!n._kind) n._kind = null;
  // Save original colors for focus+context restore
  n._origColor = JSON.parse(JSON.stringify(n.color));
  n._origFontColor = n.font ? n.font.color : "#ccc";
}});

edgesData.forEach(e => {{
  e._origColor = JSON.parse(JSON.stringify(e.color));
}});

const nodes = new vis.DataSet(nodesData);
const edges = new vis.DataSet(edgesData);

const container = document.getElementById("graph");
const data = {{ nodes, edges }};

const options = {{
  physics: {{
    enabled: true,
    solver: "forceAtlas2Based",
    forceAtlas2Based: {{
      gravitationalConstant: -120,
      centralGravity: 0.012,
      springLength: 180,
      springConstant: 0.035,
      damping: 0.45,
      avoidOverlap: 0.85
    }},
    stabilization: {{
      enabled: true,
      iterations: 400,
      updateInterval: 20,
      fit: true
    }},
    maxVelocity: 50,
    minVelocity: 0.75,
  }},
  edges: {{
    smooth: {{ type: "continuous", forceDirection: "none" }},
    hoverWidth: 2,
    selectionWidth: 2,
  }},
  interaction: {{
    hover: true,
    hideEdgesOnDrag: true,
    hideEdgesOnZoom: true,
    multiselect: true,
    navigationButtons: false,
    keyboard: {{ enabled: true }},
    zoomView: true,
  }},
  layout: {{
    improvedLayout: true,
  }},
}};

const network = new vis.Network(container, data, options);

network.once("stabilizationIterationsDone", function() {{
  network.setOptions({{ physics: {{ enabled: false }} }});
}});

// ── Semantic search state ──
const searchState = {{ active: false, matchIds: new Set(), scores: {{}} }};
let searchAbort = null;
let searchDebounceTimer = null;
const searchInput = document.getElementById("searchInput");
const searchClear = document.getElementById("searchClear");
const searchCount = document.getElementById("searchCount");
const searchSpinner = document.getElementById("searchSpinner");

// ── Inspector panel ──
const inspectorBody = document.getElementById("inspectorBody");
const lockBadge = document.getElementById("lockBadge");
let inspectorLocked = false;
const PLACEHOLDER_HTML = '<div class="insp-placeholder">Hover over a node or edge to see details</div>';

function showInspector(id) {{
  const html = inspectorData[id];
  if (!html) return;
  inspectorBody.innerHTML = html;
  // Inject search score badge if search is active and this node matched
  if (searchState.active && searchState.scores[id] !== undefined) {{
    const badge = document.createElement("span");
    badge.className = "insp-search-score";
    badge.textContent = "\\uD83D\\uDD0D " + searchState.scores[id].toFixed(2);  // magnifying glass emoji
    const header = inspectorBody.querySelector(".insp-header");
    if (header) header.appendChild(badge);
  }}
}}

function unlockInspector() {{
  inspectorLocked = false;
  lockBadge.style.display = "none";
  inspectorBody.innerHTML = PLACEHOLDER_HTML;
}}

// ── Focus+context: dim non-neighbors on hover ──
const DIMMED_NODE = {{ background: "rgba(60,60,80,0.12)", border: "rgba(60,60,80,0.18)" }};
const DIMMED_FONT = "rgba(255,255,255,0.06)";
const DIMMED_EDGE = "rgba(100,100,120,0.08)";
let focusActive = false;

// Build the search-highlighted color for a node: original color + cyan glow
// proportional to the match score.
function searchColorForNode(n) {{
  const score = searchState.scores[n.id];
  if (score === undefined) {{
    return {{ color: DIMMED_NODE, fontColor: DIMMED_FONT }};
  }}
  // Matched node: keep original colors, add cyan border glow scaled by score
  const glowAlpha = 0.4 + score * 0.6;  // range 0.4 - 1.0
  const glowWidth = 2 + Math.round(score * 4);
  return {{
    color: {{
      background: n._origColor.background,
      border: `rgba(78, 205, 196, ${{glowAlpha}})`,
      highlight: n._origColor.highlight || {{ background: n._origColor.background, border: `rgba(78, 205, 196, 1)` }},
    }},
    fontColor: n._origFontColor,
    borderWidth: glowWidth,
  }};
}}

function applySearchHighlighting() {{
  // Apply search glow to matched nodes, dim non-matched (skip hidden)
  const nodeUpdates = [];
  nodesData.forEach(n => {{
    const current = nodes.get(n.id);
    if (current && current.hidden) return;
    const sc = searchColorForNode(n);
    const upd = {{ id: n.id, color: sc.color, font: {{ color: sc.fontColor }} }};
    if (sc.borderWidth) upd.borderWidth = sc.borderWidth;
    nodeUpdates.push(upd);
  }});
  nodes.update(nodeUpdates);

  // Only show edges where both endpoints are search matches
  const edgeUpdates = [];
  edgesData.forEach(e => {{
    const current = edges.get(e.id);
    if (current && current.hidden) return;
    const fromMatch = searchState.matchIds.has(e.from);
    const toMatch = searchState.matchIds.has(e.to);
    if (fromMatch && toMatch) {{
      edgeUpdates.push({{ id: e.id, color: e._origColor }});
    }} else {{
      edgeUpdates.push({{ id: e.id, color: {{ color: DIMMED_EDGE, highlight: DIMMED_EDGE }} }});
    }}
  }});
  edges.update(edgeUpdates);

  focusActive = true;
}}

function highlightNeighbors(hoveredNodeId) {{
  const neighborIds = network.getConnectedNodes(hoveredNodeId);
  const connectedEdgeIds = network.getConnectedEdges(hoveredNodeId);

  const activeNodes = new Set(neighborIds);
  activeNodes.add(hoveredNodeId);
  const activeEdges = new Set(connectedEdgeIds);

  const nodeUpdates = [];
  nodesData.forEach(n => {{
    // Skip hidden nodes (managed by filters)
    const current = nodes.get(n.id);
    if (current && current.hidden) return;
    if (activeNodes.has(n.id)) {{
      // Active (neighbor or hovered) node: prefer search glow if matched,
      // otherwise fall back to original color.
      if (searchState.active && searchState.scores[n.id] !== undefined) {{
        const sc = searchColorForNode(n);
        const upd = {{ id: n.id, color: sc.color, font: {{ color: sc.fontColor }} }};
        if (sc.borderWidth) upd.borderWidth = sc.borderWidth;
        nodeUpdates.push(upd);
      }} else {{
        nodeUpdates.push({{ id: n.id, color: n._origColor, font: {{ color: n._origFontColor }} }});
      }}
    }} else {{
      // Non-neighbor: use search-aware dimming when search is active so
      // matched non-neighbors keep their cyan glow (at reduced opacity).
      if (searchState.active) {{
        const sc = searchColorForNode(n);
        const upd = {{ id: n.id, color: sc.color, font: {{ color: sc.fontColor }} }};
        if (sc.borderWidth) upd.borderWidth = sc.borderWidth;
        nodeUpdates.push(upd);
      }} else {{
        nodeUpdates.push({{ id: n.id, color: DIMMED_NODE, font: {{ color: DIMMED_FONT }} }});
      }}
    }}
  }});
  nodes.update(nodeUpdates);

  const edgeUpdates = [];
  edgesData.forEach(e => {{
    const current = edges.get(e.id);
    if (current && current.hidden) return;
    if (activeEdges.has(e.id)) {{
      edgeUpdates.push({{ id: e.id, color: e._origColor }});
    }} else {{
      edgeUpdates.push({{ id: e.id, color: {{ color: DIMMED_EDGE, highlight: DIMMED_EDGE }} }});
    }}
  }});
  edges.update(edgeUpdates);

  focusActive = true;
}}

function restoreAllColors() {{
  if (!focusActive) return;

  if (searchState.active) {{
    // Restore to search-highlighted state, not base colors
    applySearchHighlighting();
    return;
  }}

  restoreBaseColors();
}}

// ── Restore base colors (bypass search state — used only by clearSearch) ──
function restoreBaseColors() {{
  const nodeUpdates = [];
  nodesData.forEach(n => {{
    const current = nodes.get(n.id);
    if (current && current.hidden) return;
    nodeUpdates.push({{ id: n.id, color: n._origColor, font: {{ color: n._origFontColor }}, borderWidth: undefined }});
  }});
  nodes.update(nodeUpdates);

  const edgeUpdates = [];
  edgesData.forEach(e => {{
    const current = edges.get(e.id);
    if (current && current.hidden) return;
    edgeUpdates.push({{ id: e.id, color: e._origColor }});
  }});
  edges.update(edgeUpdates);

  focusActive = false;
}}

// ── Search execution ──
function executeSearch(query) {{
  if (searchAbort) {{ searchAbort.abort(); searchAbort = null; }}
  const q = query.trim();
  if (!q) {{ clearSearch(); return; }}

  searchAbort = new AbortController();
  searchSpinner.style.display = "block";

  fetch("/search?q=" + encodeURIComponent(q) + "&top_k=20", {{ signal: searchAbort.signal }})
    .then(r => r.json())
    .then(data => {{
      searchSpinner.style.display = "none";
      searchAbort = null;

      searchState.active = true;
      searchState.matchIds = new Set();
      searchState.scores = {{}};

      (data.results || []).forEach(r => {{
        searchState.matchIds.add(r.nodeId);
        searchState.scores[r.nodeId] = r.score;
      }});

      // Update UI
      const count = searchState.matchIds.size;
      searchCount.textContent = count + (count === 1 ? " match" : " matches");
      searchCount.style.display = "inline";
      searchClear.style.display = "block";

      if (count === 0) {{
        // No matches — restore base colors, no fit
        searchState.active = false;
        restoreBaseColors();
        return;
      }}

      // Apply highlighting
      applySearchHighlighting();

      // Fit view to visible matched nodes only
      const visibleMatchIds = [];
      searchState.matchIds.forEach(id => {{
        const n = nodes.get(id);
        if (n && !n.hidden) visibleMatchIds.push(id);
      }});
      if (visibleMatchIds.length > 0) {{
        network.fit({{
          nodes: visibleMatchIds,
          animation: {{ duration: 600, easingFunction: "easeInOutQuad" }}
        }});
      }}
    }})
    .catch(err => {{
      if (err.name === "AbortError") return;  // cancelled by new query
      searchSpinner.style.display = "none";
      searchAbort = null;
      console.error("Search failed:", err);
    }});
}}

function clearSearch() {{
  if (searchAbort) {{ searchAbort.abort(); searchAbort = null; }}
  if (searchDebounceTimer) {{ clearTimeout(searchDebounceTimer); searchDebounceTimer = null; }}

  searchState.active = false;
  searchState.matchIds = new Set();
  searchState.scores = {{}};

  searchInput.value = "";
  searchCount.style.display = "none";
  searchClear.style.display = "none";
  searchSpinner.style.display = "none";

  restoreBaseColors();
}}

// Wire up search input
searchInput.addEventListener("input", function() {{
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
  const val = searchInput.value;
  if (!val.trim()) {{
    clearSearch();
    return;
  }}
  searchClear.style.display = "block";
  searchDebounceTimer = setTimeout(() => executeSearch(val), 400);
}});

searchInput.addEventListener("keydown", function(e) {{
  if (e.key === "Enter") {{
    e.preventDefault();
    if (searchDebounceTimer) {{ clearTimeout(searchDebounceTimer); searchDebounceTimer = null; }}
    executeSearch(searchInput.value);
  }}
  // Prevent ESC from bubbling to the document handler (which would also
  // unlock the inspector or clear the search — two actions for one keypress).
  if (e.key === "Escape") {{
    searchInput.blur();
    e.stopPropagation();
  }}
}});

searchClear.addEventListener("click", clearSearch);

// ── Event handlers ──
network.on("hoverNode", function(params) {{
  if (!inspectorLocked) {{
    showInspector(params.node);
    highlightNeighbors(params.node);
  }}
}});
network.on("blurNode", function() {{
  if (!inspectorLocked) {{
    inspectorBody.innerHTML = PLACEHOLDER_HTML;
    restoreAllColors();
  }}
}});

network.on("hoverEdge", function(params) {{
  if (!inspectorLocked) showInspector(params.edge);
}});
network.on("blurEdge", function() {{
  if (!inspectorLocked) inspectorBody.innerHTML = PLACEHOLDER_HTML;
}});

network.on("click", function(params) {{
  if (params.nodes.length > 0) {{
    inspectorLocked = true;
    lockBadge.style.display = "inline";
    showInspector(params.nodes[0]);
    highlightNeighbors(params.nodes[0]);
  }} else if (params.edges.length > 0) {{
    inspectorLocked = true;
    lockBadge.style.display = "inline";
    showInspector(params.edges[0]);
    restoreAllColors();
  }} else {{
    unlockInspector();
    restoreAllColors();
  }}
}});

// Two-stage ESC: first unlock inspector (restore search state),
// then clear search entirely
document.addEventListener("keydown", function(e) {{
  if (e.key === "Escape") {{
    if (inspectorLocked) {{
      unlockInspector();
      restoreAllColors();
    }} else if (searchState.active) {{
      clearSearch();
    }}
  }}
}});

// ── Filtering controls ──
let physicsOn = false;

function togglePhysics() {{
  physicsOn = !physicsOn;
  network.setOptions({{ physics: {{ enabled: physicsOn }} }});
}}

function applyFilters() {{
  // Restore colors before applying filters so filter logic
  // always operates on nodes/edges in their normal visual state.
  // restoreAllColors() will restore to search-highlighted state if
  // search is active, or to base colors otherwise.
  restoreAllColors();

  const showFiles = document.getElementById("togFiles").checked;
  const showBelongsTo = document.getElementById("togBelongsTo").checked;
  const showImports = document.getElementById("togImports").checked;
  const showInteracts = document.getElementById("togInteracts").checked;
  const showDepends = document.getElementById("togDepends").checked;

  const showL0 = document.getElementById("togL0").checked;
  const showL1 = document.getElementById("togL1").checked;
  const showL2 = document.getElementById("togL2").checked;
  const showL3plus = document.getElementById("togL3plus").checked;

  // Build set of hidden node IDs
  const hiddenNodes = new Set();
  const nodeUpdates = nodesData.map(n => {{
    let hidden = false;
    if (n._isFile) {{
      hidden = !showFiles;
    }} else if (n._level !== undefined && n._level !== null) {{
      if (n._level === 0) hidden = !showL0;
      else if (n._level === 1) hidden = !showL1;
      else if (n._level === 2) hidden = !showL2;
      else hidden = !showL3plus;
    }}
    if (hidden) hiddenNodes.add(n.id);
    return {{ id: n.id, hidden }};
  }});
  nodes.update(nodeUpdates);

  const edgeUpdates = edgesData.map(e => {{
    // Hide edge if either endpoint is hidden
    if (hiddenNodes.has(e.from) || hiddenNodes.has(e.to)) {{
      return {{ id: e.id, hidden: true }};
    }}
    let hidden = false;
    if (e._type === "BelongsTo") hidden = !showBelongsTo;
    else if (e._type === "Imports") hidden = !showImports;
    else if (e._type === "InteractsWith") hidden = !showInteracts;
    else if (e._type === "DependsOn") hidden = !showDepends;
    return {{ id: e.id, hidden }};
  }});
  edges.update(edgeUpdates);

  // Re-apply search glow to any newly-visible nodes after filter change
  if (searchState.active) applySearchHighlighting();
}}

document.querySelectorAll("#controls input").forEach(el => {{
  el.addEventListener("change", applyFilters);
}});
</script>
</body>
</html>"""


_NO_DATA_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Theo Graph</title>
<style>
  body {
    background: #0f0f23; color: #ccc; font-family: Inter, system-ui, sans-serif;
    display: flex; align-items: center; justify-content: center; height: 100vh;
  }
  .box {
    text-align: center; padding: 40px; border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px; background: rgba(15, 15, 35, 0.92);
  }
  h1 { font-size: 22px; color: #fff; margin-bottom: 12px; }
  p { font-size: 14px; color: #999; }
</style>
</head>
<body>
<div class="box">
  <h1>No graph data yet</h1>
  <p>Run the Theo indexer first to populate the knowledge graph.</p>
</div>
</body>
</html>"""


def _ensure_flask() -> None:
    """Raise a helpful error if Flask is not installed."""
    try:
        import flask  # noqa: F401
    except ImportError:
        typer.echo(
            'Error: Flask is required for `theo ui`. Install it with: pip install "theo[ui]"',
            err=True,
        )
        raise typer.Exit(1)  # noqa: B904


def _create_app(db_path: Path, project_slug: str) -> Any:
    """Create and configure the Flask application."""
    from flask import Flask as _Flask
    from flask import jsonify

    flask_app = _Flask(__name__)

    @flask_app.route("/")
    def index() -> tuple[str, int, dict[str, str]]:
        if not db_path.exists():
            return _NO_DATA_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}
        return (
            _build_graph(db_path, project_slug),
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    @flask_app.route("/health")
    def health() -> Any:
        return jsonify({"status": "ok"})

    @flask_app.route("/search")
    def search() -> Any:
        """Search stub. Semantic search will be wired in later; for now
        the frontend gets an empty result set so the search bar is inert."""
        return jsonify({"results": []})

    return flask_app


def run(project_dir_str: str, *, port: int = 7777, no_browser: bool = False) -> None:
    """Start the Theo graph visualization server."""
    project_dir = Path(project_dir_str).resolve()
    root = find_theo_root(project_dir)
    if root is None:
        typer.echo("Error: no .theo/config.json found (searched upward).", err=True)
        raise typer.Exit(1)

    config_path = root / ".theo" / "config.json"
    config = json.loads(config_path.read_text())
    db_rel = config["db_path"]
    db_path = (root / db_rel).resolve()
    project_slug: str = config.get("project_slug", root.name)

    if not db_path.exists():
        typer.echo("Error: database not found. Run 'theo use' first.", err=True)
        raise typer.Exit(1)

    _ensure_flask()
    flask_app = _create_app(db_path, project_slug)

    url = f"http://127.0.0.1:{port}/"
    typer.echo(f"Starting Theo graph UI at {url}")

    if not no_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()

    flask_app.run(host="127.0.0.1", port=port)
