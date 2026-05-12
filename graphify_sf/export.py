# write graph to HTML, JSON, GraphML, Obsidian vault, and Neo4j Cypher
from __future__ import annotations

import html as _html
import json
import re
from collections import Counter
from pathlib import Path

import networkx as nx
from networkx.readwrite import json_graph

from graphify_sf.analyze import _node_community_map
from graphify_sf.build import edge_data
from graphify_sf.security import sanitize_label


def _obsidian_tag(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-/]", "", name.replace(" ", "_"))


def _strip_diacritics(text: str) -> str:
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _yaml_str(s: str) -> str:
    if s is None:
        return ""
    out: list[str] = []
    for ch in str(s):
        cp = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\0":
            out.append("\\0")
        elif cp == 0x2028:
            out.append("\\L")
        elif cp == 0x2029:
            out.append("\\P")
        elif cp < 0x20 or cp == 0x7F:
            out.append(f"\\x{cp:02x}")
        else:
            out.append(ch)
    return "".join(out)


COMMUNITY_COLORS = [
    "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
]

MAX_NODES_FOR_VIZ = 5_000


def _viz_node_limit() -> int:
    import os
    raw = os.environ.get("GRAPHIFY_SF_VIZ_NODE_LIMIT")
    if raw is None or not raw.strip():
        return MAX_NODES_FOR_VIZ
    try:
        return int(raw)
    except ValueError:
        return MAX_NODES_FOR_VIZ


def _html_styles() -> str:
    return """<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f0f1a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; display: flex; height: 100vh; overflow: hidden; }
  #graph { flex: 1; }
  #sidebar { width: 280px; background: #1a1a2e; border-left: 1px solid #2a2a4e; display: flex; flex-direction: column; overflow: hidden; }
  #search-wrap { padding: 12px; border-bottom: 1px solid #2a2a4e; }
  #search { width: 100%; background: #0f0f1a; border: 1px solid #3a3a5e; color: #e0e0e0; padding: 7px 10px; border-radius: 6px; font-size: 13px; outline: none; }
  #search:focus { border-color: #4E79A7; }
  #search-results { max-height: 140px; overflow-y: auto; padding: 4px 12px; border-bottom: 1px solid #2a2a4e; display: none; }
  .search-item { padding: 4px 6px; cursor: pointer; border-radius: 4px; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .search-item:hover { background: #2a2a4e; }
  #info-panel { padding: 14px; border-bottom: 1px solid #2a2a4e; min-height: 140px; }
  #info-panel h3 { font-size: 13px; color: #aaa; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em; }
  #info-content { font-size: 13px; color: #ccc; line-height: 1.6; }
  #info-content .field { margin-bottom: 5px; }
  #info-content .field b { color: #e0e0e0; }
  #info-content .empty { color: #555; font-style: italic; }
  .neighbor-link { display: block; padding: 2px 6px; margin: 2px 0; border-radius: 3px; cursor: pointer; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-left: 3px solid #333; }
  .neighbor-link:hover { background: #2a2a4e; }
  #neighbors-list { max-height: 160px; overflow-y: auto; margin-top: 4px; }
  #legend-wrap { flex: 1; overflow-y: auto; padding: 12px; }
  #legend-wrap h3 { font-size: 13px; color: #aaa; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.05em; }
  .legend-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; cursor: pointer; border-radius: 4px; font-size: 12px; }
  .legend-item:hover { background: #2a2a4e; padding-left: 4px; }
  .legend-item.dimmed { opacity: 0.35; }
  .legend-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
  .legend-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .legend-count { color: #666; font-size: 11px; }
  #stats { padding: 10px 14px; border-top: 1px solid #2a2a4e; font-size: 11px; color: #555; }
  #legend-controls { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; padding: 4px 0; }
  #legend-controls label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 12px; color: #aaa; user-select: none; }
  #legend-controls label:hover { color: #e0e0e0; }
  .legend-cb, #select-all-cb { appearance: none; -webkit-appearance: none; width: 14px; height: 14px; border: 1.5px solid #3a3a5e; border-radius: 3px; background: #0f0f1a; cursor: pointer; position: relative; flex-shrink: 0; }
  .legend-cb:checked, #select-all-cb:checked { background: #4E79A7; border-color: #4E79A7; }
  .legend-cb:checked::after, #select-all-cb:checked::after { content: ''; position: absolute; left: 3.5px; top: 1px; width: 4px; height: 7px; border: solid #fff; border-width: 0 2px 2px 0; transform: rotate(45deg); }
  #select-all-cb:indeterminate { background: #4E79A7; border-color: #4E79A7; }
  #select-all-cb:indeterminate::after { content: ''; position: absolute; left: 2px; top: 5px; width: 8px; height: 2px; background: #fff; border: none; transform: none; }
</style>"""


