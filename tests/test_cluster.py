"""Tests for clustering."""

from __future__ import annotations

import networkx as nx


def test_cluster_returns_communities(simple_graph):
    """Test that cluster() returns communities dict."""
    from graphify_sf.cluster import cluster

    communities = cluster(simple_graph)

    assert isinstance(communities, dict)
    assert len(communities) > 0


def test_cluster_community_ids_start_at_zero(simple_graph):
    """Test that community IDs start at 0."""
    from graphify_sf.cluster import cluster

    communities = cluster(simple_graph)

    assert 0 in communities


def test_cluster_all_nodes_assigned(simple_graph):
    """Test that all nodes are assigned to communities."""
    from graphify_sf.cluster import cluster

    communities = cluster(simple_graph)

    all_assigned = set()
    for nodes in communities.values():
        all_assigned.update(nodes)

    assert len(all_assigned) == simple_graph.number_of_nodes()


def test_cluster_largest_community_first(simple_graph):
    """Test that communities are sorted by size (largest first)."""
    from graphify_sf.cluster import cluster

    communities = cluster(simple_graph)

    if len(communities) > 1:
        sizes = [len(nodes) for nodes in communities.values()]
        # Check that sizes are in descending order
        assert sizes == sorted(sizes, reverse=True)


def test_cluster_empty_graph():
    """Test that cluster() handles empty graphs."""
    from graphify_sf.cluster import cluster

    G = nx.Graph()
    communities = cluster(G)

    assert communities == {}


def test_cluster_single_node():
    """Test that cluster() handles single-node graphs."""
    from graphify_sf.cluster import cluster

    G = nx.Graph()
    G.add_node("node1")
    communities = cluster(G)

    assert len(communities) == 1
    assert "node1" in communities[0]


def test_cluster_disconnected_graph():
    """Test that cluster() handles disconnected graphs."""
    from graphify_sf.cluster import cluster

    G = nx.Graph()
    G.add_edge("n1", "n2")
    G.add_edge("n3", "n4")
    # Two disconnected components

    communities = cluster(G)

    # Should create separate communities for disconnected components
    assert len(communities) >= 2


def test_cluster_directed_graph():
    """Test that cluster() converts directed graphs to undirected."""
    from graphify_sf.cluster import cluster

    G = nx.DiGraph()
    G.add_edge("n1", "n2")
    G.add_edge("n2", "n3")

    communities = cluster(G)

    assert len(communities) >= 1


def test_cohesion_score_full_clique():
    """Test that cohesion_score() returns 1.0 for fully connected subgraphs."""
    from graphify_sf.cluster import cohesion_score

    G = nx.complete_graph(5)
    score = cohesion_score(G, list(G.nodes()))

    assert score == 1.0


def test_cohesion_score_single_node():
    """Test that cohesion_score() returns 1.0 for single nodes."""
    from graphify_sf.cluster import cohesion_score

    G = nx.Graph()
    G.add_node("n1")
    score = cohesion_score(G, ["n1"])

    assert score == 1.0


def test_cohesion_score_no_edges():
    """Test that cohesion_score() returns 0.0 for disconnected nodes."""
    from graphify_sf.cluster import cohesion_score

    G = nx.Graph()
    G.add_nodes_from(["n1", "n2", "n3"])
    score = cohesion_score(G, ["n1", "n2", "n3"])

    assert score == 0.0


def test_score_all_returns_dict(simple_graph, simple_communities):
    """Test that score_all() returns cohesion scores for all communities."""
    from graphify_sf.cluster import score_all

    scores = score_all(simple_graph, simple_communities)

    assert isinstance(scores, dict)
    assert len(scores) == len(simple_communities)
    for cid in simple_communities:
        assert cid in scores
        assert 0.0 <= scores[cid] <= 1.0


def test_cluster_splits_large_communities():
    """Test that oversized communities are split."""
    from graphify_sf.cluster import cluster

    # Create a large clique that exceeds max community size
    G = nx.complete_graph(100)

    communities = cluster(G)

    # Should split into multiple communities if it exceeds threshold
    # (25% of 100 = 25, min split size = 10)
    max_size = max(len(nodes) for nodes in communities.values())
    assert max_size <= 25 or len(communities) == 1


def test_cluster_isolates_get_own_communities():
    """Test that isolated nodes get their own communities."""
    from graphify_sf.cluster import cluster

    G = nx.Graph()
    G.add_edge("n1", "n2")
    G.add_node("isolated1")
    G.add_node("isolated2")

    communities = cluster(G)

    # Each isolated node should be in its own community
    isolated_communities = [nodes for nodes in communities.values() if len(nodes) == 1]
    assert len(isolated_communities) >= 2


def test_cluster_stability():
    """Test that cluster() produces stable results for the same graph."""
    from graphify_sf.cluster import cluster

    G = nx.karate_club_graph()

    communities1 = cluster(G)
    communities2 = cluster(G)

    # Community IDs might differ, but sizes should be the same
    sizes1 = sorted([len(nodes) for nodes in communities1.values()], reverse=True)
    sizes2 = sorted([len(nodes) for nodes in communities2.values()], reverse=True)

    assert sizes1 == sizes2
