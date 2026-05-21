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

    # Ensure stub nodes exist for referenced IDs with no extracted node.
    # Mutate a copy so we don't modify the caller's data.
    nodes_list = list(extraction.get("nodes", []))
    edges_list = list(extraction.get("edges", []))
    _ensure_stub_nodes(nodes_list, edges_list)
    extraction = dict(extraction, nodes=nodes_list, edges=edges_list)

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


def _resolve_apex_calls(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Resolve _raw_calls stored on Apex nodes into cross-file 'calls' edges.

    apex.py stores unresolved inter-class method calls in node["_raw_calls"].
    After all nodes are collected we can match callee_class names to known
    ApexClass node IDs and emit edges.
    """
    # Build label → node_id map for all Apex class-like nodes
    apex_label_to_id: dict[str, str] = {}
    for node in nodes:
        if node.get("sf_type") in ("ApexClass", "ApexInterface", "ApexEnum", "ApexTrigger"):
            label = node.get("label", "")
            if label:
                apex_label_to_id[label.lower()] = node["id"]

    extra_edges: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for node in nodes:
        raw_calls = node.get("_raw_calls")
        if not raw_calls:
            continue
        caller_source_file = node.get("source_file", "")
        for call in raw_calls:
            callee_class = call.get("callee_class", "")
            caller_id = call.get("caller_id", "")
            if not callee_class or not caller_id:
                continue
            target_id = apex_label_to_id.get(callee_class.lower())
            if target_id and caller_id != target_id:
                key = (caller_id, target_id)
                if key not in seen:
                    seen.add(key)
                    extra_edges.append(
                        {
                            "source": caller_id,
                            "target": target_id,
                            "relation": "calls",
                            "confidence": "INFERRED",
                            "confidence_score": 0.8,
                            "source_file": caller_source_file,
                            "source_location": None,
                            "weight": 1.0,
                            "_src": caller_id,
                            "_tgt": target_id,
                        }
                    )

    return extra_edges


def _derive_object_edges(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Derive direct Object → Object edges from Field → Object lookup/references edges.

    object.py emits:  Object → Field (contains)  and  Field → Object (references)
    This adds:        Object → Object (references, INFERRED) when a lookup field links them.
    Only adds the edge if it doesn't already exist in the current edge list.
    """
    # Build node_id → sf_type map
    node_type: dict[str, str] = {n["id"]: n.get("sf_type", "") for n in nodes}

    # Build Field → parent Object map from "contains" edges
    field_to_parent: dict[str, str] = {}
    for edge in edges:
        if (
            edge.get("relation") == "contains"
            and node_type.get(edge["source"]) == "CustomObject"
            and node_type.get(edge["target"]) == "CustomField"
        ):
            field_to_parent[edge["target"]] = edge["source"]

    # Gather existing Object → Object edge pairs to avoid duplicates
    existing_obj_edges: set[tuple[str, str]] = set()
    for edge in edges:
        src, tgt = edge.get("source", ""), edge.get("target", "")
        if node_type.get(src) == "CustomObject" and node_type.get(tgt) == "CustomObject":
            existing_obj_edges.add((src, tgt))

    derived: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for edge in edges:
        if edge.get("relation") not in ("references", "master_detail"):
            continue
        src, tgt = edge.get("source", ""), edge.get("target", "")
        if node_type.get(src) != "CustomField" or node_type.get(tgt) != "CustomObject":
            continue
        parent_obj = field_to_parent.get(src)
        if not parent_obj or parent_obj == tgt:
            continue
        key = (parent_obj, tgt)
        if key in existing_obj_edges or key in seen:
            continue
        seen.add(key)
        derived.append(
            {
                "source": parent_obj,
                "target": tgt,
                "relation": edge.get("relation", "references"),
                "confidence": "INFERRED",
                "confidence_score": 0.9,
                "source_file": edge.get("source_file"),
                "source_location": None,
                "weight": 1.0,
                "_src": parent_obj,
                "_tgt": tgt,
            }
        )

    return derived


def _ensure_stub_nodes(nodes: list[dict], edges: list[dict]) -> None:
    """Auto-create stub nodes for referenced IDs that have no extracted node.

    Standard Salesforce objects (Lead, Account, Contact, etc.) are often
    referenced by triggers/flows/fields but never have a .object-meta.xml
    file in the SFDX project.  Without a node, build_from_json drops those
    edges as dangling references.

    This pass scans all edge endpoints, identifies missing node IDs, and
    injects minimal stub nodes so the edges are preserved.

    ID prefix → sf_type mapping mirrors _ids.py conventions:
      object_* → CustomObject
      flow_*   → Flow
      apex_*   → ApexClass
      trigger_* → ApexTrigger
    """
    existing_ids: set[str] = {n["id"] for n in nodes}

    _PREFIX_TYPE: list[tuple[str, str, str]] = [
        ("object_", "CustomObject", "object"),
        ("flow_", "Flow", "flow"),
        ("apex_", "ApexClass", "apex"),
        ("trigger_", "ApexTrigger", "apex"),
    ]

    stubs: list[dict] = []
    seen_stubs: set[str] = set()

    all_ids: set[str] = set()
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src:
            all_ids.add(src)
        if tgt:
            all_ids.add(tgt)

    for nid in all_ids:
        if nid in existing_ids or nid in seen_stubs:
            continue
        for prefix, sf_type, file_type in _PREFIX_TYPE:
            if nid.startswith(prefix):
                # Derive a human-readable label from the ID
                raw = nid[len(prefix) :]
                # Convert snake_case back to PascalCase-ish label
                label = raw.replace("_", " ").title().replace(" ", "_")
                # Strip common suffixes like __c __e __r for display
                label = re.sub(r"_{1,2}[Cer]$", "", label)
                stubs.append(
                    {
                        "id": nid,
                        "label": label,
                        "sf_type": sf_type,
                        "file_type": file_type,
                        "source_file": None,
                        "source_location": None,
                        "stub": True,  # mark as auto-generated
                    }
                )
                seen_stubs.add(nid)
                break

    nodes.extend(stubs)


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

    # Cross-file post-processing passes
    combined["edges"].extend(_resolve_apex_calls(combined["nodes"], combined["edges"]))
    combined["edges"].extend(_derive_object_edges(combined["nodes"], combined["edges"]))

    # Ensure stub nodes exist for referenced objects/flows/apex that have no
    # extracted node yet (e.g. standard objects like Lead, Account that have
    # no .object-meta.xml but are referenced by triggers or flows).
    _ensure_stub_nodes(combined["nodes"], combined["edges"])

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
