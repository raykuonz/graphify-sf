"""G3 — MultiDiGraph verification tests (graphify-sf v0.4.0).

Tests the core contract change: same-direction parallel relations (e.g. an Apex
class that BOTH queries AND dml-writes the same object) are now preserved in the
graph.  Also verifies:
  - graph.json declares "multigraph": true and links carry a "key"
  - round-trip via node_link_graph preserves both parallel edges
  - relation-filter queries find the pair via BOTH queries AND dml
  - NEGATIVE CONTROL: multigraph=False loses one relation (this test must stay)

CRITICAL: Run with .venv/bin/python -m pytest (bare python has no networkx).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
EPICG_FIXTURE = FIXTURES / "epicG_multigraph" / "force-app" / "main" / "default"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_graphify(fixture_path: Path, out_dir: Path) -> dict:
    """Run graphify-sf on the fixture, return parsed graph.json."""
    result = subprocess.run(
        [sys.executable, "-m", "graphify_sf", str(fixture_path), "--no-viz", "--force", "--out", str(out_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"graphify-sf failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    graph_json_path = out_dir / "graph.json"
    assert graph_json_path.exists(), "graph.json not written"
    return json.loads(graph_json_path.read_text(encoding="utf-8"))


def _links(graph_data: dict) -> list[dict]:
    return graph_data.get("links", graph_data.get("edges", []))


def _apex_account_links(graph_data: dict) -> list[dict]:
    """Return all links between apex_accountprocessor and object_account."""
    return [
        lnk
        for lnk in _links(graph_data)
        if lnk.get("source") == "apex_accountprocessor" and lnk.get("target") == "object_account"
    ]


# ---------------------------------------------------------------------------
# G3.1 — multigraph flag and parallel edges in graph.json
# ---------------------------------------------------------------------------


def test_graph_json_declares_multigraph(tmp_path):
    """graph.json must declare "multigraph": true (contract change)."""
    data = _run_graphify(EPICG_FIXTURE, tmp_path)
    assert data.get("multigraph") is True, 'graph.json missing "multigraph": true'


def test_graph_json_links_have_key_field(tmp_path):
    """Each link entry in graph.json must carry a "key" field (multigraph contract)."""
    data = _run_graphify(EPICG_FIXTURE, tmp_path)
    links = _links(data)
    assert links, "graph.json has no links"
    missing_key = [lnk for lnk in links if "key" not in lnk]
    assert not missing_key, f"{len(missing_key)} link(s) missing 'key' field: {missing_key[:3]}"


def test_parallel_edges_both_queries_and_dml_in_graph_json(tmp_path):
    """AccountProcessor → Account must have BOTH a queries AND a dml link."""
    data = _run_graphify(EPICG_FIXTURE, tmp_path)
    pair_links = _apex_account_links(data)
    relations = {lnk.get("relation") for lnk in pair_links}
    assert "queries" in relations, f"queries relation missing; found: {relations}"
    assert "dml" in relations, f"dml relation missing; found: {relations}"
    assert len(pair_links) >= 2, f"expected ≥2 links for the pair, got {len(pair_links)}: {pair_links}"


def test_parallel_edges_have_distinct_keys(tmp_path):
    """Parallel links between the same pair must carry distinct key values."""
    data = _run_graphify(EPICG_FIXTURE, tmp_path)
    pair_links = _apex_account_links(data)
    keys = [lnk.get("key") for lnk in pair_links]
    assert len(set(keys)) == len(keys), f"duplicate keys in parallel links: {keys}"


# ---------------------------------------------------------------------------
# G3.2 — round-trip: load graph.json via node_link_graph
# ---------------------------------------------------------------------------


def test_round_trip_preserves_parallel_edges(tmp_path):
    """Loading graph.json via node_link_graph must preserve both parallel edges."""
    import networkx as nx
    from networkx.readwrite import json_graph as _jg

    data = _run_graphify(EPICG_FIXTURE, tmp_path)
    try:
        G = _jg.node_link_graph(data, edges="links")
    except TypeError:
        G = _jg.node_link_graph(data)

    assert isinstance(G, (nx.MultiGraph, nx.MultiDiGraph)), f"loaded graph is {type(G).__name__}, expected MultiDiGraph"

    src, tgt = "apex_accountprocessor", "object_account"
    assert G.has_edge(src, tgt), f"edge {src}→{tgt} missing after round-trip"

    from graphify_sf.build import edge_datas

    eds = edge_datas(G, src, tgt)
    relations = {ed.get("relation") for ed in eds}
    assert "queries" in relations, f"queries missing after round-trip; found: {relations}"
    assert "dml" in relations, f"dml missing after round-trip; found: {relations}"


# ---------------------------------------------------------------------------
# G3.3 — consumer query: relation-filter finds pair via both queries and dml
# ---------------------------------------------------------------------------


def test_relation_filter_finds_pair_via_queries(tmp_path):
    """A filter for relation=queries must return the AccountProcessor→Account pair."""
    from networkx.readwrite import json_graph as _jg

    from graphify_sf.build import edge_datas

    data = _run_graphify(EPICG_FIXTURE, tmp_path)
    try:
        G = _jg.node_link_graph(data, edges="links")
    except TypeError:
        G = _jg.node_link_graph(data)

    src = "apex_accountprocessor"
    neighbors = list(G.neighbors(src))
    queries_neighbors = [
        nb for nb in neighbors if any(ed.get("relation") == "queries" for ed in edge_datas(G, src, nb))
    ]
    assert "object_account" in queries_neighbors, (
        f"object_account not found via queries filter; queries_neighbors={queries_neighbors}"
    )


def test_relation_filter_finds_pair_via_dml(tmp_path):
    """A filter for relation=dml must ALSO return the AccountProcessor→Account pair."""
    from networkx.readwrite import json_graph as _jg

    from graphify_sf.build import edge_datas

    data = _run_graphify(EPICG_FIXTURE, tmp_path)
    try:
        G = _jg.node_link_graph(data, edges="links")
    except TypeError:
        G = _jg.node_link_graph(data)

    src = "apex_accountprocessor"
    neighbors = list(G.neighbors(src))
    dml_neighbors = [nb for nb in neighbors if any(ed.get("relation") == "dml" for ed in edge_datas(G, src, nb))]
    assert "object_account" in dml_neighbors, f"object_account not found via dml filter; dml_neighbors={dml_neighbors}"


# ---------------------------------------------------------------------------
# G3 NEGATIVE CONTROL — multigraph=False loses a relation (MANDATORY)
# This test PROVES that the multigraph path is what preserves both edges.
# Keep this test — it must pass to demonstrate the fix is doing real work.
# ---------------------------------------------------------------------------


def test_negative_control_simple_graph_loses_a_relation():
    """NEGATIVE CONTROL (G3): multigraph=False (simple graph) must lose one of
    queries/dml when both come from the same Apex class to the same object.

    This test proves the multigraph fix is load-bearing: if it ever starts
    failing (both relations surviving on a simple graph), the fix is broken.
    """
    from graphify_sf.build import build_from_json, edge_datas

    extraction = {
        "nodes": [
            {
                "id": "apex_accountprocessor",
                "label": "AccountProcessor",
                "sf_type": "ApexClass",
                "file_type": "apex",
                "source_file": "AccountProcessor.cls",
            },
            {
                "id": "object_account",
                "label": "Account",
                "sf_type": "CustomObject",
                "file_type": "object",
                "source_file": "Account.object-meta.xml",
            },
        ],
        "edges": [
            {
                "source": "apex_accountprocessor",
                "target": "object_account",
                "relation": "queries",
                "confidence": "EXTRACTED",
            },
            {
                "source": "apex_accountprocessor",
                "target": "object_account",
                "relation": "dml",
                "confidence": "INFERRED",
            },
        ],
    }

    # multigraph=True (default 0.4.0): BOTH edges survive
    G_multi = build_from_json(extraction, multigraph=True)
    multi_rels = {ed.get("relation") for ed in edge_datas(G_multi, "apex_accountprocessor", "object_account")}
    assert "queries" in multi_rels, "multigraph=True must preserve queries"
    assert "dml" in multi_rels, "multigraph=True must preserve dml"
    assert len(multi_rels) == 2, f"multigraph=True must have 2 distinct relations, got {multi_rels}"

    # multigraph=False (pre-0.4.0 simple graph): exactly ONE relation survives
    G_simple = build_from_json(extraction, multigraph=False)
    simple_rels = {ed.get("relation") for ed in edge_datas(G_simple, "apex_accountprocessor", "object_account")}
    assert len(simple_rels) == 1, (
        f"NEGATIVE CONTROL FAILED: simple graph should lose one relation, "
        f"but both survived: {simple_rels}. The multigraph fix may be broken."
    )
    # dml (priority=60) outranks queries (priority=55) in _RELATION_PRIORITY.
    # With a simple graph the collision guard keeps the higher-priority relation,
    # so dml survives regardless of edge order. Either way exactly ONE survives.
    assert simple_rels <= {"queries", "dml"}, f"unexpected relation in simple graph: {simple_rels}"


# ---------------------------------------------------------------------------
# G3.4 — opposite-direction case: self-lookup still works (0.3.6 behavior)
# ---------------------------------------------------------------------------


def test_self_lookup_opposite_direction_preserved(tmp_path):
    """Account has a self-lookup field ParentAccount__c → both directed edges
    (object→field contains and field→object references) must exist."""
    from networkx.readwrite import json_graph as _jg

    from graphify_sf.build import edge_datas

    data = _run_graphify(EPICG_FIXTURE, tmp_path)
    try:
        G = _jg.node_link_graph(data, edges="links")
    except TypeError:
        G = _jg.node_link_graph(data)

    obj = "object_account"
    field = "field_account_parentaccount__c"
    assert G.has_node(obj), f"node {obj} missing"
    assert G.has_node(field), f"node {field} missing"
    # object → field (contains)
    assert G.has_edge(obj, field), f"contains edge {obj}→{field} missing"
    contains_rels = {ed.get("relation") for ed in edge_datas(G, obj, field)}
    assert "contains" in contains_rels, f"contains missing in {contains_rels}"
    # field → object (references)
    assert G.has_edge(field, obj), f"references edge {field}→{obj} missing"
    ref_rels = {ed.get("relation") for ed in edge_datas(G, field, obj)}
    assert "references" in ref_rels, f"references missing in {ref_rels}"


# ---------------------------------------------------------------------------
# A1 — serve.py MCP tool handlers must surface ALL parallel edges
# (regression of the 0.4.0 MultiDiGraph fix — edge_data → edge_datas)
# ---------------------------------------------------------------------------


def _multi_serve_graph():
    """A tiny MultiDiGraph: AccountProcessor both queries AND dml-writes Account."""
    from graphify_sf.build import build_from_json

    extraction = {
        "nodes": [
            {"id": "apex_accountprocessor", "label": "AccountProcessor", "sf_type": "ApexClass", "file_type": "apex"},
            {"id": "object_account", "label": "Account", "sf_type": "CustomObject", "file_type": "object"},
        ],
        "edges": [
            {
                "source": "apex_accountprocessor",
                "target": "object_account",
                "relation": "queries",
                "confidence": "EXTRACTED",
            },
            {
                "source": "apex_accountprocessor",
                "target": "object_account",
                "relation": "dml",
                "confidence": "EXTRACTED",
            },
        ],
    }
    return build_from_json(extraction, multigraph=True)


def _install_serve_graph(monkeypatch, G):
    import graphify_sf.serve as serve

    monkeypatch.setattr(serve, "_G", G, raising=False)
    monkeypatch.setattr(serve, "_communities", {}, raising=False)
    monkeypatch.setattr(serve, "_community_labels", {}, raising=False)
    return serve


def test_serve_get_neighbors_surfaces_both_parallel_relations(monkeypatch):
    """get_neighbors with no filter must emit BOTH queries and dml for the pair."""
    serve = _install_serve_graph(monkeypatch, _multi_serve_graph())
    result = serve._tool_get_neighbors({"label": "AccountProcessor"})
    rels = {(n["id"], n["relation"]) for n in result["neighbors"]}
    assert ("object_account", "queries") in rels, f"queries missing: {rels}"
    assert ("object_account", "dml") in rels, f"dml missing: {rels}"


def test_serve_get_neighbors_relation_filter_finds_pair_via_dml(monkeypatch):
    """The identical bug 0.4.0 fixed for --explain: dml filter must find the pair."""
    serve = _install_serve_graph(monkeypatch, _multi_serve_graph())
    result = serve._tool_get_neighbors({"label": "AccountProcessor", "relation_filter": "dml"})
    ids = {n["id"] for n in result["neighbors"]}
    assert "object_account" in ids, f"object_account not found via dml filter: {result['neighbors']}"


def test_serve_get_neighbors_relation_filter_finds_pair_via_queries(monkeypatch):
    """queries filter must ALSO find the same pair."""
    serve = _install_serve_graph(monkeypatch, _multi_serve_graph())
    result = serve._tool_get_neighbors({"label": "AccountProcessor", "relation_filter": "queries"})
    ids = {n["id"] for n in result["neighbors"]}
    assert "object_account" in ids, f"object_account not found via queries filter: {result['neighbors']}"


def test_serve_get_node_lists_every_relation_to_neighbor(monkeypatch):
    """get_node's connection list must include every relation, not just the first."""
    serve = _install_serve_graph(monkeypatch, _multi_serve_graph())
    result = serve._tool_get_node({"label": "AccountProcessor"})
    rels = {n["relation"] for n in result["neighbors"] if n["id"] == "object_account"}
    assert rels == {"queries", "dml"}, f"expected both relations, got {rels}"


