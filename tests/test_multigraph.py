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

    assert isinstance(G, (nx.MultiGraph, nx.MultiDiGraph)), (
        f"loaded graph is {type(G).__name__}, expected MultiDiGraph"
    )

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
    dml_neighbors = [
        nb for nb in neighbors if any(ed.get("relation") == "dml" for ed in edge_datas(G, src, nb))
    ]
    assert "object_account" in dml_neighbors, (
        f"object_account not found via dml filter; dml_neighbors={dml_neighbors}"
    )


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
