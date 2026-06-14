"""Tests for graph building."""

from __future__ import annotations

import json

import networkx as nx


def test_build_from_json_creates_graph(simple_extraction):
    """Test that build_from_json() creates correct number of nodes and edges."""
    from graphify_sf.build import build_from_json

    G = build_from_json(simple_extraction)

    assert isinstance(G, nx.Graph)
    assert G.number_of_nodes() > 0
    assert G.number_of_edges() > 0


def test_build_from_json_node_attributes(simple_extraction):
    """Test that nodes have correct attributes."""
    from graphify_sf.build import build_from_json

    G = build_from_json(simple_extraction)

    # Check that nodes have expected attributes
    for node_id in list(G.nodes())[:5]:  # Check first 5 nodes
        data = G.nodes[node_id]
        assert "label" in data or "sf_type" in data or "file_type" in data


def test_build_from_json_edge_attributes(simple_extraction):
    """Test that edges have correct attributes."""
    from graphify_sf.build import build_from_json

    G = build_from_json(simple_extraction)

    # Check that edges have expected attributes
    for u, v in list(G.edges())[:5]:  # Check first 5 edges
        data = G[u][v]
        assert "relation" in data or "confidence" in data


def test_deduplicate_by_label_removes_duplicates():
    """Test that deduplicate_by_label() removes duplicates."""
    from graphify_sf.build import deduplicate_by_label

    nodes = [
        {"id": "node1", "label": "TestClass"},
        {"id": "node2", "label": "testclass"},  # Duplicate with different case
        {"id": "node3", "label": "OtherClass"},
    ]
    edges = [
        {"source": "node1", "target": "node3", "relation": "calls"},
        {"source": "node2", "target": "node3", "relation": "calls"},
    ]

    deduped_nodes, deduped_edges = deduplicate_by_label(nodes, edges)

    # Should have 2 nodes (TestClass and OtherClass)
    assert len(deduped_nodes) == 2

    # Edges should be rewritten to point to canonical node
    for edge in deduped_edges:
        assert edge["source"] in [n["id"] for n in deduped_nodes]
        assert edge["target"] in [n["id"] for n in deduped_nodes]


def test_deduplicate_by_label_preserves_non_duplicates():
    """Test that non-duplicate nodes are preserved."""
    from graphify_sf.build import deduplicate_by_label

    nodes = [
        {"id": "node1", "label": "ClassA"},
        {"id": "node2", "label": "ClassB"},
        {"id": "node3", "label": "ClassC"},
    ]
    edges = []

    deduped_nodes, deduped_edges = deduplicate_by_label(nodes, edges)

    assert len(deduped_nodes) == 3


def test_edge_data_returns_attributes(simple_graph):
    """Test that edge_data() returns correct edge attributes."""
    from graphify_sf.build import edge_data

    edges = list(simple_graph.edges())
    if edges:
        u, v = edges[0]
        data = edge_data(simple_graph, u, v)
        assert isinstance(data, dict)


def test_build_merge_sf_creates_graph(simple_extraction, tmp_path):
    """Test that build_merge_sf() merges new extraction into existing graph."""
    from graphify_sf.build import build_from_json, build_merge_sf

    # Create an initial graph.json
    graph_path = tmp_path / "graph.json"
    initial = build_from_json(simple_extraction)

    # Export to JSON format
    from networkx.readwrite import json_graph

    graph_data = json_graph.node_link_data(initial)
    graph_path.write_text(json.dumps(graph_data), encoding="utf-8")

    # Now merge with same extraction (should not duplicate)
    merged = build_merge_sf(simple_extraction, graph_path)

    assert isinstance(merged, nx.Graph)
    # Merged graph should have similar node count (may be slightly different due to deduplication)
    assert merged.number_of_nodes() >= initial.number_of_nodes()


def test_build_merge_sf_missing_graph(simple_extraction, tmp_path):
    """Test that build_merge_sf() creates new graph if existing one doesn't exist."""
    from graphify_sf.build import build_merge_sf

    graph_path = tmp_path / "nonexistent" / "graph.json"
    merged = build_merge_sf(simple_extraction, graph_path)

    assert isinstance(merged, nx.Graph)
    assert merged.number_of_nodes() > 0


def test_build_from_json_directed_graph(simple_extraction):
    """Test that build_from_json() can create directed graphs."""
    from graphify_sf.build import build_from_json

    G = build_from_json(simple_extraction, directed=True)

    assert isinstance(G, nx.DiGraph)
    assert G.is_directed()


def test_build_from_extraction_alias(simple_extraction):
    """Test that build_from_extraction is an alias for build_from_json."""
    from graphify_sf.build import build_from_extraction, build_from_json

    assert build_from_extraction is build_from_json