def test_serve_shortest_path_reports_all_parallel_relations(monkeypatch):
    """shortest_path hop label must reflect the full set of parallel edges."""
    serve = _install_serve_graph(monkeypatch, _multi_serve_graph())
    result = serve._tool_shortest_path({"source": "AccountProcessor", "target": "Account"})
    assert result["found"], result
    hop = result["path"][0]
    rel = hop["relation"]
    rels = set(rel) if isinstance(rel, list) else {rel}
    assert "queries" in rels and "dml" in rels, f"hop lost a parallel relation: {rel}"


# ---------------------------------------------------------------------------
# A4 — bfs_impact MCP tool
# ---------------------------------------------------------------------------


def _bfs_chain_graph():
    """A→B (calls) → C (references); plus INFERRED A→D that must not appear by default."""
    from graphify_sf.build import build_from_json

    extraction = {
        "nodes": [
            {"id": "a", "label": "A", "sf_type": "ApexClass", "file_type": "apex"},
            {"id": "b", "label": "B", "sf_type": "CustomObject", "file_type": "object"},
            {"id": "c", "label": "C", "sf_type": "Flow", "file_type": "flow"},
            {"id": "d", "label": "D", "sf_type": "ApexClass", "file_type": "apex"},
        ],
        "edges": [
            {"source": "a", "target": "b", "relation": "calls", "confidence": "EXTRACTED"},
            {"source": "b", "target": "c", "relation": "references", "confidence": "EXTRACTED"},
            {"source": "a", "target": "d", "relation": "calls", "confidence": "INFERRED"},
        ],
    }
    return build_from_json(extraction, multigraph=True)


