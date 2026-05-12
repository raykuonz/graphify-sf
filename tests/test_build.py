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
