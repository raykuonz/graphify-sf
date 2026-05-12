# graphify_sf/serve.py
"""Minimal MCP stdio server for graphify-sf.

Implements JSON-RPC 2.0 over stdin/stdout per the MCP spec.
Tools exposed:
  - graph_stats        — node/edge/community counts
  - query              — BFS/DFS traversal for a question
  - get_node           — details for a single named node
  - get_neighbors      — connections of a node (up to N, optional relation filter)
  - shortest_path      — shortest path between two nodes
  - god_nodes          — highest-degree nodes (most central)
  - list_communities   — community names and member counts
  - get_community      — all nodes belonging to a specific community

Resources exposed:
  - graphify-sf://report       — GRAPH_REPORT.md contents
  - graphify-sf://stats        — graph statistics JSON
  - graphify-sf://god-nodes    — top god nodes JSON
  - graphify-sf://surprises    — surprising connections JSON
  - graphify-sf://audit        — edge confidence summary
  - graphify-sf://questions    — suggested exploration questions

Install with: pip install graphify-sf[mcp]
(Uses the `mcp` package when available; falls back to raw JSON-RPC otherwise.)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Tool registry ─────────────────────────────────────────────────────────────

_TOOLS = [
    {
        "name": "graph_stats",
        "description": "Return high-level statistics about the loaded knowledge graph.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "query",
        "description": (
            "BFS or DFS traversal of the graph for a natural-language question. "
            "Returns nodes and connections related to the query."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to explore"},
                "mode": {
                    "type": "string",
                    "enum": ["bfs", "dfs"],
                    "description": "Traversal mode (default: bfs)",
                },
                "budget": {
                    "type": "integer",
                    "description": "Max tokens in response (default: 2000)",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "get_node",
        "description": "Get detailed information about a single metadata node by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Node label / metadata name"},
            },
            "required": ["label"],
        },
    },
    {
        "name": "get_neighbors",
        "description": "Get the neighbors (connected nodes) of a metadata node.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Node label / metadata name"},
                "limit": {
                    "type": "integer",
                    "description": "Max neighbors to return (default: 20)",
                },
                "relation_filter": {
                    "type": "string",
                    "description": (
                        "Only return neighbors connected by this relation type "
                        "(e.g. 'triggers', 'queries', 'calls', 'contains'). "
                        "Omit to return all relations."
                    ),
                },
            },
            "required": ["label"],
        },
    },
    {
        "name": "shortest_path",
        "description": "Find the shortest path between two metadata nodes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source node label"},
                "target": {"type": "string", "description": "Target node label"},
            },
            "required": ["source", "target"],
        },
    },
    {
        "name": "god_nodes",
        "description": "Return the highest-degree nodes — the most central metadata in the org.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "How many god nodes to return (default: 10)",
                },
            },
        },
    },
    {
        "name": "list_communities",
        "description": "List all detected communities with their labels and member counts.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_community",
        "description": "Get all nodes belonging to a specific community (by id or label).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "community_id": {
                    "type": "integer",
                    "description": "Community ID (integer)",
                },
                "label": {
                    "type": "string",
                    "description": "Community label (fuzzy matched if community_id not given)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max members to return (default: 50)",
                },
            },
        },
    },
]

# ── MCP Resources ──────────────────────────────────────────────────────────────

_RESOURCES = [
    {
        "uri": "graphify-sf://report",
        "name": "GRAPH_REPORT.md",
        "description": "Plain-language Salesforce metadata graph report (god nodes, surprising connections, suggested questions)",
        "mimeType": "text/markdown",
    },
    {
        "uri": "graphify-sf://stats",
        "name": "Graph Statistics",
        "description": "Node count, edge count, community count, and type distribution",
        "mimeType": "application/json",
    },
    {
        "uri": "graphify-sf://god-nodes",
        "name": "God Nodes",
        "description": "Top 20 highest-degree metadata nodes — the core abstractions of the org",
        "mimeType": "application/json",
    },
    {
        "uri": "graphify-sf://surprises",
        "name": "Surprising Connections",
        "description": "Cross-community edges — unexpected metadata dependencies",
        "mimeType": "application/json",
    },
    {
        "uri": "graphify-sf://audit",
        "name": "Edge Confidence Audit",
        "description": "Breakdown of EXTRACTED vs INFERRED vs AMBIGUOUS edges",
        "mimeType": "application/json",
    },
    {
        "uri": "graphify-sf://questions",
        "name": "Suggested Questions",
        "description": "Questions this graph is uniquely positioned to answer",
        "mimeType": "application/json",
    },
]


# ── Graph loading ─────────────────────────────────────────────────────────────

_G = None
_communities: dict = {}
_community_labels: dict = {}
_graph_path: str = ""


def _ensure_graph(graph_path: str) -> None:
    global _G, _communities, _community_labels, _graph_path
    if _G is not None and graph_path == _graph_path:
        return
    import json as _json

    from graphify_sf.__main__ import _load_graph_from_json

    gp = Path(graph_path)
    _G, _ = _load_graph_from_json(gp)
    # Re-derive communities from node attribute
    _communities.clear()
    for nid, data in _G.nodes(data=True):
        cid = data.get("community")
        if cid is not None:
            _communities.setdefault(int(cid), []).append(nid)
    if not _communities:
        from graphify_sf.cluster import cluster

        _communities.update(cluster(_G))
    # Load labels sidecar
    labels_path = gp.parent / ".graphify_sf_labels.json"
    if labels_path.exists():
        try:
            _community_labels = {int(k): v for k, v in _json.loads(labels_path.read_text()).items()}
        except Exception:
            _community_labels = {}
    _graph_path = graph_path


def _score_nodes(question: str) -> list[tuple[float, str]]:
    """Score graph nodes against a question string.

    Exact label match receives a +100 bonus over token-overlap scoring,
    ensuring that ``query "AccountTrigger"`` always starts from that node
    rather than one that merely contains the substring.
    """
    tokens = question.lower().split()
    scores: list[tuple[float, str]] = []
    for nid, data in _G.nodes(data=True):
        label = data.get("label", nid)
        label_lower = label.lower()
        # Exact match bonus
        if label_lower == question.lower():
            scores.append((100.0 + len(tokens), nid))
            continue
        score = sum(1 for t in tokens if t in label_lower)
        if score > 0:
            scores.append((float(score), nid))
    return scores


def _find_node(label: str):
    """Find the best-matching node for a label string."""
    q = label.lower()
    # Exact match first
    for nid, data in _G.nodes(data=True):
        if data.get("label", nid).lower() == q:
            return nid
    # Prefix / substring fallback
    candidates = []
    for nid, data in _G.nodes(data=True):
        lbl = data.get("label", nid).lower()
        if q in lbl:
            candidates.append((len(lbl), nid))
    if candidates:
        return min(candidates, key=lambda x: x[0])[1]
    return None


# ── Tool handlers ─────────────────────────────────────────────────────────────


def _tool_graph_stats(args: dict) -> dict:
    from collections import Counter

    sf_types = Counter(d.get("sf_type", "") for _, d in _G.nodes(data=True) if d.get("sf_type"))
    return {
        "nodes": _G.number_of_nodes(),
        "edges": _G.number_of_edges(),
        "communities": len(_communities),
        "community_labels": {str(k): v for k, v in _community_labels.items()},
        "top_sf_types": dict(sf_types.most_common(10)),
    }


def _tool_query(args: dict) -> dict:
    from collections import deque

    question = args["question"]
    use_dfs = args.get("mode", "bfs") == "dfs"
    budget = int(args.get("budget", 2000))

    scores = _score_nodes(question)
    if not scores:
        return {"found": False, "message": f"No nodes matching: {question}", "nodes": []}

    scores.sort(reverse=True)
    top_nid = scores[0][1]

    visited: set = set()
    result_nodes = []
    queue: deque = deque([(top_nid, 0)])
    char_budget = budget * 4

    chars_used = 0
    while queue and chars_used < char_budget:
        nid, depth = queue.popleft() if not use_dfs else queue.pop()
        if nid in visited:
            continue
        visited.add(nid)
        data = _G.nodes[nid]
        entry = {
            "id": nid,
            "label": data.get("label", nid),
            "sf_type": data.get("sf_type", ""),
            "file_type": data.get("file_type", ""),
            "source_file": data.get("source_file", ""),
            "community": data.get("community"),
            "depth": depth,
        }
        result_nodes.append(entry)
        chars_used += len(str(entry))
        if depth < 2:
            for nb in sorted(_G.neighbors(nid), key=lambda n: _G.degree(n), reverse=True)[:5]:
                queue.append((nb, depth + 1))

    return {
        "found": True,
        "question": question,
        "start_node": _G.nodes[top_nid].get("label", top_nid),
        "nodes": result_nodes,
    }


def _tool_get_node(args: dict) -> dict:
    label = args["label"]
    nid = _find_node(label)
    if nid is None:
        return {"found": False, "message": f"No node matching '{label}'"}
    data = _G.nodes[nid]
    from graphify_sf.build import edge_data

    neighbors = []
    for nb in sorted(_G.neighbors(nid), key=lambda n: _G.degree(n), reverse=True)[:20]:
        edata = edge_data(_G, nid, nb)
        neighbors.append(
            {
                "id": nb,
                "label": _G.nodes[nb].get("label", nb),
                "relation": edata.get("relation", ""),
                "confidence": edata.get("confidence", ""),
            }
        )
    return {
        "found": True,
        "id": nid,
        "label": data.get("label", nid),
        "sf_type": data.get("sf_type", ""),
        "file_type": data.get("file_type", ""),
        "source_file": data.get("source_file", ""),
        "source_location": data.get("source_location", ""),
        "community": data.get("community"),
        "community_label": _community_labels.get(data.get("community"), ""),
        "degree": _G.degree(nid),
        "neighbors": neighbors,
    }


def _tool_get_neighbors(args: dict) -> dict:
    label = args["label"]
    limit = int(args.get("limit", 20))
    relation_filter = args.get("relation_filter", "").strip().lower() or None
    nid = _find_node(label)
    if nid is None:
        return {"found": False, "message": f"No node matching '{label}'"}
    from graphify_sf.build import edge_data

    neighbors = []
    for nb in sorted(_G.neighbors(nid), key=lambda n: _G.degree(n), reverse=True):
        if len(neighbors) >= limit:
            break
        edata = edge_data(_G, nid, nb)
        rel = edata.get("relation", "")
        if relation_filter and rel.lower() != relation_filter:
            continue
        neighbors.append(
            {
                "id": nb,
                "label": _G.nodes[nb].get("label", nb),
                "sf_type": _G.nodes[nb].get("sf_type", ""),
                "relation": rel,
                "confidence": edata.get("confidence", ""),
            }
        )
    return {
        "found": True,
        "node": _G.nodes[nid].get("label", nid),
        "neighbor_count": _G.degree(nid),
        "relation_filter": relation_filter,
        "neighbors": neighbors,
    }


def _tool_shortest_path(args: dict) -> dict:
    import networkx as nx

    from graphify_sf.build import edge_data

    src_nid = _find_node(args["source"])
    tgt_nid = _find_node(args["target"])
    if src_nid is None:
        return {"found": False, "message": f"Source node not found: {args['source']}"}
    if tgt_nid is None:
        return {"found": False, "message": f"Target node not found: {args['target']}"}
    try:
        path_nodes = nx.shortest_path(_G, src_nid, tgt_nid)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return {"found": False, "message": f"No path between '{args['source']}' and '{args['target']}'"}
    hops = []
    for i in range(len(path_nodes) - 1):
        u, v = path_nodes[i], path_nodes[i + 1]
        edata = edge_data(_G, u, v)
        hops.append(
            {
                "from": _G.nodes[u].get("label", u),
                "to": _G.nodes[v].get("label", v),
                "relation": edata.get("relation", ""),
                "confidence": edata.get("confidence", ""),
            }
        )
    return {
        "found": True,
        "source": _G.nodes[src_nid].get("label", src_nid),
        "target": _G.nodes[tgt_nid].get("label", tgt_nid),
        "hop_count": len(hops),
        "path": hops,
    }


def _tool_god_nodes(args: dict) -> dict:
    from graphify_sf.analyze import god_nodes as _god_nodes

    limit = int(args.get("limit", 10))
    gods = _god_nodes(_G)
    result = []
    for nid, deg in gods[:limit]:
        data = _G.nodes[nid]
        result.append(
            {
                "label": data.get("label", nid),
                "sf_type": data.get("sf_type", ""),
                "degree": deg,
                "community": data.get("community"),
                "community_label": _community_labels.get(data.get("community"), ""),
            }
        )
    return {"god_nodes": result}


def _tool_list_communities(args: dict) -> dict:
    result = []
    for cid, members in sorted(_communities.items()):
        result.append(
            {
                "id": cid,
                "label": _community_labels.get(cid, f"Community {cid}"),
                "member_count": len(members),
            }
        )
    return {"communities": result}


def _tool_get_community(args: dict) -> dict:
    limit = int(args.get("limit", 50))
    cid_arg = args.get("community_id")
    label_arg = (args.get("label") or "").strip().lower()

    # Resolve community id
    if cid_arg is not None:
        cid = int(cid_arg)
    elif label_arg:
        # Fuzzy match label
        best = None
        best_score = -1
        for c, lbl in _community_labels.items():
            if lbl.lower() == label_arg:
                best = c
                break
            if label_arg in lbl.lower():
                if len(lbl) > best_score:
                    best_score = len(lbl)
                    best = c
        cid = best
    else:
        return {"found": False, "message": "Provide community_id or label"}

    if cid not in _communities:
        return {"found": False, "message": f"Community {cid} not found"}

    members_raw = _communities[cid][:limit]
    members = []
    for nid in sorted(members_raw, key=lambda n: _G.degree(n), reverse=True):
        data = _G.nodes.get(nid, {})
        members.append(
            {
                "id": nid,
                "label": data.get("label", nid),
                "sf_type": data.get("sf_type", ""),
                "degree": _G.degree(nid),
            }
        )
    return {
        "found": True,
        "community_id": cid,
        "label": _community_labels.get(cid, f"Community {cid}"),
        "total_members": len(_communities[cid]),
        "members": members,
    }


_TOOL_HANDLERS = {
    "graph_stats": _tool_graph_stats,
    "query": _tool_query,
    "get_node": _tool_get_node,
    "get_neighbors": _tool_get_neighbors,
    "shortest_path": _tool_shortest_path,
    "god_nodes": _tool_god_nodes,
    "list_communities": _tool_list_communities,
    "get_community": _tool_get_community,
}


# ── Resource read handlers ────────────────────────────────────────────────────


def _read_resource(uri: str, graph_path: str) -> str:
    """Return the text content for an MCP resource URI."""
    gp = Path(graph_path)
    _ensure_graph(graph_path)

    if uri == "graphify-sf://report":
        report_path = gp.parent / "GRAPH_REPORT.md"
        if report_path.exists():
            return report_path.read_text(encoding="utf-8")
        return "_No GRAPH_REPORT.md found. Run graphify-sf to build the graph._"

    if uri == "graphify-sf://stats":
        return json.dumps(_tool_graph_stats({}), indent=2)

    if uri == "graphify-sf://god-nodes":
        return json.dumps(_tool_god_nodes({"limit": 20}), indent=2)

    if uri == "graphify-sf://surprises":
        from graphify_sf.analyze import surprising_connections

        surprises = surprising_connections(_G, _communities)
        return json.dumps({"surprising_connections": surprises}, indent=2)

    if uri == "graphify-sf://audit":
        from collections import Counter

        confidences = Counter(d.get("confidence", "EXTRACTED") or "EXTRACTED" for _, _, d in _G.edges(data=True))
        total = sum(confidences.values()) or 1
        return json.dumps(
            {
                "total_edges": total,
                "breakdown": {k: {"count": v, "pct": round(v / total * 100)} for k, v in confidences.items()},
            },
            indent=2,
        )

    if uri == "graphify-sf://questions":
        from graphify_sf.analyze import suggest_questions

        questions = suggest_questions(_G, _communities, _community_labels)
        return json.dumps({"suggested_questions": questions}, indent=2)

    return f"Unknown resource: {uri}"


# ── JSON-RPC helpers ──────────────────────────────────────────────────────────


def _send(obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _ok(req_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


# ── Blank-line stdin filter ───────────────────────────────────────────────────


def _filtered_stdin():
    """Yield non-empty lines from stdin.

    Some MCP clients (Claude Desktop, certain shell pipelines) send blank lines
    between JSON messages.  These cause ``json.loads("")`` to raise a parse error.
    Filtering them here keeps the main loop clean.
    """
    for line in sys.stdin:
        stripped = line.strip()
        if stripped:
            yield stripped


# ── MCP protocol handlers ─────────────────────────────────────────────────────


def _handle(msg: dict, graph_path: str) -> dict | None:
    req_id = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params") or {}

    # Notifications — no response
    if req_id is None:
        return None

    if method == "initialize":
        return _ok(
            req_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "graphify-sf", "version": "0.1"},
            },
        )

    if method == "tools/list":
        return _ok(req_id, {"tools": _TOOLS})

    if method == "resources/list":
        return _ok(req_id, {"resources": _RESOURCES})

    if method == "resources/read":
        uri = params.get("uri", "")
        try:
            content = _read_resource(uri, graph_path)
            mime = next((r["mimeType"] for r in _RESOURCES if r["uri"] == uri), "text/plain")
            return _ok(req_id, {"contents": [{"uri": uri, "mimeType": mime, "text": content}]})
        except Exception as exc:
            return _error(req_id, -32603, f"Resource read error: {exc}")

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        handler = _TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return _error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            _ensure_graph(graph_path)
            result = handler(tool_args)
            return _ok(
                req_id,
                {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}],
                },
            )
        except Exception as exc:
            return _error(req_id, -32603, str(exc))

    if method == "ping":
        return _ok(req_id, {})

    return _error(req_id, -32601, f"Unknown method: {method}")


def serve(graph_path: str) -> None:
    """Run the MCP stdio server until stdin closes."""
    print("[graphify-sf serve] MCP stdio server started", file=sys.stderr)
    print(f"[graphify-sf serve] graph: {graph_path}", file=sys.stderr)
    print(f"[graphify-sf serve] tools: {', '.join(t['name'] for t in _TOOLS)}", file=sys.stderr)
    print(f"[graphify-sf serve] resources: {len(_RESOURCES)}", file=sys.stderr)

    for raw_line in _filtered_stdin():
        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            _send(_error(None, -32700, f"Parse error: {exc}"))
            continue
        try:
            response = _handle(msg, graph_path)
            if response is not None:
                _send(response)
        except Exception as exc:
            _send(_error(msg.get("id"), -32603, f"Internal error: {exc}"))
