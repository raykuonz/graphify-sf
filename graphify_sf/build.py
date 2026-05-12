"""Assemble node+edge dicts into a NetworkX graph.

Adapted from Graphify's build.py — removes LLM dedup and validate imports,
adds build_from_extraction() and build_merge_sf() for the SF pipeline.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import networkx as nx


def _normalize_id(s: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", s)
    return cleaned.strip("_").lower()


def _norm_source_file(p: str | None) -> str | None:
    return p.replace("\\", "/") if p else p


def edge_data(G: nx.Graph, u: str, v: str) -> dict:
    raw = G[u][v]
    if isinstance(G, (nx.MultiGraph, nx.MultiDiGraph)):
        return next(iter(raw.values()), {})
    return raw


def edge_datas(G: nx.Graph, u: str, v: str) -> list[dict]:
    raw = G[u][v]
    if isinstance(G, (nx.MultiGraph, nx.MultiDiGraph)):
        return list(raw.values())
    return [raw]


def build_from_json(extraction: dict, *, directed: bool = False) -> nx.Graph:
    """Build a NetworkX graph from an extraction dict."""
    if "edges" not in extraction and "links" in extraction:
        extraction = dict(extraction, edges=extraction["links"])

    G: nx.Graph = nx.DiGraph() if directed else nx.Graph()
    for node in extraction.get("nodes", []):
        if not isinstance(node, dict) or "id" not in node:
            continue
        if node.get("file_type") in (None, ""):
            node = dict(node)
            node["file_type"] = "concept"
        if "source_file" in node:
            node = dict(node)
            node["source_file"] = _norm_source_file(node["source_file"])
        G.add_node(node["id"], **{k: v for k, v in node.items() if k != "id"})

    node_set = set(G.nodes())
    norm_to_id: dict[str, str] = {_normalize_id(nid): nid for nid in node_set}

    for edge in extraction.get("edges", []):
        if not isinstance(edge, dict):
            continue
        if "source" not in edge and "from" in edge:
            edge = dict(edge)
            edge["source"] = edge["from"]
        if "target" not in edge and "to" in edge:
            edge = dict(edge)
            edge["target"] = edge["to"]
        if "source" not in edge or "target" not in edge:
            continue
        src, tgt = edge["source"], edge["target"]
        if src not in node_set:
            src = norm_to_id.get(_normalize_id(src), src)
        if tgt not in node_set:
            tgt = norm_to_id.get(_normalize_id(tgt), tgt)
        if src not in node_set or tgt not in node_set:
            continue  # dangling edges to external references — skip
        attrs = {k: v for k, v in edge.items() if k not in ("source", "target")}
        if "source_file" in attrs:
            attrs["source_file"] = _norm_source_file(attrs["source_file"])
        attrs["_src"] = src
        attrs["_tgt"] = tgt
        G.add_edge(src, tgt, **attrs)

    hyperedges = extraction.get("hyperedges", [])
    if hyperedges:
        G.graph["hyperedges"] = hyperedges
    return G


# Alias used by the CLI and other modules
build_from_extraction = build_from_json


def build(extractions: list[dict], *, directed: bool = False) -> nx.Graph:
    """Merge multiple extraction results into one graph."""
    combined: dict = {
        "nodes": [],
        "edges": [],
        "hyperedges": [],
        "input_tokens": 0,
        "output_tokens": 0,
    }
    for ext in extractions:
        combined["nodes"].extend(ext.get("nodes", []))
        combined["edges"].extend(ext.get("edges", []))
        combined["hyperedges"].extend(ext.get("hyperedges", []))
    return build_from_json(combined, directed=directed)


def build_merge_sf(
    new_extraction: dict,
    graph_path: str | Path = "graphify-sf-out/graph.json",
    *,
    directed: bool = False,
) -> nx.Graph:
    """Load existing graph.json, merge new extraction into it.

    Used by --update (incremental mode). Loads existing nodes/edges from
    graph.json and combines them with the new extraction result.
    """
    graph_path = Path(graph_path)
    if graph_path.exists():
        try:
            data = json.loads(graph_path.read_text(encoding="utf-8"))
            links_key = "links" if "links" in data else "edges"
            existing = {
                "nodes": list(data.get("nodes", [])),
                "edges": list(data.get(links_key, [])),
            }
        except Exception as exc:
            print(f"[graphify-sf] WARNING: could not load {graph_path}: {exc}", file=sys.stderr)
            existing = {"nodes": [], "edges": []}
    else:
        existing = {"nodes": [], "edges": []}

    return build([existing, new_extraction], directed=directed)


def _norm_label(label: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", label.lower()).strip()


def deduplicate_by_label(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict]]:
    """Merge nodes that share a normalised label, rewriting edge references."""
    _CHUNK_SUFFIX = re.compile(r"_c\d+$")
    canonical: dict[str, dict] = {}
    remap: dict[str, str] = {}

    for node in nodes:
        key = _norm_label(node.get("label", node.get("id", "")))
        if not key:
            continue
        existing = canonical.get(key)
        if existing is None:
            canonical[key] = node
        else:
            has_suffix = bool(_CHUNK_SUFFIX.search(node["id"]))
            existing_has_suffix = bool(_CHUNK_SUFFIX.search(existing["id"]))
            if has_suffix and not existing_has_suffix:
                remap[node["id"]] = existing["id"]
            elif existing_has_suffix and not has_suffix:
                remap[existing["id"]] = node["id"]
                canonical[key] = node
            elif len(node["id"]) < len(existing["id"]):
                remap[existing["id"]] = node["id"]
                canonical[key] = node
            else:
                remap[node["id"]] = existing["id"]

    if not remap:
        return nodes, edges

    deduped_nodes = list(canonical.values())
    deduped_edges = []
    for edge in edges:
        e = dict(edge)
        e["source"] = remap.get(e["source"], e["source"])
        e["target"] = remap.get(e["target"], e["target"])
        if e["source"] != e["target"]:
            deduped_edges.append(e)
    return deduped_nodes, deduped_edges