def test_bfs_impact_forward_returns_chain_at_correct_depths(monkeypatch):
    serve = _install_serve_graph(monkeypatch, _bfs_chain_graph())
    result = serve._tool_bfs_impact({"node": "A", "direction": "forward", "max_depth": 3})
    depths = {n["id"]: n["depth"] for n in result["nodes"]}
    assert depths == {"b": 1, "c": 2}, f"expected b@1, c@2 (no INFERRED d), got {depths}"
    assert result["total_impacted"] == 2


def test_bfs_impact_reverse_walks_predecessors(monkeypatch):
    serve = _install_serve_graph(monkeypatch, _bfs_chain_graph())
    result = serve._tool_bfs_impact({"node": "C", "direction": "reverse", "max_depth": 3})
    depths = {n["id"]: n["depth"] for n in result["nodes"]}
    assert depths == {"b": 1, "a": 2}, f"reverse from C should reach b@1, a@2, got {depths}"


def test_bfs_impact_both_unions_directions(monkeypatch):
    serve = _install_serve_graph(monkeypatch, _bfs_chain_graph())
    result = serve._tool_bfs_impact({"node": "B", "direction": "both", "max_depth": 1})
    ids = {n["id"] for n in result["nodes"]}
    assert ids == {"a", "c"}, f"both @depth1 from B should be a and c, got {ids}"