def test_build_multiple_extractions():
    """Test that build() can merge multiple extraction results."""
    from graphify_sf.build import build

    ext1 = {
        "nodes": [{"id": "n1", "label": "Node1", "file_type": "apex"}],
        "edges": [],
    }
    ext2 = {
        "nodes": [{"id": "n2", "label": "Node2", "file_type": "apex"}],
        "edges": [{"source": "n2", "target": "n1", "relation": "calls"}],
    }

    G = build([ext1, ext2])

    assert G.number_of_nodes() == 2
    assert G.number_of_edges() == 1


def test_build_skips_dangling_edges():
    """Test that edges to non-existent nodes are skipped."""
    from graphify_sf.build import build_from_json

    extraction = {
        "nodes": [{"id": "n1", "label": "Node1", "file_type": "apex"}],
        "edges": [
            {"source": "n1", "target": "n2", "relation": "calls"},  # n2 doesn't exist
        ],
    }

    G = build_from_json(extraction)

    assert G.number_of_nodes() == 1
    assert G.number_of_edges() == 0  # Dangling edge should be skipped


def test_build_normalizes_source_file_paths():
    """Test that source_file paths are normalized (backslashes → forward slashes)."""
    from graphify_sf.build import build_from_json

    extraction = {
        "nodes": [{"id": "n1", "label": "Node1", "file_type": "apex", "source_file": "path\\to\\file.cls"}],
        "edges": [],
    }

    G = build_from_json(extraction)

    node_data = G.nodes["n1"]
    assert "path/to/file.cls" in node_data["source_file"]


def test_deduplicate_removes_self_loops():
    """Test that deduplication removes self-loops."""
    from graphify_sf.build import deduplicate_by_label

    nodes = [
        {"id": "node1", "label": "TestClass"},
        {"id": "node2", "label": "testclass"},  # Duplicate
    ]
    edges = [
        {"source": "node1", "target": "node2", "relation": "calls"},  # Will become self-loop
    ]

    deduped_nodes, deduped_edges = deduplicate_by_label(nodes, edges)

    # Self-loops should be removed
    assert len(deduped_edges) == 0


# ---------------------------------------------------------------------------
# Regression: dedup must NOT merge nodes of different sf_type (0.3.6 bug fix)
# ---------------------------------------------------------------------------


def test_dedup_does_not_merge_across_sf_type():
    """A CustomObject and a CustomTab/PermissionSet that normalise to the same
    label must remain SEPARATE nodes — previously they were conflated and the
    object's edges were rewritten onto the wrong survivor."""
    from graphify_sf.build import deduplicate_by_label

    nodes = [
        {"id": "object_supporterconnection__c", "label": "SupporterConnection__c", "sf_type": "CustomObject"},
        {"id": "customtab_supporterconnection__c", "label": "SupporterConnection__c", "sf_type": "CustomTab"},
    ]
    edges = []
    deduped_nodes, _ = deduplicate_by_label(nodes, edges)
    ids = {n["id"] for n in deduped_nodes}
    assert "object_supporterconnection__c" in ids
    assert "customtab_supporterconnection__c" in ids
    assert len(deduped_nodes) == 2, "different sf_type must not merge"


def test_dedup_still_merges_same_sf_type_chunks():
    """Same-type chunked duplicates (the intended case) still merge."""
    from graphify_sf.build import deduplicate_by_label

    nodes = [
        {"id": "doc_readme", "label": "README", "sf_type": "Document"},
        {"id": "doc_readme_c1", "label": "README", "sf_type": "Document"},  # chunk
    ]
    edges = [{"source": "doc_readme_c1", "target": "doc_readme", "relation": "references"}]
    deduped_nodes, _ = deduplicate_by_label(nodes, edges)
    assert len(deduped_nodes) == 1, "same-type chunk duplicates should merge"
    assert deduped_nodes[0]["id"] == "doc_readme"


def test_self_lookup_keeps_contains_edge():
    """A self-referencing lookup field (object→field `contains` collides with
    field→object `references` in the undirected simple graph) must keep the
    `contains` ownership edge — it outranks `references`."""
    from graphify_sf.build import build_from_json

    extraction = {
        "nodes": [
            {"id": "object_account", "label": "Account", "sf_type": "CustomObject", "file_type": "object"},
            {
                "id": "field_account_parent__c",
                "label": "Account.Parent__c",
                "sf_type": "CustomField",
                "file_type": "object",
            },
        ],
        "edges": [
            {"source": "object_account", "target": "field_account_parent__c", "relation": "contains"},
            {"source": "field_account_parent__c", "target": "object_account", "relation": "references"},
        ],
    }
    G = build_from_json(extraction)  # undirected (default)
    assert G.has_edge("object_account", "field_account_parent__c")
    assert G.get_edge_data("object_account", "field_account_parent__c")["relation"] == "contains"


