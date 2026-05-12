"""Tests for graph analysis."""
from __future__ import annotations

import networkx as nx


def test_god_nodes_returns_list(simple_graph):
    """Test that god_nodes() returns a list of high-degree nodes."""
    from graphify_sf.analyze import god_nodes

    gods = god_nodes(simple_graph, top_n=5)

    assert isinstance(gods, list)
    assert len(gods) <= 5


def test_god_nodes_have_required_fields(simple_graph):
    """Test that god nodes have required attributes."""
    from graphify_sf.analyze import god_nodes

    gods = god_nodes(simple_graph, top_n=5)

    if gods:
        for node in gods:
            assert "id" in node
            assert "label" in node
            assert "degree" in node
            assert "sf_type" in node


def test_god_nodes_sorted_by_degree(simple_graph):
    """Test that god nodes are sorted by degree (descending)."""
    from graphify_sf.analyze import god_nodes

    gods = god_nodes(simple_graph, top_n=10)

    if len(gods) > 1:
        degrees = [n["degree"] for n in gods]
        assert degrees == sorted(degrees, reverse=True)


def test_god_nodes_excludes_method_stubs():
    """Test that low-degree method nodes are excluded."""
    from graphify_sf.analyze import god_nodes

    G = nx.Graph()
    G.add_node("class1", label="Class1", sf_type="ApexClass")
    G.add_node("method1", label="method1", sf_type="ApexMethod")
    G.add_edge("class1", "method1")

    gods = god_nodes(G, top_n=10)

    # Method with only 1 connection should be filtered
    labels = [n["label"] for n in gods]
    assert "method1" not in labels


def test_surprising_connections_returns_list(simple_graph, simple_communities):
    """Test that surprising_connections() returns a list."""
    from graphify_sf.analyze import surprising_connections

    surprises = surprising_connections(simple_graph, simple_communities, top_n=5)

    assert isinstance(surprises, list)


def test_surprising_connections_have_required_fields(simple_graph, simple_communities):
    """Test that surprising connections have required attributes."""
    from graphify_sf.analyze import surprising_connections

    surprises = surprising_connections(simple_graph, simple_communities, top_n=5)

    if surprises:
        for conn in surprises:
            assert "source" in conn
            assert "target" in conn
            assert "confidence" in conn or "relation" in conn


def test_suggest_questions_returns_list(simple_graph, simple_communities):
    """Test that suggest_questions() returns a list of questions."""
    from graphify_sf.analyze import suggest_questions

    labels = {cid: f"Community {cid}" for cid in simple_communities}
    questions = suggest_questions(simple_graph, simple_communities, labels, top_n=7)

    assert isinstance(questions, list)
    assert len(questions) <= 7


def test_suggest_questions_have_structure(simple_graph, simple_communities):
    """Test that questions have expected structure."""
    from graphify_sf.analyze import suggest_questions

    labels = {cid: f"Community {cid}" for cid in simple_communities}
    questions = suggest_questions(simple_graph, simple_communities, labels, top_n=5)

    if questions:
        for q in questions:
            assert "type" in q
            assert "question" in q or q["type"] == "no_signal"
            assert "why" in q


def test_graph_diff_detects_new_nodes():
    """Test that graph_diff() detects new nodes."""
    from graphify_sf.analyze import graph_diff

    G_old = nx.Graph()
    G_old.add_node("n1", label="Node1")

    G_new = nx.Graph()
    G_new.add_node("n1", label="Node1")
    G_new.add_node("n2", label="Node2")

    diff = graph_diff(G_old, G_new)

    assert len(diff["new_nodes"]) == 1
    assert diff["new_nodes"][0]["id"] == "n2"


def test_graph_diff_detects_removed_nodes():
    """Test that graph_diff() detects removed nodes."""
    from graphify_sf.analyze import graph_diff

    G_old = nx.Graph()
    G_old.add_node("n1", label="Node1")
    G_old.add_node("n2", label="Node2")

    G_new = nx.Graph()
    G_new.add_node("n1", label="Node1")

    diff = graph_diff(G_old, G_new)

    assert len(diff["removed_nodes"]) == 1
    assert diff["removed_nodes"][0]["id"] == "n2"


def test_graph_diff_detects_new_edges():
    """Test that graph_diff() detects new edges."""
    from graphify_sf.analyze import graph_diff

    G_old = nx.Graph()
    G_old.add_edge("n1", "n2")

    G_new = nx.Graph()
    G_new.add_edge("n1", "n2")
    G_new.add_edge("n2", "n3")

    diff = graph_diff(G_old, G_new)

    assert len(diff["new_edges"]) == 1


def test_graph_diff_detects_removed_edges():
    """Test that graph_diff() detects removed edges."""
    from graphify_sf.analyze import graph_diff

    G_old = nx.Graph()
    G_old.add_edge("n1", "n2")
    G_old.add_edge("n2", "n3")

    G_new = nx.Graph()
    G_new.add_edge("n1", "n2")

    diff = graph_diff(G_old, G_new)

    assert len(diff["removed_edges"]) == 1


def test_graph_diff_summary_message():
    """Test that graph_diff() generates a summary message."""
    from graphify_sf.analyze import graph_diff

    G_old = nx.Graph()
    G_old.add_node("n1")

    G_new = nx.Graph()
    G_new.add_node("n1")
    G_new.add_node("n2")

    diff = graph_diff(G_old, G_new)

    assert "summary" in diff
    assert "new node" in diff["summary"]


def test_graph_diff_no_changes():
    """Test that graph_diff() handles identical graphs."""
    from graphify_sf.analyze import graph_diff

    G_old = nx.Graph()
    G_old.add_edge("n1", "n2")

    G_new = nx.Graph()
    G_new.add_edge("n1", "n2")

    diff = graph_diff(G_old, G_new)

    assert diff["summary"] == "no changes"


def test_sf_type_category_mapping():
    """Test that SF type categories are correctly mapped."""
    from graphify_sf.analyze import _sf_type_category

    assert _sf_type_category("apex") == "code"
    assert _sf_type_category("trigger") == "code"
    assert _sf_type_category("flow") == "automation"
    assert _sf_type_category("object") == "schema"
    assert _sf_type_category("lwc") == "ui"
    assert _sf_type_category("profile") == "security"
    assert _sf_type_category("unknown") == "other"


def test_is_file_node_excludes_low_degree_methods():
    """Test that _is_file_node() identifies method stubs correctly."""
    from graphify_sf.analyze import _is_file_node

    G = nx.Graph()
    G.add_node("method1", sf_type="ApexMethod", label="method1")
    G.add_node("class1", sf_type="ApexClass", label="Class1")
    G.add_edge("class1", "method1")

    # Method with degree 1 should be considered a file node
    assert _is_file_node(G, "method1") is True
    assert _is_file_node(G, "class1") is False


def test_is_concept_node_empty_source():
    """Test that _is_concept_node() identifies concept nodes."""
    from graphify_sf.analyze import _is_concept_node

    G = nx.Graph()
    G.add_node("concept1", source_file="")
    G.add_node("real1", source_file="/path/to/file.cls")

    assert _is_concept_node(G, "concept1") is True
    assert _is_concept_node(G, "real1") is False


def test_surprising_connections_empty_graph():
    """Test that surprising_connections() handles empty graphs."""
    from graphify_sf.analyze import surprising_connections

    G = nx.Graph()
    surprises = surprising_connections(G, {}, top_n=5)

    assert isinstance(surprises, list)