def test_bfs_impact_excludes_inferred_by_default(monkeypatch):
    serve = _install_serve_graph(monkeypatch, _bfs_chain_graph())
    result = serve._tool_bfs_impact({"node": "A", "direction": "forward", "max_depth": 3})
    ids = {n["id"] for n in result["nodes"]}
    assert "d" not in ids, f"INFERRED edge A→D must not appear by default, got {ids}"


def test_bfs_impact_include_inferred_toggles_visibility(monkeypatch):
    serve = _install_serve_graph(monkeypatch, _bfs_chain_graph())
    result = serve._tool_bfs_impact({"node": "A", "direction": "forward", "max_depth": 3, "include_inferred": True})
    ids = {n["id"] for n in result["nodes"]}
    assert "d" in ids, f"include_inferred must surface the INFERRED A→D edge, got {ids}"


def test_bfs_impact_limit_truncates_but_preserves_total(monkeypatch):
    serve = _install_serve_graph(monkeypatch, _bfs_chain_graph())
    result = serve._tool_bfs_impact({"node": "A", "direction": "forward", "max_depth": 3, "limit": 1})
    assert result["truncated"] is True
    assert result["returned"] == 1
    assert result["total_impacted"] == 2, "total_impacted must be the untruncated count"


def test_bfs_impact_relation_filter_restricts_traversal(monkeypatch):
    serve = _install_serve_graph(monkeypatch, _bfs_chain_graph())
    # Only 'calls' edges: A→B is calls, B→C is references, so C must not be reached.
    result = serve._tool_bfs_impact({"node": "A", "direction": "forward", "max_depth": 3, "relation_filter": "calls"})
    ids = {n["id"] for n in result["nodes"]}
    assert ids == {"b"}, f"relation_filter=calls should reach only b, got {ids}"