def test_contains_not_overwritten_regardless_of_edge_order():
    """contains must win even when the weaker relation is added second."""
    from graphify_sf.build import build_from_json

    extraction = {
        "nodes": [
            {"id": "object_x", "label": "X", "sf_type": "CustomObject"},
            {"id": "field_x_self__c", "label": "X.Self__c", "sf_type": "CustomField"},
        ],
        # references first, contains second
        "edges": [
            {"source": "field_x_self__c", "target": "object_x", "relation": "references"},
            {"source": "object_x", "target": "field_x_self__c", "relation": "contains"},
        ],
    }
    G = build_from_json(extraction)
    assert G.get_edge_data("object_x", "field_x_self__c")["relation"] == "contains"


# ---------------------------------------------------------------------------
# _ensure_stub_nodes
# ---------------------------------------------------------------------------


def test_ensure_stub_nodes_creates_object_stub():
    """_ensure_stub_nodes creates a stub CustomObject node for a missing object_ reference."""
    from graphify_sf.build import _ensure_stub_nodes

    nodes = []
    edges = [{"source": "flow_myflow", "target": "object_lead"}]
    _ensure_stub_nodes(nodes, edges)

    stub_ids = {n["id"] for n in nodes}
    assert "object_lead" in stub_ids
    stub = next(n for n in nodes if n["id"] == "object_lead")
    assert stub["sf_type"] == "CustomObject"
    assert stub.get("stub") is True


def test_ensure_stub_nodes_creates_apex_stub():
    """_ensure_stub_nodes creates a stub ApexClass node for a missing apex_ reference."""
    from graphify_sf.build import _ensure_stub_nodes

    nodes = []
    edges = [{"source": "flow_myflow", "target": "apex_accountservice"}]
    _ensure_stub_nodes(nodes, edges)

    stub_ids = {n["id"] for n in nodes}
    assert "apex_accountservice" in stub_ids
    stub = next(n for n in nodes if n["id"] == "apex_accountservice")
    assert stub["sf_type"] == "ApexClass"


def test_ensure_stub_nodes_does_not_create_stub_for_known_node():
    """_ensure_stub_nodes skips IDs that already have a real node."""
    from graphify_sf.build import _ensure_stub_nodes

    # Use a source with an unrecognised prefix so only the target is checked
    nodes = [
        {"id": "object_lead", "label": "Lead", "sf_type": "CustomObject", "file_type": "object"},
        {"id": "flow_myflow", "label": "MyFlow", "sf_type": "Flow", "file_type": "flow"},
    ]
    edges = [{"source": "flow_myflow", "target": "object_lead"}]
    original_count = len(nodes)
    _ensure_stub_nodes(nodes, edges)

    assert len(nodes) == original_count, "No new stub should be created when both nodes already exist"


def test_ensure_stub_nodes_no_stubs_for_unknown_prefix():
    """_ensure_stub_nodes ignores IDs with unrecognised prefixes."""
    from graphify_sf.build import _ensure_stub_nodes

    nodes = []
    edges = [{"source": "foo_bar", "target": "baz_qux"}]
    _ensure_stub_nodes(nodes, edges)

    assert len(nodes) == 0, "No stubs for unknown prefixes"


# ---------------------------------------------------------------------------
# _resolve_apex_calls
# ---------------------------------------------------------------------------


def test_resolve_apex_calls_creates_calls_edges():
    """_resolve_apex_calls turns _raw_calls into 'calls' edges when target class exists."""
    from graphify_sf.build import _resolve_apex_calls

    nodes = [
        {
            "id": "apex_handler",
            "label": "Handler",
            "sf_type": "ApexClass",
            "_raw_calls": [
                {"caller_id": "method_handler_run", "callee_class": "AccountService", "callee_method": "getAccounts"}
            ],
        },
        {"id": "apex_accountservice", "label": "AccountService", "sf_type": "ApexClass"},
    ]
    edges = []
    extra = _resolve_apex_calls(nodes, edges)

    call_edges = [e for e in extra if e.get("relation") == "calls"]
    assert len(call_edges) == 1
    assert call_edges[0]["source"] == "method_handler_run"
    assert "accountservice" in call_edges[0]["target"].lower()


def test_resolve_apex_calls_deduplicates():
    """_resolve_apex_calls does not emit duplicate caller→callee edges."""
    from graphify_sf.build import _resolve_apex_calls

    nodes = [
        {
            "id": "apex_handler",
            "label": "Handler",
            "sf_type": "ApexClass",
            "_raw_calls": [
                {"caller_id": "apex_handler", "callee_class": "AccountService", "callee_method": "m1"},
                {"caller_id": "apex_handler", "callee_class": "AccountService", "callee_method": "m2"},
            ],
        },
        {"id": "apex_accountservice", "label": "AccountService", "sf_type": "ApexClass"},
    ]
    edges = []
    extra = _resolve_apex_calls(nodes, edges)

    call_edges = [e for e in extra if e.get("relation") == "calls"]
    assert len(call_edges) == 1, "Duplicate caller→callee pair should be emitted only once"