def _html_script(nodes_json: str, edges_json: str, legend_json: str) -> str:
    return f"""<script>
const RAW_NODES = {nodes_json};
const RAW_EDGES = {edges_json};
const LEGEND = {legend_json};

function esc(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}}

const nodesDS = new vis.DataSet(RAW_NODES.map(n => ({{
  id: n.id, label: n.label, color: n.color, size: n.size,
  font: n.font, title: n.title,
  _community: n.community, _community_name: n.community_name,
  _source_file: n.source_file, _file_type: n.file_type,
  _sf_type: n.sf_type, _degree: n.degree,
}})));

const edgesDS = new vis.DataSet(RAW_EDGES.map((e, i) => ({{
  id: i, from: e.from, to: e.to,
  label: '',
  title: e.title,
  dashes: e.dashes,
  width: e.width,
  color: e.color,
  arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }},
}})));

const container = document.getElementById('graph');
const network = new vis.Network(container, {{ nodes: nodesDS, edges: edgesDS }}, {{
  physics: {{
    enabled: true,
    solver: 'forceAtlas2Based',
    forceAtlas2Based: {{
      gravitationalConstant: -60,
      centralGravity: 0.005,
      springLength: 120,
      springConstant: 0.08,
      damping: 0.4,
      avoidOverlap: 0.8,
    }},
    stabilization: {{ iterations: 200, fit: true }},
  }},
  interaction: {{
    hover: true,
    tooltipDelay: 100,
    hideEdgesOnDrag: true,
    navigationButtons: false,
    keyboard: false,
  }},
  nodes: {{ shape: 'dot', borderWidth: 1.5 }},
  edges: {{ smooth: {{ type: 'continuous', roundness: 0.2 }}, selectionWidth: 3 }},
}});

network.once('stabilizationIterationsDone', () => {{
  network.setOptions({{ physics: {{ enabled: false }} }});
}});

function showInfo(nodeId) {{
  const n = nodesDS.get(nodeId);
  if (!n) return;
  const neighborIds = network.getConnectedNodes(nodeId);
  const neighborItems = neighborIds.map(nid => {{
    const nb = nodesDS.get(nid);
    const color = nb ? nb.color.background : '#555';
    return `<span class="neighbor-link" style="border-left-color:${{esc(color)}}" onclick="focusNode(${{JSON.stringify(nid)}})">${{esc(nb ? nb.label : nid)}}</span>`;
  }}).join('');
  document.getElementById('info-content').innerHTML = `
    <div class="field"><b>${{esc(n.label)}}</b></div>
    <div class="field">SF Type: ${{esc(n._sf_type || n._file_type || 'unknown')}}</div>
    <div class="field">Community: ${{esc(n._community_name)}}</div>
    <div class="field">Source: ${{esc(n._source_file || '-')}}</div>
    <div class="field">Degree: ${{n._degree}}</div>
    ${{neighborIds.length ? `<div class="field" style="margin-top:8px;color:#aaa;font-size:11px">Neighbors (${{neighborIds.length}})</div><div id="neighbors-list">${{neighborItems}}</div>` : ''}}
  `;
}}

function focusNode(nodeId) {{
  network.focus(nodeId, {{ scale: 1.4, animation: true }});
  network.selectNodes([nodeId]);
  showInfo(nodeId);
}}

let hoveredNodeId = null;
network.on('hoverNode', params => {{
  hoveredNodeId = params.node;
  container.style.cursor = 'pointer';
}});
network.on('blurNode', () => {{
  hoveredNodeId = null;
  container.style.cursor = 'default';
}});
container.addEventListener('click', () => {{
  if (hoveredNodeId !== null) {{
    showInfo(hoveredNodeId);
    network.selectNodes([hoveredNodeId]);
  }}
}});
network.on('click', params => {{
  if (params.nodes.length > 0) {{
    showInfo(params.nodes[0]);
  }} else if (hoveredNodeId === null) {{
    document.getElementById('info-content').innerHTML = '<span class="empty">Click a node to inspect it</span>';
  }}
}});

const searchInput = document.getElementById('search');
const searchResults = document.getElementById('search-results');
searchInput.addEventListener('input', () => {{
  const q = searchInput.value.toLowerCase().trim();
  searchResults.innerHTML = '';
  if (!q) {{ searchResults.style.display = 'none'; return; }}
  const matches = RAW_NODES.filter(n => n.label.toLowerCase().includes(q)).slice(0, 20);
  if (!matches.length) {{ searchResults.style.display = 'none'; return; }}
  searchResults.style.display = 'block';
  matches.forEach(n => {{
    const el = document.createElement('div');
    el.className = 'search-item';
    el.textContent = n.label;
    el.style.borderLeft = `3px solid ${{n.color.background}}`;
    el.style.paddingLeft = '8px';
    el.onclick = () => {{
      network.focus(n.id, {{ scale: 1.5, animation: true }});
      network.selectNodes([n.id]);
      showInfo(n.id);
      searchResults.style.display = 'none';
      searchInput.value = '';
    }};
    searchResults.appendChild(el);
  }});
}});
document.addEventListener('click', e => {{
  if (!searchResults.contains(e.target) && e.target !== searchInput)
    searchResults.style.display = 'none';
}});

const hiddenCommunities = new Set();
const selectAllCb = document.getElementById('select-all-cb');

function updateSelectAllState() {{
  const total = LEGEND.length;
  const hidden = hiddenCommunities.size;
  selectAllCb.checked = hidden === 0;
  selectAllCb.indeterminate = hidden > 0 && hidden < total;
}}

function toggleAllCommunities(hide) {{
  document.querySelectorAll('.legend-item').forEach(item => {{
    hide ? item.classList.add('dimmed') : item.classList.remove('dimmed');
  }});
  document.querySelectorAll('.legend-cb').forEach(cb => {{
    cb.checked = !hide;
  }});
  LEGEND.forEach(c => {{
    if (hide) hiddenCommunities.add(c.cid); else hiddenCommunities.delete(c.cid);
  }});
  const updates = RAW_NODES.map(n => ({{ id: n.id, hidden: hide }}));
  nodesDS.update(updates);
  updateSelectAllState();
}}

const legendEl = document.getElementById('legend');
LEGEND.forEach(c => {{
  const item = document.createElement('div');
  item.className = 'legend-item';
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.className = 'legend-cb';
  cb.checked = true;
  cb.addEventListener('change', (e) => {{
    e.stopPropagation();
    if (cb.checked) {{
      hiddenCommunities.delete(c.cid);
      item.classList.remove('dimmed');
    }} else {{
      hiddenCommunities.add(c.cid);
      item.classList.add('dimmed');
    }}
    const updates = RAW_NODES
      .filter(n => n.community === c.cid)
      .map(n => ({{ id: n.id, hidden: !cb.checked }}));
    nodesDS.update(updates);
    updateSelectAllState();
  }});
  item.innerHTML = `<div class="legend-dot" style="background:${{c.color}}"></div>
    <span class="legend-label">${{c.label}}</span>
    <span class="legend-count">${{c.count}}</span>`;
  item.prepend(cb);
  item.onclick = (e) => {{
    if (e.target === cb) return;
    cb.checked = !cb.checked;
    cb.dispatchEvent(new Event('change'));
  }};
  legendEl.appendChild(item);
}});
</script>"""


_CONFIDENCE_SCORE_DEFAULTS = {"EXTRACTED": 1.0, "INFERRED": 0.5, "AMBIGUOUS": 0.2}


def _git_head() -> str | None:
    import subprocess as _sp
    try:
        r = _sp.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def to_json(G: nx.Graph, communities: dict[int, list[str]], output_path: str, *, force: bool = False, built_at_commit: str | None = None) -> bool:
    existing_path = Path(output_path)
    if not force and existing_path.exists():
        try:
            existing_data = json.loads(existing_path.read_text(encoding="utf-8"))
            existing_n = len(existing_data.get("nodes", []))
            new_n = G.number_of_nodes()
            if new_n < existing_n:
                import sys as _sys
                print(
                    f"[graphify-sf] WARNING: new graph has {new_n} nodes but existing "
                    f"graph.json has {existing_n}. Refusing to overwrite — you may be "
                    f"missing files from a previous run. "
                    f"Pass force=True to override.",
                    file=_sys.stderr,
                )
                return False
        except Exception:
            pass

    node_community = _node_community_map(communities)
    try:
        data = json_graph.node_link_data(G, edges="links")
    except TypeError:
        data = json_graph.node_link_data(G)
    for node in data["nodes"]:
        node["community"] = node_community.get(node["id"])
        node["norm_label"] = _strip_diacritics(node.get("label", "")).lower()
    for link in data["links"]:
        if "confidence_score" not in link:
            conf = link.get("confidence", "EXTRACTED")
            link["confidence_score"] = _CONFIDENCE_SCORE_DEFAULTS.get(conf, 1.0)
        true_src = link.pop("_src", None)
        true_tgt = link.pop("_tgt", None)
        if true_src is not None and true_tgt is not None:
            link["source"] = true_src
            link["target"] = true_tgt
    data["hyperedges"] = getattr(G, "graph", {}).get("hyperedges", [])
    commit = built_at_commit if built_at_commit is not None else _git_head()
    if commit:
        data["built_at_commit"] = commit
    with open(output_path, "w", encoding="utf-8") as f:  # nosec
        json.dump(data, f, indent=2)
    return True


