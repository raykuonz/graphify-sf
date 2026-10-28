"""Merging raw graph.json files: strict loading, edge identity and the git 3-way merge.

``merge-graphs`` unions N graphs; the git merge driver merges ours/theirs against a common
base. Both work on the raw ``nodes`` / ``links`` lists (never a collapsing ``nx.Graph``) so
parallel edges survive until the multigraph build.
"""

from __future__ import annotations

import json
from pathlib import Path

from graphify_sf.build import prefer_real

_MISSING = object()

# Edge fields that never decide whether two links are the same edge. ``key`` is numbered per source graph;
# ``source_file`` is an absolute path of the building machine; ``source_location`` is a line number that moves
# whenever the file is edited; ``confidence_score`` is derived from ``confidence`` and ``weight`` is constant;
# ``site_count`` counts call sites on an aggregated edge. Everything else (relation, confidence, operation,
# trigger_type, test_context, inference_reason, ...) is part of the identity, so ``dml`` create and update stay
# separate edges, and an attribute added by a newer tool version can only ever *split* edges, never merge two
# distinct ones. A denylist (not an allowlist) is deliberate.
_VOLATILE_EDGE_FIELDS = frozenset({"key", "source_file", "source_location", "confidence_score", "weight", "site_count"})


class GraphJsonError(ValueError):
    """A graph.json that cannot be merged safely (unreadable, malformed, missing node/link arrays)."""


def load_graph_json_strict(path: Path) -> dict:
    """Load a graph.json for merging, or raise `GraphJsonError`.

    Unlike the tolerant loader used elsewhere, an unreadable file is an error and never an empty
    graph: under deletion-wins, an empty graph would silently delete everything.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GraphJsonError(f"{path}: cannot read as JSON ({exc})") from exc
    if not isinstance(raw, dict):
        raise GraphJsonError(f"{path}: top level is not a JSON object")
    if "links" not in raw and "edges" in raw:
        raw = dict(raw, links=raw["edges"])
    for key in ("nodes", "links"):
        if not isinstance(raw.get(key), list):
            raise GraphJsonError(f"{path}: missing or invalid '{key}' array")
    # A node without a usable id (or a non-object entry) would be silently dropped, and under
    # deletion-wins that deletes the other side's copy: refuse instead.
    for i, node in enumerate(raw["nodes"]):
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            raise GraphJsonError(f"{path}: nodes[{i}] is not an object with a non-empty string 'id'")
    for i, link in enumerate(raw["links"]):
        if not isinstance(link, dict) or "source" not in link or "target" not in link:
            raise GraphJsonError(f"{path}: links[{i}] is not an object with 'source' and 'target'")
    return raw


def load_base_graph_json(path: Path) -> dict | None:
    """The merge base, or None when there is none (missing or zero-byte file = add/add merge).

    A non-empty base that cannot be read or parsed is an error: guessing "no base" would resurrect
    nodes that one side deleted.
    """
    p = Path(path)
    try:
        if not p.exists() or p.stat().st_size == 0:
            return None
    except OSError as exc:
        raise GraphJsonError(f"{path}: cannot inspect merge base ({exc})") from exc
    return load_graph_json_strict(p)


def edge_identity(edge: dict) -> str:
    """Canonical identity of a link: every field except the volatile ones above."""
    return json.dumps({k: v for k, v in edge.items() if k not in _VOLATILE_EDGE_FIELDS}, sort_keys=True, default=str)


def merge_attrs(base: dict | None, ours: dict, theirs: dict) -> dict:
    """Per-attribute 3-way merge: ours if it differs from base, else theirs; never base alone.

    With no base every attribute is "changed", so ours wins, except that an explicit ``None`` in ours
    does not hide a real value in theirs.
    """
    base = base or {}
    merged: dict = {}
    for k in dict.fromkeys([*ours, *theirs]):
        b, o, t = base.get(k, _MISSING), ours.get(k, _MISSING), theirs.get(k, _MISSING)
        chosen = o if o != b else t
        if o is None and b is _MISSING and t is not _MISSING:
            chosen = t
        if chosen is not _MISSING:
            merged[k] = chosen
    return merged


def _index_nodes(data: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for node in (data or {}).get("nodes", []):
        nid = node.get("id", "")
        if nid and nid not in out:
            out[nid] = node
    return out


def _index_edges(data: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for edge in (data or {}).get("links", []):
        out.setdefault(edge_identity(edge), {k: v for k, v in edge.items() if k != "key"})
    return out


def three_way_merge(
    base: dict | None, ours: dict, theirs: dict, *, prune_dangling: bool = False
) -> tuple[list[dict], list[dict]]:
    """Git-style 3-way merge of node and edge lists.

    Keep x if it is in both heads, or in exactly one head and not in the base. Present in the base
    but missing from either head means that head deleted it, and deletion wins (a node one side
    modified and the other deleted is deleted; graph.json is regenerated by the next build).
    Attributes merge per attribute, never letting the base win. ``base is None`` means no common
    base: a plain union. With *prune_dangling*, edges whose endpoint did not survive are dropped (an edge
    one side added to a node the other side deleted would otherwise bring the node back as a stub).
    """

    def keep(in_ours: bool, in_theirs: bool, in_base: bool) -> bool:
        if in_ours and in_theirs:
            return True
        return (in_ours or in_theirs) and not in_base

    b_nodes, o_nodes, t_nodes = _index_nodes(base), _index_nodes(ours), _index_nodes(theirs)
    nodes: list[dict] = []
    for nid in [*o_nodes, *(n for n in t_nodes if n not in o_nodes)]:
        if keep(nid in o_nodes, nid in t_nodes, nid in b_nodes):
            ours_node, theirs_node = o_nodes.get(nid, {}), t_nodes.get(nid, {})
            real = prefer_real(ours_node, theirs_node) if ours_node and theirs_node else None
            nodes.append(dict(real) if real is not None else merge_attrs(b_nodes.get(nid), ours_node, theirs_node))

    b_edges, o_edges, t_edges = _index_edges(base), _index_edges(ours), _index_edges(theirs)
    edges: list[dict] = []
    for ident in [*o_edges, *(e for e in t_edges if e not in o_edges)]:
        if keep(ident in o_edges, ident in t_edges, ident in b_edges):
            edges.append(merge_attrs(b_edges.get(ident), o_edges.get(ident, {}), t_edges.get(ident, {})))
    if prune_dangling:
        alive = {n["id"] for n in nodes}
        edges = [e for e in edges if e.get("source") in alive and e.get("target") in alive]
    return nodes, edges


def union_graph_json(datas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Union of several graphs' node/link lists (no base, nothing is deleted), for ``merge-graphs``."""
    acc: dict = {"nodes": [], "links": []}
    for data in datas:
        nodes, links = three_way_merge(None, acc, data)
        acc = {"nodes": nodes, "links": links}
    return acc["nodes"], acc["links"]