# ---------------------------------------------------------------------------
# _derive_object_edges
# ---------------------------------------------------------------------------


def test_derive_object_edges_creates_object_to_object_edge():
    """_derive_object_edges derives Object→Object edge from Field→Object lookup chain."""
    from graphify_sf.build import _derive_object_edges

    nodes = [
        {"id": "object_opportunity", "sf_type": "CustomObject"},
        {"id": "field_opportunity_account__c", "sf_type": "CustomField"},
        {"id": "object_account", "sf_type": "CustomObject"},
    ]
    edges = [
        {"source": "object_opportunity", "target": "field_opportunity_account__c", "relation": "contains"},
        {"source": "field_opportunity_account__c", "target": "object_account", "relation": "references"},
    ]

    derived = _derive_object_edges(nodes, edges)
    obj_edges = [e for e in derived if e.get("relation") == "references"]
    assert len(obj_edges) == 1
    assert obj_edges[0]["source"] == "object_opportunity"
    assert obj_edges[0]["target"] == "object_account"
    assert obj_edges[0]["confidence"] == "INFERRED"


def test_derive_object_edges_skips_self_references():
    """_derive_object_edges skips when a field's parent object equals the reference target."""
    from graphify_sf.build import _derive_object_edges

    nodes = [
        {"id": "object_account", "sf_type": "CustomObject"},
        {"id": "field_account_parent__c", "sf_type": "CustomField"},
    ]
    edges = [
        {"source": "object_account", "target": "field_account_parent__c", "relation": "contains"},
        {"source": "field_account_parent__c", "target": "object_account", "relation": "references"},
    ]

    derived = _derive_object_edges(nodes, edges)
    assert len(derived) == 0, "Self-referential hierarchy should not produce Object→Object edge"


def test_derive_object_edges_skips_existing_edges():
    """_derive_object_edges does not duplicate edges that already exist."""
    from graphify_sf.build import _derive_object_edges

    nodes = [
        {"id": "object_opportunity", "sf_type": "CustomObject"},
        {"id": "field_opportunity_account__c", "sf_type": "CustomField"},
        {"id": "object_account", "sf_type": "CustomObject"},
    ]
    edges = [
        {"source": "object_opportunity", "target": "field_opportunity_account__c", "relation": "contains"},
        {"source": "field_opportunity_account__c", "target": "object_account", "relation": "references"},
        # Already have direct Object→Object edge
        {"source": "object_opportunity", "target": "object_account", "relation": "references"},
    ]

    derived = _derive_object_edges(nodes, edges)
    assert len(derived) == 0, "Should not duplicate an already-existing Object→Object edge"


# ---------------------------------------------------------------------------
# build() post-processing: _resolve_apex_calls + _derive_object_edges applied
# ---------------------------------------------------------------------------


def test_build_resolves_apex_calls():
    """build() applies _resolve_apex_calls so cross-class calls become graph edges."""
    from graphify_sf.build import build

    ext = {
        "nodes": [
            {
                "id": "apex_handler",
                "label": "Handler",
                "sf_type": "ApexClass",
                "file_type": "apex",
                "_raw_calls": [{"caller_id": "apex_handler", "callee_class": "AccountService", "callee_method": "run"}],
            },
            {"id": "apex_accountservice", "label": "AccountService", "sf_type": "ApexClass", "file_type": "apex"},
        ],
        "edges": [],
    }

    G = build([ext])
    # Should have an edge between the two Apex classes
    assert G.has_edge("apex_handler", "apex_accountservice") or any(
        d.get("relation") == "calls" for _, _, d in G.edges(data=True)
    )


def test_build_derives_object_to_object_edges():
    """build() applies _derive_object_edges to add Object→Object edges."""
    from graphify_sf.build import build

    ext = {
        "nodes": [
            {"id": "object_opportunity", "label": "Opportunity", "sf_type": "CustomObject", "file_type": "object"},
            {
                "id": "field_opportunity_account__c",
                "label": "Opportunity.Account__c",
                "sf_type": "CustomField",
                "file_type": "object",
            },
            {"id": "object_account", "label": "Account", "sf_type": "CustomObject", "file_type": "object"},
        ],
        "edges": [
            {
                "source": "object_opportunity",
                "target": "field_opportunity_account__c",
                "relation": "contains",
                "confidence": "EXTRACTED",
            },
            {
                "source": "field_opportunity_account__c",
                "target": "object_account",
                "relation": "references",
                "confidence": "EXTRACTED",
            },
        ],
    }

    G = build([ext])
    # object_opportunity → object_account derived edge should exist
    assert G.has_edge("object_opportunity", "object_account")