def test_bfs_impact_unknown_node_returns_not_found(monkeypatch):
    serve = _install_serve_graph(monkeypatch, _bfs_chain_graph())
    result = serve._tool_bfs_impact({"node": "DoesNotExist"})
    assert result["found"] is False


def test_bfs_impact_surfaces_all_parallel_relations_to_neighbor(monkeypatch):
    """A neighbour reached via several parallel edges must report ALL of them.

    Regression for the MultiDiGraph collapse: AccountProcessor both queries AND
    dml-writes Account, so bfs_impact must list both relations, not just the
    first-encountered one.
    """
    serve = _install_serve_graph(monkeypatch, _multi_serve_graph())
    result = serve._tool_bfs_impact({"node": "AccountProcessor", "direction": "forward", "max_depth": 1})
    entry = next(n for n in result["nodes"] if n["id"] == "object_account")
    rel = entry["relation"]
    rels = set(rel) if isinstance(rel, list) else {rel}
    assert rels == {"queries", "dml"}, f"bfs_impact lost a parallel relation: {rel}"


def _multi_confidence_serve_graph():
    """AccountProcessor writes Account via one EXTRACTED and one INFERRED edge."""
    from graphify_sf.build import build_from_json

    extraction = {
        "nodes": [
            {"id": "apex_accountprocessor", "label": "AccountProcessor", "sf_type": "ApexClass", "file_type": "apex"},
            {"id": "object_account", "label": "Account", "sf_type": "CustomObject", "file_type": "object"},
        ],
        "edges": [
            {
                "source": "apex_accountprocessor",
                "target": "object_account",
                "relation": "dml",
                "confidence": "EXTRACTED",
            },
            {
                "source": "apex_accountprocessor",
                "target": "object_account",
                "relation": "reads_config",
                "confidence": "INFERRED",
            },
        ],
    }
    return build_from_json(extraction, multigraph=True)