def prune_dangling_edges(graph_data: dict) -> tuple[dict, int]:
    node_ids = {n["id"] for n in graph_data["nodes"]}
    links_key = "links" if "links" in graph_data else "edges"
    before = len(graph_data[links_key])
    graph_data[links_key] = [
        e for e in graph_data[links_key]
        if e["source"] in node_ids and e["target"] in node_ids
    ]
    return graph_data, before - len(graph_data[links_key])


def _cypher_escape(s: str) -> str:
    s = "".join(ch for ch in s if ch >= " " or ch == "\t")
    return (
        s.replace("\\", "\\\\")
         .replace("'", "\\'")
         .replace("\n", "\\n")
         .replace("\r", "\\r")
    )


_CYPHER_IDENT_RE = re.compile(r"[^A-Za-z0-9_]")


def _cypher_label(raw: str, fallback: str) -> str:
    cleaned = _CYPHER_IDENT_RE.sub("", raw or "")
    if not cleaned or not cleaned[0].isalpha():
        return fallback
    return cleaned


def to_cypher(G: nx.Graph, output_path: str) -> None:
    lines = ["// Neo4j Cypher import - generated by graphify-sf", ""]
    for node_id, data in G.nodes(data=True):
        label = _cypher_escape(data.get("label", node_id))
        node_id_esc = _cypher_escape(node_id)
        ftype = _cypher_label(
            (data.get("sf_type", data.get("file_type", "unknown")) or "Entity").replace(" ", ""),
            "SFEntity",
        )
        lines.append(f"MERGE (n:{ftype} {{id: '{node_id_esc}', label: '{label}'}});")
    lines.append("")
    for u, v, data in G.edges(data=True):
        rel = _cypher_label(
            (data.get("relation", "RELATES_TO") or "RELATES_TO").upper(),
            "RELATES_TO",
        )
        conf = _cypher_escape(data.get("confidence", "EXTRACTED"))
        u_esc = _cypher_escape(u)
        v_esc = _cypher_escape(v)
        lines.append(
            f"MATCH (a {{id: '{u_esc}'}}), (b {{id: '{v_esc}'}}) "
            f"MERGE (a)-[:{rel} {{confidence: '{conf}'}}]->(b);"
        )
    with open(output_path, "w", encoding="utf-8") as f:  # nosec
        f.write("\n".join(lines))


def to_html(
    G: nx.Graph,
    communities: dict[int, list[str]],
    output_path: str,
    community_labels: dict[int, str] | None = None,
    member_counts: dict[int, int] | None = None,
    node_limit: int | None = None,
) -> None:
    limit = node_limit if node_limit is not None else _viz_node_limit()
    if G.number_of_nodes() > limit:
        if node_limit is not None:
            from collections import Counter as _Counter

            import networkx as _nx
            print(f"Graph has {G.number_of_nodes()} nodes (above {limit} limit). Building aggregated community view...")
            node_to_community = {nid: cid for cid, members in communities.items() for nid in members}
            meta = _nx.Graph()
            for cid, members in communities.items():
                meta.add_node(str(cid), label=(community_labels or {}).get(cid, f"Community {cid}"))
            edge_counts = _Counter()
            for u, v in G.edges():
                cu, cv = node_to_community.get(u), node_to_community.get(v)
                if cu is not None and cv is not None and cu != cv:
                    edge_counts[(min(cu, cv), max(cu, cv))] += 1
            for (cu, cv), w in edge_counts.items():
                meta.add_edge(str(cu), str(cv), weight=w,
                              relation=f"{w} cross-community edges", confidence="AGGREGATED")
            if meta.number_of_nodes() <= 1:
                print("Single community - aggregated view not useful. Skipping graph.html.")
                return
            meta_communities = {cid: [str(cid)] for cid in communities}
            mc = {cid: len(members) for cid, members in communities.items()}
            to_html(meta, meta_communities, output_path,
                    community_labels=community_labels, member_counts=mc)
            return
        raise ValueError(
            f"Graph has {G.number_of_nodes()} nodes - too large for HTML viz "
            f"(limit: {limit}). Use --no-viz, raise GRAPHIFY_SF_VIZ_NODE_LIMIT, "
            f"or reduce input size."
        )

    node_community = _node_community_map(communities)
    degree = dict(G.degree())
    max_deg = max(degree.values(), default=1) or 1
    max_mc = (max(member_counts.values(), default=1) or 1) if member_counts else 1

    vis_nodes = []
    for node_id, data in G.nodes(data=True):
        cid = node_community.get(node_id, 0)
        color = COMMUNITY_COLORS[cid % len(COMMUNITY_COLORS)]
        label = sanitize_label(data.get("label", node_id))
        deg = degree.get(node_id, 1)
        if member_counts:
            mc = member_counts.get(cid, 1)
            size = 10 + 30 * (mc / max_mc)
            font_size = 12
        else:
            size = 10 + 30 * (deg / max_deg)
            font_size = 12 if deg >= max_deg * 0.15 else 0
        vis_nodes.append({
            "id": node_id,
            "label": label,
            "color": {"background": color, "border": color, "highlight": {"background": "#ffffff", "border": color}},
            "size": round(size, 1),
            "font": {"size": font_size, "color": "#ffffff"},
            "title": _html.escape(label),
            "community": cid,
            "community_name": sanitize_label((community_labels or {}).get(cid, f"Community {cid}")),
            "source_file": sanitize_label(str(data.get("source_file") or "")),
            "file_type": data.get("file_type", ""),
            "sf_type": data.get("sf_type", ""),
            "degree": deg,
        })

    vis_edges = []
    for u, v, data in G.edges(data=True):
        confidence = data.get("confidence", "EXTRACTED")
        relation = data.get("relation", "")
        true_src = data.get("_src", u)
        true_tgt = data.get("_tgt", v)
        vis_edges.append({
            "from": true_src,
            "to": true_tgt,
            "label": relation,
            "title": _html.escape(f"{relation} [{confidence}]"),
            "dashes": confidence != "EXTRACTED",
            "width": 2 if confidence == "EXTRACTED" else 1,
            "color": {"opacity": 0.7 if confidence == "EXTRACTED" else 0.35},
            "confidence": confidence,
        })

    legend_data = []
    for cid in sorted((community_labels or {}).keys()):
        color = COMMUNITY_COLORS[cid % len(COMMUNITY_COLORS)]
        lbl = _html.escape(sanitize_label((community_labels or {}).get(cid, f"Community {cid}")))
        n = member_counts.get(cid, len(communities.get(cid, []))) if member_counts else len(communities.get(cid, []))
        legend_data.append({"cid": cid, "color": color, "label": lbl, "count": n})

    def _js_safe(obj) -> str:
        return json.dumps(obj).replace("</", "<\\/")

    nodes_json = _js_safe(vis_nodes)
    edges_json = _js_safe(vis_edges)
    legend_json = _js_safe(legend_data)
    title = _html.escape(sanitize_label(str(output_path)))
    stats = f"{G.number_of_nodes()} nodes &middot; {G.number_of_edges()} edges &middot; {len(communities)} communities"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>graphify-sf - {title}</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
{_html_styles()}
</head>
<body>
<div id="graph"></div>
<div id="sidebar">
  <div id="search-wrap">
    <input id="search" type="text" placeholder="Search SF metadata..." autocomplete="off">
    <div id="search-results"></div>
  </div>
  <div id="info-panel">
    <h3>Node Info</h3>
    <div id="info-content"><span class="empty">Click a node to inspect it</span></div>
  </div>
  <div id="legend-wrap">
    <h3>Communities</h3>
    <div id="legend-controls">
      <label><input type="checkbox" id="select-all-cb" checked onchange="toggleAllCommunities(!this.checked)">Select All</label>
    </div>
    <div id="legend"></div>
  </div>
  <div id="stats">{stats}</div>