def test_bfs_impact_surfaces_all_parallel_confidences_to_neighbor(monkeypatch):
    """Confidence must not collapse either: an EXTRACTED + INFERRED pair to one
    target reports both confidences when include_inferred is set."""
    serve = _install_serve_graph(monkeypatch, _multi_confidence_serve_graph())
    result = serve._tool_bfs_impact(
        {"node": "AccountProcessor", "direction": "forward", "max_depth": 1, "include_inferred": True}
    )
    entry = next(n for n in result["nodes"] if n["id"] == "object_account")
    conf = entry["confidence"]
    confs = set(conf) if isinstance(conf, list) else {conf}
    assert confs == {"EXTRACTED", "INFERRED"}, f"bfs_impact collapsed confidence: {conf}"


# ---------------------------------------------------------------------------
# _get_int hardening — non-numeric / oversized MCP args must not crash or
# return unbounded results (serve.py's int(args.get(...)) call sites)
# ---------------------------------------------------------------------------


def test_bfs_impact_non_numeric_max_depth_falls_back_to_default(monkeypatch):
    serve = _install_serve_graph(monkeypatch, _bfs_chain_graph())
    result = serve._tool_bfs_impact({"node": "A", "direction": "forward", "max_depth": "abc"})
    assert result["found"] is True
    assert result["max_depth"] == 3


def test_bfs_impact_non_numeric_limit_falls_back_to_default(monkeypatch):
    serve = _install_serve_graph(monkeypatch, _bfs_chain_graph())
    result = serve._tool_bfs_impact({"node": "A", "direction": "forward", "limit": "not-a-number"})
    assert result["found"] is True
    assert result["truncated"] is False
    assert result["returned"] == result["total_impacted"]


def test_bfs_impact_oversized_limit_is_capped(monkeypatch):
    serve = _install_serve_graph(monkeypatch, _bfs_chain_graph())
    result = serve._tool_bfs_impact({"node": "A", "direction": "forward", "limit": 1_000_000})
    assert result["found"] is True
    assert result["returned"] == result["total_impacted"]


def test_get_neighbors_non_numeric_limit_falls_back_to_default(monkeypatch):
    serve = _install_serve_graph(monkeypatch, _multi_serve_graph())
    result = serve._tool_get_neighbors({"label": "AccountProcessor", "limit": "abc"})
    assert result["found"] is True


def test_get_int_helper_defaults_on_bad_input():
    from graphify_sf.serve import _get_int

    assert _get_int({"limit": "abc"}, "limit", 20) == 20
    assert _get_int({"limit": None}, "limit", 20) == 20
    assert _get_int({}, "limit", 20) == 20


def test_get_int_helper_clamps_to_bounds():
    from graphify_sf.serve import _get_int

    assert _get_int({"limit": 1_000_000}, "limit", 20, min_val=1, max_val=10000) == 10000
    assert _get_int({"max_depth": -5}, "max_depth", 3, min_val=0, max_val=10) == 0