</div>
{_html_script(nodes_json, edges_json, legend_json)}
</body>
</html>"""

    Path(output_path).write_text(html, encoding="utf-8")  # nosec


generate_html = to_html


def to_obsidian(
    G: nx.Graph,
    communities: dict[int, list[str]],
    output_dir: str,
    community_labels: dict[int, str] | None = None,
    cohesion: dict[int, float] | None = None,
) -> int:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    node_community = _node_community_map(communities)

    def safe_name(label: str) -> str:
        cleaned = re.sub(r'[\\/*?:"<>|#^[\]]', "", label.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")).strip()
        cleaned = re.sub(r"\.(md|mdx|qmd|markdown)$", "", cleaned, flags=re.IGNORECASE)
        return cleaned or "unnamed"

    node_filename: dict[str, str] = {}
    seen_names: dict[str, int] = {}
    for node_id, data in G.nodes(data=True):
        base = safe_name(data.get("label", node_id))
        if base in seen_names:
            seen_names[base] += 1
            node_filename[node_id] = f"{base}_{seen_names[base]}"
        else:
            seen_names[base] = 0
            node_filename[node_id] = base

    def _dominant_confidence(node_id: str) -> str:
        confs = []
        for u, v, edata in G.edges(node_id, data=True):
            confs.append(edata.get("confidence", "EXTRACTED"))
        if not confs:
            return "EXTRACTED"
        return Counter(confs).most_common(1)[0][0]

    # SF file_type → Obsidian tag
    _FTYPE_TAG = {
        "apex": "sfmeta/apex",
        "trigger": "sfmeta/trigger",
        "flow": "sfmeta/flow",
        "automation": "sfmeta/automation",
        "object": "sfmeta/object",
        "field": "sfmeta/field",
        "lwc": "sfmeta/lwc",
        "aura": "sfmeta/aura",
        "visualforce": "sfmeta/visualforce",
        "layout": "sfmeta/layout",
        "profile": "sfmeta/security",
        "permset": "sfmeta/security",
        "config": "sfmeta/config",
    }

    for node_id, data in G.nodes(data=True):
        label = data.get("label", node_id)
        cid = node_community.get(node_id)
        community_name = (
            community_labels.get(cid, f"Community {cid}")
            if community_labels and cid is not None
            else f"Community {cid}"
        )

        ftype = data.get("file_type", "")
        ftype_tag = _FTYPE_TAG.get(ftype, f"sfmeta/{ftype}" if ftype else "sfmeta/unknown")
        dom_conf = _dominant_confidence(node_id)
        conf_tag = f"sfmeta/{dom_conf}"
        comm_tag = f"community/{_obsidian_tag(community_name)}"
        node_tags = [ftype_tag, conf_tag, comm_tag]

        lines: list[str] = []
        lines += [
            "---",
            f'source_file: "{_yaml_str(data.get("source_file", ""))}"',
            f'sf_type: "{_yaml_str(data.get("sf_type", ""))}"',
            f'file_type: "{_yaml_str(ftype)}"',
            f'community: "{_yaml_str(community_name)}"',
        ]
        if data.get("source_location"):
            lines.append(f'location: "{_yaml_str(str(data["source_location"]))}"')
        lines.append("tags:")
        for tag in node_tags:
            lines.append(f"  - {tag}")
        lines += ["---", "", f"# {label}", ""]

        neighbors = list(G.neighbors(node_id))
        if neighbors:
            lines.append("## Connections")
            for neighbor in sorted(neighbors, key=lambda n: G.nodes[n].get("label", n)):
                edata = edge_data(G, node_id, neighbor)
                neighbor_label = node_filename[neighbor]
                relation = edata.get("relation", "")
                confidence = edata.get("confidence", "EXTRACTED")
                lines.append(f"- [[{neighbor_label}]] - `{relation}` [{confidence}]")
            lines.append("")

        inline_tags = " ".join(f"#{t}" for t in node_tags)
        lines.append(inline_tags)

        fname = node_filename[node_id] + ".md"
        (out / fname).write_text("\n".join(lines), encoding="utf-8")  # nosec

    # Community overview notes
    inter_community_edges: dict[int, dict[int, int]] = {}
    for cid in communities:
        inter_community_edges[cid] = {}
    for u, v in G.edges():
        cu = node_community.get(u)
        cv = node_community.get(v)
        if cu is not None and cv is not None and cu != cv:
            inter_community_edges.setdefault(cu, {})
            inter_community_edges.setdefault(cv, {})
            inter_community_edges[cu][cv] = inter_community_edges[cu].get(cv, 0) + 1
            inter_community_edges[cv][cu] = inter_community_edges[cv].get(cu, 0) + 1

    community_notes_written = 0
    for cid, members in communities.items():
        community_name = (
            community_labels.get(cid, f"Community {cid}")
            if community_labels and cid is not None
            else f"Community {cid}"
        )
        n_members = len(members)
        coh_value = cohesion.get(cid) if cohesion else None

        lines = ["---", "type: community"]
        if coh_value is not None:
            lines.append(f"cohesion: {coh_value:.2f}")
        lines.append(f"members: {n_members}")
        lines.append("---")
        lines.append(f"\n# {community_name}\n")

        if coh_value is not None:
            cohesion_desc = (
                "tightly connected" if coh_value >= 0.7
                else "moderately connected" if coh_value >= 0.4
                else "loosely connected"
            )
            lines.append(f"**Cohesion:** {coh_value:.2f} - {cohesion_desc}")
        lines.append(f"**Members:** {n_members} nodes\n")

        lines.append("## Members")
        for node_id in sorted(members, key=lambda n: G.nodes[n].get("label", n)):
            data = G.nodes[node_id]
            node_label = node_filename[node_id]
            ftype = data.get("file_type", "")
            sf_type = data.get("sf_type", "")
            source = data.get("source_file", "")
            entry = f"- [[{node_label}]]"
            if sf_type:
                entry += f" ({sf_type})"
            if source:
                entry += f" - {source}"
            lines.append(entry)
        lines.append("")

        cross = inter_community_edges.get(cid, {})
        if cross:
            lines.append("## Connections to other communities")
            for other_cid, edge_count in sorted(cross.items(), key=lambda x: -x[1]):
                other_name = (
                    community_labels.get(other_cid, f"Community {other_cid}")
                    if community_labels and other_cid is not None
                    else f"Community {other_cid}"
                )
                other_safe = safe_name(other_name)
                lines.append(f"- {edge_count} edge{'s' if edge_count != 1 else ''} to [[_COMMUNITY_{other_safe}]]")
            lines.append("")

        community_safe = safe_name(community_name)
        fname = f"_COMMUNITY_{community_safe}.md"
        (out / fname).write_text("\n".join(lines), encoding="utf-8")  # nosec
        community_notes_written += 1

    # Write Obsidian graph config
    obsidian_dir = out / ".obsidian"
    obsidian_dir.mkdir(exist_ok=True)
    graph_config = {
        "colorGroups": [
            {
                "query": f"tag:#community/{label.replace(' ', '_')}",
                "color": {"a": 1, "rgb": int(COMMUNITY_COLORS[cid % len(COMMUNITY_COLORS)].lstrip('#'), 16)}
            }
            for cid, label in sorted((community_labels or {}).items())
        ]
    }
    (obsidian_dir / "graph.json").write_text(json.dumps(graph_config, indent=2), encoding="utf-8")  # nosec

    return G.number_of_nodes() + community_notes_written


def to_graphml(
    G: nx.Graph,
    communities: dict[int, list[str]],
    output_path: str,
) -> None:
    H = G.copy()
    node_community = _node_community_map(communities)
    for node_id in H.nodes():
        H.nodes[node_id]["community"] = node_community.get(node_id, -1)
    nx.write_graphml(H, output_path)


def to_wiki(
    G: nx.Graph,
    communities: dict[int, list[str]],
    output_dir: str,
    community_labels: dict[int, str] | None = None,
) -> int:
    """Export an agent-crawlable wiki: one markdown file per community + index.md.

    Returns the number of files written (community pages + index).
    """
    wiki_dir = Path(output_dir) / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)

    labels = community_labels or {}
    node_community = _node_community_map(communities)

    def _slug(text: str) -> str:
        s = text.lower()
        s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
        return s or "community"

    # ── Community pages ─────────────────────────────────────────────────────
    pages_written = 0
    index_rows: list[tuple[str, str, int]] = []  # (filename, label, node_count)

    for cid, node_ids in sorted(communities.items()):
        label = labels.get(cid, f"Community {cid}")
        filename = f"{cid:03d}-{_slug(label)}.md"

        lines: list[str] = [f"# {label}", ""]

        # Group nodes by sf_type
        by_type: dict[str, list[tuple[str, str, dict]]] = {}
        for nid in node_ids:
            data = G.nodes.get(nid, {})
            sf_type = data.get("sf_type", "Other")
            node_label = data.get("label", nid)
            by_type.setdefault(sf_type, []).append((nid, node_label, data))

        for sf_type in sorted(by_type):
            lines.append(f"## {sf_type}")
            lines.append("")
            for nid, node_label, data in sorted(by_type[sf_type], key=lambda x: x[1].lower()):
                source = data.get("source_file", "")
                loc = data.get("source_location") or ""
                source_tag = f" — `{source}`" + (f" {loc}" if loc else "") if source else ""
                lines.append(f"### {node_label}{source_tag}")
                lines.append("")

                # Top connections (cross-community first for discoverability)
                neighbors = sorted(
                    G.neighbors(nid),
                    key=lambda n: (node_community.get(n, -1) == cid, -G.degree(n)),
                )[:8]
                if neighbors:
                    for nb in neighbors:
                        edata = (
                            G.edges[nid, nb] if G.has_edge(nid, nb)
                            else G.edges[nb, nid] if G.has_edge(nb, nid)
                            else {}
                        )
                        rel = edata.get("relation", "related")
                        conf = edata.get("confidence", "")
                        conf_tag = f" `{conf}`" if conf else ""
                        nb_label = G.nodes[nb].get("label", nb)
                        nb_cid = node_community.get(nb, -1)
                        if nb_cid != cid:
                            nb_comm = labels.get(nb_cid, f"Community {nb_cid}")
                            lines.append(f"- **{rel}**{conf_tag} → {nb_label} *(in {nb_comm})*")
                        else:
                            lines.append(f"- **{rel}**{conf_tag} → {nb_label}")
                    lines.append("")

        page_path = wiki_dir / filename
        page_path.write_text("\n".join(lines), encoding="utf-8")
        pages_written += 1
        index_rows.append((filename, label, len(node_ids)))

    # ── index.md ────────────────────────────────────────────────────────────
    total_nodes = G.number_of_nodes()
    total_edges = G.number_of_edges()
    index_lines = [
        "# graphify-sf Wiki",
        "",
        f"**{total_nodes} nodes · {total_edges} edges · {len(communities)} communities**",
        "",
        "## Communities",
        "",
    ]
    for filename, label, count in index_rows:
        index_lines.append(f"- [{label}]({filename}) — {count} nodes")
    index_lines.append("")

    (wiki_dir / "index.md").write_text("\n".join(index_lines), encoding="utf-8")
    return pages_written + 1  # community pages + index


def push_to_neo4j(
    G,
    output_path: str,
    *,
    uri: str = "bolt://localhost:7687",
    user: str = "neo4j",
    password: str = "neo4j",
    database: str | None = None,
    batch_size: int = 500,
) -> dict:
    """Push graph nodes and edges directly to a running Neo4j instance.

    Requires: pip install graphify-sf[neo4j]  (installs the neo4j driver)

    Args:
        G: NetworkX graph.
        output_path: Also writes cypher.txt alongside the push (for audit).
        uri: Bolt URI (default: bolt://localhost:7687).
        user: Neo4j username (default: neo4j).
        password: Neo4j password.
        database: Target database name (None = default database).
        batch_size: Nodes/edges per transaction batch.

    Returns:
        {"nodes_merged": N, "edges_merged": N}
    """
    try:
        from neo4j import GraphDatabase
    except ImportError:
        raise ImportError(
            "neo4j driver not installed. "
            "Install with: pip install graphify-sf[neo4j]"
        )

    # Also write the cypher.txt audit file
    to_cypher(G, output_path)

    nodes_merged = 0
    edges_merged = 0

    driver = GraphDatabase.driver(uri, auth=(user, password))
    db_kwargs = {"database": database} if database else {}

    try:
        with driver.session(**db_kwargs) as session:
            # Merge nodes in batches
            node_batch = []
            for node_id, data in G.nodes(data=True):
                ftype = _cypher_label(
                    (data.get("sf_type", data.get("file_type", "unknown")) or "Entity").replace(" ", ""),
                    "SFEntity",
                )
                node_batch.append({
                    "id": _cypher_escape(node_id),
                    "label": _cypher_escape(data.get("label", node_id)),
                    "sf_type": data.get("sf_type", ""),
                    "file_type": data.get("file_type", ""),
                    "source_file": data.get("source_file", ""),
                    "community": data.get("community", -1),
                    "ftype": ftype,
                })
                if len(node_batch) >= batch_size:
                    session.run(
                        "UNWIND $batch AS n "
                        "MERGE (x {id: n.id}) "
                        "SET x.label = n.label, x.sf_type = n.sf_type, "
                        "    x.file_type = n.file_type, x.source_file = n.source_file, "
                        "    x.community = n.community",
                        batch=node_batch,
                    )
                    nodes_merged += len(node_batch)
                    node_batch = []
            if node_batch:
                session.run(
                    "UNWIND $batch AS n "
                    "MERGE (x {id: n.id}) "
                    "SET x.label = n.label, x.sf_type = n.sf_type, "
                    "    x.file_type = n.file_type, x.source_file = n.source_file, "
                    "    x.community = n.community",
                    batch=node_batch,
                )
                nodes_merged += len(node_batch)

            # Merge edges in batches
            edge_batch = []
            for u, v, data in G.edges(data=True):
                rel = _cypher_label(
                    (data.get("relation", "RELATES_TO") or "RELATES_TO").upper(),
                    "RELATES_TO",
                )
                edge_batch.append({
                    "source": _cypher_escape(u),
                    "target": _cypher_escape(v),
                    "relation": rel,
                    "confidence": data.get("confidence", "EXTRACTED"),
                })
                if len(edge_batch) >= batch_size:
                    session.run(
                        "UNWIND $batch AS e "
                        "MATCH (a {id: e.source}), (b {id: e.target}) "
                        "MERGE (a)-[r:RELATES_TO {relation: e.relation}]->(b) "
                        "SET r.confidence = e.confidence",
                        batch=edge_batch,
                    )
                    edges_merged += len(edge_batch)
                    edge_batch = []
            if edge_batch:
                session.run(
                    "UNWIND $batch AS e "
                    "MATCH (a {id: e.source}), (b {id: e.target}) "
                    "MERGE (a)-[r:RELATES_TO {relation: e.relation}]->(b) "
                    "SET r.confidence = e.confidence",
                    batch=edge_batch,
                )
                edges_merged += len(edge_batch)
    finally:
        driver.close()

    return {"nodes_merged": nodes_merged, "edges_merged": edges_merged}


def to_svg(
    G,
    communities: dict,
    output_path: str,
    community_labels: dict | None = None,
    figsize: tuple = (24, 18),
    dpi: int = 150,
) -> None:
    """Export the graph as an SVG image using matplotlib + networkx layout.

    Requires: pip install graphify-sf[svg]  (installs matplotlib)

    Args:
        G: NetworkX graph.
        communities: Community id → list of node ids.
        output_path: Destination .svg (or .png) path.
        community_labels: Optional dict mapping community id → label string.
        figsize: Matplotlib figure size in inches.
        dpi: Resolution for raster output (ignored for SVG).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.patches as mpatches
        import matplotlib.pyplot as plt
    except ImportError:
        raise ImportError(
            "matplotlib not installed. Install with: pip install graphify-sf[svg]"
        )

    node_community = _node_community_map(communities)

    # Node colors by community
    node_colors = [
        COMMUNITY_COLORS[node_community.get(nid, 0) % len(COMMUNITY_COLORS)]
        for nid in G.nodes()
    ]

    # Node sizes by degree (min 30, max 500)
    degrees = dict(G.degree())
    max_deg = max(degrees.values(), default=1) or 1
    node_sizes = [
        30 + 470 * (degrees.get(nid, 0) / max_deg)
        for nid in G.nodes()
    ]

    # Layout
    n = G.number_of_nodes()
    if n <= 200:
        pos = nx.spring_layout(G, seed=42, k=2.5 / (n ** 0.5) if n > 1 else 1)
    else:
        pos = nx.kamada_kawai_layout(G) if n <= 500 else nx.random_layout(G, seed=42)

    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor("#0f0f1a")
    ax.set_facecolor("#0f0f1a")

    # Draw edges
    nx.draw_networkx_edges(
        G, pos, ax=ax,
        alpha=0.15, edge_color="#4a4a8a", width=0.5,
    )

    # Draw nodes
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color=node_colors,
        node_size=node_sizes,
        alpha=0.85,
    )

    # Labels for high-degree nodes only
    threshold = max_deg * 0.15
    labels = {
        nid: G.nodes[nid].get("label", nid)
        for nid in G.nodes()
        if degrees.get(nid, 0) >= threshold
    }
    nx.draw_networkx_labels(
        G, pos, labels=labels, ax=ax,
        font_size=6, font_color="#e0e0e0",
    )

    # Legend
    legend_patches = []
    for cid in sorted((community_labels or {}).keys())[:10]:
        color = COMMUNITY_COLORS[cid % len(COMMUNITY_COLORS)]
        lbl = (community_labels or {}).get(cid, f"Community {cid}")
        legend_patches.append(mpatches.Patch(color=color, label=lbl[:30]))
    if legend_patches:
        ax.legend(
            handles=legend_patches,
            loc="upper left",
            fontsize=7,
            facecolor="#1a1a2e",
            edgecolor="#2a2a4e",
            labelcolor="#e0e0e0",
        )

    stats_text = f"{G.number_of_nodes()} nodes · {G.number_of_edges()} edges · {len(communities)} communities"
    ax.set_title(stats_text, color="#aaaaaa", fontsize=9, pad=8)
    ax.axis("off")

    plt.tight_layout()
    plt.savefig(output_path, format="svg" if str(output_path).endswith(".svg") else "png",
                dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def to_callflow_html(
    G,
    output_path: str,
    *,
    max_nodes: int = 60,
    max_edges: int = 120,
) -> int:
    """Generate a Mermaid-based call-flow HTML diagram for Salesforce metadata.

    Shows the dependency chain: triggers/flows → objects, apex → apex calls,
    lwc → apex controllers.  Focuses on high-degree nodes and cross-type edges
    for readability.

    Args:
        G: NetworkX graph.
        output_path: Destination .html path.
        max_nodes: Cap on nodes shown (highest-degree first).
        max_edges: Cap on edges shown.

    Returns:
        Number of nodes included in the diagram.
    """
    import re as _re

    # Priority relations for the call-flow view
    _CALLFLOW_RELATIONS = {
        "triggers", "calls", "queries", "dml",
        "references", "contains", "extends", "implements",
    }

    # Pick the top max_nodes nodes by degree (skip pure file/bundle nodes)
    degrees = dict(G.degree())
    sorted_nodes = sorted(G.nodes(), key=lambda n: degrees.get(n, 0), reverse=True)
    included = set()
    for nid in sorted_nodes:
        data = G.nodes[nid]
        sf_type = data.get("sf_type", "") or ""
        if sf_type:
            included.add(nid)
        if len(included) >= max_nodes:
            break
    # If not enough typed nodes, fill with highest-degree remaining
    for nid in sorted_nodes:
        if len(included) >= max_nodes:
            break
        included.add(nid)

    # Build edge list (callflow-relevant edges between included nodes)
    edges = []
    for u, v, data in G.edges(data=True):
        if u not in included or v not in included:
            continue
        rel = data.get("relation", "") or ""
        if not rel or rel in _CALLFLOW_RELATIONS:
            edges.append((u, v, rel, data.get("confidence", "EXTRACTED")))
    edges = edges[:max_edges]

    # Mermaid node ID: strip non-alphanum
    def _mid(nid: str) -> str:
        return _re.sub(r"[^a-zA-Z0-9_]", "_", nid)[:40]

    # Mermaid label: truncate long labels
    def _mlabel(nid: str) -> str:
        data = G.nodes[nid]
        label = data.get("label", nid)
        sf_type = data.get("sf_type", "") or data.get("file_type", "") or ""
        short = label[:28] + ".." if len(label) > 30 else label
        return f"{short}\\n[{sf_type}]" if sf_type else short

    # Mermaid arrow style by relation
    def _arrow(rel: str, conf: str) -> str:
        dashed = conf != "EXTRACTED"
        if rel in ("triggers", "dml"):
            return "-.->" if dashed else "==>"
        if rel in ("calls",):
            return "-.->" if dashed else "-->"
        if rel in ("queries",):
            return "-.->|query|" if dashed else "-->|query|"
        if rel in ("contains",):
            return "-.->" if dashed else "---"
        return "-.->" if dashed else "-->"

    # Build Mermaid diagram
    lines = ["flowchart LR"]

    # Node definitions with subgraph by sf_type
    by_type: dict[str, list[str]] = {}
    for nid in included:
        sf_type = G.nodes[nid].get("sf_type", "") or G.nodes[nid].get("file_type", "") or "Other"
        by_type.setdefault(sf_type, []).append(nid)

    _TYPE_STYLE = {
        "ApexClass":   "fill:#4E79A7,color:#fff",
        "ApexTrigger": "fill:#E15759,color:#fff",
        "ApexMethod":  "fill:#76B7B2,color:#fff",
        "Flow":        "fill:#F28E2B,color:#fff",
        "CustomObject":"fill:#59A14F,color:#fff",
        "CustomField": "fill:#B07AA1,color:#fff",
        "LWCBundle":   "fill:#EDC948,color:#000",
        "AuraBundle":  "fill:#FF9DA7,color:#000",
        "Profile":     "fill:#9C755F,color:#fff",
        "PermissionSet":"fill:#BAB0AC,color:#000",
        "Layout":      "fill:#1f77b4,color:#fff",
    }

    for sf_type, nids in sorted(by_type.items()):
        sg_id = _re.sub(r"[^a-zA-Z0-9]", "", sf_type)
        lines.append(f"  subgraph {sg_id}[{sf_type}]")
        for nid in nids:
            mid = _mid(nid)
            mlabel = _mlabel(nid)
            lines.append(f"    {mid}[\"{mlabel}\"]")
        lines.append("  end")

    # Style definitions
    for sf_type, style in _TYPE_STYLE.items():
        sg_id = _re.sub(r"[^a-zA-Z0-9]", "", sf_type)
        lines.append(f"  style {sg_id} {style.replace(',', ';')}")

    # Edges
    for u, v, rel, conf in edges:
        arrow = _arrow(rel, conf)
        u_mid = _mid(u)
        v_mid = _mid(v)
        if rel and "|" not in arrow:
            lines.append(f"  {u_mid} {arrow}|{rel}| {v_mid}")
        else:
            lines.append(f"  {u_mid} {arrow} {v_mid}")

    mermaid_src = "\n".join(lines)

    n_nodes = len(included)
    n_edges_shown = len(edges)
    title = f"Call Flow — {n_nodes} nodes · {n_edges_shown} edges"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>graphify-sf Call Flow</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f0f1a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 20px; }}
  h1 {{ font-size: 16px; color: #aaa; margin-bottom: 16px; font-weight: 400; }}
  #diagram {{ background: #1a1a2e; border-radius: 8px; padding: 20px; overflow: auto; }}
  .mermaid {{ background: transparent; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div id="diagram">
<div class="mermaid">
{mermaid_src}
</div>
</div>
<script>
mermaid.initialize({{
  startOnLoad: true,
  theme: 'dark',
  flowchart: {{ curve: 'basis', padding: 20 }},
  themeVariables: {{
    primaryColor: '#1a1a2e',
    primaryTextColor: '#e0e0e0',
    primaryBorderColor: '#3a3a5e',
    lineColor: '#6a6a9e',
    secondaryColor: '#16213e',
    tertiaryColor: '#0f3460',
  }},
}});
</script>
</body>
</html>"""

    Path(output_path).write_text(html, encoding="utf-8")
    return n_nodes


def to_tree_html(
    G,
    communities: dict,
    output_path: str,
    community_labels: dict | None = None,
) -> None:
    """Generate a D3 v7 collapsible tree HTML page organized by community.

    The tree root is "graphify-sf", with one branch per community, and each
    node's metadata shown in a tooltip on hover.

    Args:
        G: NetworkX graph.
        communities: Community id → list of node ids.
        output_path: Destination .html path.
        community_labels: Optional dict mapping community id → label string.
    """
    import json as _json

    labels = community_labels or {}
    degrees = dict(G.degree())

    # Build tree structure: root → community → nodes (sorted by degree desc)
    tree_data = {
        "name": "graphify-sf",
        "children": [],
    }

    for cid, node_ids in sorted(communities.items()):
        comm_label = labels.get(cid, f"Community {cid}")
        sorted_members = sorted(node_ids, key=lambda n: degrees.get(n, 0), reverse=True)
        children = []
        for nid in sorted_members:
            data = G.nodes.get(nid, {})
            node_label = data.get("label", nid)
            sf_type = data.get("sf_type", "") or data.get("file_type", "") or ""
            source = data.get("source_file", "") or ""
            deg = degrees.get(nid, 0)
            children.append({
                "name": node_label[:40],
                "sf_type": sf_type,
                "source": source,
                "degree": deg,
            })
        tree_data["children"].append({
            "name": comm_label,
            "community_id": cid,
            "children": children,
        })

    tree_json = _json.dumps(tree_data, ensure_ascii=False)
    total_nodes = G.number_of_nodes()
    total_edges = G.number_of_edges()
    n_communities = len(communities)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>graphify-sf Tree</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f0f1a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; overflow: hidden; }}
  #stats {{ padding: 10px 16px; font-size: 12px; color: #666; border-bottom: 1px solid #1a1a2e; }}
  #tree-container {{ width: 100vw; height: calc(100vh - 36px); overflow: hidden; }}
  .node circle {{ stroke-width: 1.5; cursor: pointer; }}
  .node text {{ font-size: 11px; fill: #ccc; pointer-events: none; }}
  .link {{ fill: none; stroke: #2a2a4e; stroke-width: 1.5; }}
  .link:hover {{ stroke: #4E79A7; }}
  .tooltip {{
    position: absolute; background: #1a1a2e; border: 1px solid #3a3a5e;
    color: #ccc; padding: 8px 12px; border-radius: 6px; font-size: 12px;
    pointer-events: none; opacity: 0; transition: opacity 0.15s;
    max-width: 280px; line-height: 1.5;
  }}
</style>
</head>
<body>
<div id="stats">{total_nodes} nodes &middot; {total_edges} edges &middot; {n_communities} communities &nbsp;|&nbsp; Click nodes to expand/collapse</div>
<div id="tree-container"></div>
<div class="tooltip" id="tooltip"></div>
<script>
const DATA = {tree_json};

const COLORS = ["#4E79A7","#F28E2B","#E15759","#76B7B2","#59A14F","#EDC948","#B07AA1","#FF9DA7","#9C755F","#BAB0AC"];

const container = document.getElementById('tree-container');
const tooltip = document.getElementById('tooltip');
const W = container.clientWidth;
const H = container.clientHeight;

const svg = d3.select('#tree-container').append('svg')
  .attr('width', W).attr('height', H);
const g = svg.append('g').attr('transform', `translate(120,${{H/2}})`);

svg.call(d3.zoom().scaleExtent([0.1, 4]).on('zoom', e => {{
  g.attr('transform', e.transform);
}}));

const treeLayout = d3.tree().size([H - 40, W - 240]);

const root = d3.hierarchy(DATA);
root.x0 = H / 2;
root.y0 = 0;

// Collapse all community children initially
root.children && root.children.forEach(d => {{
  d._children = d.children;
  d.children = null;
}});

let i = 0;
function update(source) {{
  const treeData = treeLayout(root);
  const nodes = treeData.descendants();
  const links = treeData.links();

  nodes.forEach(d => {{ d.y = d.depth * 220; }});

  const node = g.selectAll('g.node').data(nodes, d => d.id || (d.id = ++i));

  const nodeEnter = node.enter().append('g').attr('class', 'node')
    .attr('transform', d => `translate(${{source.y0}},${{source.x0}})`)
    .on('click', (_, d) => {{
      if (d.children) {{ d._children = d.children; d.children = null; }}
      else {{ d.children = d._children; d._children = null; }}
      update(d);
    }})
    .on('mouseover', (event, d) => {{
      if (!d.data.sf_type) return;
      tooltip.style.opacity = 1;
      tooltip.innerHTML = `<b>${{d.data.name}}</b><br>Type: ${{d.data.sf_type}}<br>Degree: ${{d.data.degree}}<br>${{d.data.source ? 'Source: '+d.data.source : ''}}`;
    }})
    .on('mousemove', event => {{
      tooltip.style.left = (event.pageX + 12) + 'px';
      tooltip.style.top = (event.pageY - 28) + 'px';
    }})
    .on('mouseout', () => {{ tooltip.style.opacity = 0; }});

  nodeEnter.append('circle')
    .attr('r', 1e-6)
    .style('fill', d => {{
      if (d.depth === 0) return '#888';
      if (d.depth === 1) return COLORS[(d.data.community_id || 0) % COLORS.length];
      return d._children ? '#555' : '#222';
    }})
    .style('stroke', d => {{
      if (d.depth === 0) return '#888';
      if (d.depth === 1) return COLORS[(d.data.community_id || 0) % COLORS.length];
      return '#4E79A7';
    }});

  nodeEnter.append('text')
    .attr('dy', '.35em')
    .attr('x', d => d.children || d._children ? -10 : 10)
    .attr('text-anchor', d => d.children || d._children ? 'end' : 'start')
    .text(d => d.data.name.length > 24 ? d.data.name.slice(0, 22) + '..' : d.data.name);

  const nodeUpdate = nodeEnter.merge(node);
  nodeUpdate.transition().duration(300)
    .attr('transform', d => `translate(${{d.y}},${{d.x}})`);
  nodeUpdate.select('circle').transition().duration(300)
    .attr('r', d => d.depth === 0 ? 8 : d.depth === 1 ? 6 : 4)
    .style('fill', d => {{
      if (d.depth === 0) return '#888';
      if (d.depth === 1) return COLORS[(d.data.community_id || 0) % COLORS.length];
      return d._children ? '#555' : '#1a1a2e';
    }});

  node.exit().transition().duration(300)
    .attr('transform', d => `translate(${{source.y}},${{source.x}})`)
    .remove()
    .select('circle').attr('r', 1e-6);

  const link = g.selectAll('path.link').data(links, d => d.target.id);
  const linkEnter = link.enter().insert('path', 'g').attr('class', 'link')
    .attr('d', d => {{
      const o = {{x: source.x0, y: source.y0}};
      return d3.linkHorizontal(){{x: d => d.y, y: d => d.x}}({{source: o, target: o}});
    }});
  linkEnter.merge(link).transition().duration(300)
    .attr('d', d3.linkHorizontal().x(d => d.y).y(d => d.x));
  link.exit().transition().duration(300)
    .attr('d', d => {{
      const o = {{x: source.x, y: source.y}};
      return d3.linkHorizontal(){{x: d => d.y, y: d => d.x}}({{source: o, target: o}});
    }}).remove();

  nodes.forEach(d => {{ d.x0 = d.x; d.y0 = d.y; }});
}}

update(root);
</script>
</body>
</html>"""

    Path(output_path).write_text(html, encoding="utf-8")
