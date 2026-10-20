"""Community detection on NetworkX graphs.

Uses Leiden (graspologic-native) if available, falls back to Louvain (networkx).
Splits oversized communities. Returns cohesion scores.

Adapted from Graphify's cluster.py — logic is identical; just updated
module name in docstrings.
"""

from __future__ import annotations

import contextlib
import inspect
import io
import sys

import networkx as nx


def _suppress_output():
    """Context manager to suppress stdout/stderr during library calls."""
    return contextlib.redirect_stdout(io.StringIO())


def _leiden_edge_list(G: nx.Graph) -> list[tuple[str, str, float]]:
    """Collapse G into one weighted edge per unordered node pair, keyed by str ids.

    graspologic-native keeps only the first weight it sees for a pair (later
    duplicates, including the reversed pair, are dropped), so parallel edges are
    summed here — the same treatment Louvain gives multigraphs. Self-loops are
    skipped. Sorted, so the result never depends on G's iteration order (which,
    for small networkx subgraph views, follows Python's randomized str hashing).
    """
    weights: dict[tuple[str, str], float] = {}
    for u, v, w in G.edges(data="weight", default=1.0):
        su, sv = str(u), str(v)
        if su == sv:
            continue
        pair = (su, sv) if su < sv else (sv, su)
        weights[pair] = weights.get(pair, 0.0) + float(w)
    return sorted((a, b, w) for (a, b), w in weights.items())


def _partition(G: nx.Graph) -> dict[str, int]:
    """Run community detection. Returns {node_id: community_id}.

    Tries Leiden (graspologic-native) first — best quality.
    Falls back to Louvain (built into networkx) if graspologic-native is not installed.
    """
    try:
        from graspologic_native import leiden

        edges = _leiden_edge_list(G)
        native: dict[str, int] = {}
        if edges:
            old_stderr = sys.stderr
            try:
                sys.stderr = io.StringIO()
                with _suppress_output():
                    _, native = leiden(
                        edges=edges,
                        resolution=1.0,
                        randomness=0.001,
                        iterations=1,
                        use_modularity=True,
                        seed=42,
                        trials=1,
                    )
            finally:
                sys.stderr = old_stderr
        # Relabel in sorted-id order: the engine's own labels (and dict order) vary
        # between runs even with a fixed seed, which would reshuffle cluster()'s
        # size-tie ordering. Nodes whose only edges are self-loops never reach the
        # engine and get a community of their own.
        labels: dict[object, int] = {}
        return {
            n: labels.setdefault(native.get(str(n), ("self-loop", n)), len(labels)) for n in sorted(G.nodes(), key=str)
        }
    except ImportError:
        pass

    kwargs: dict = {"seed": 42, "threshold": 1e-4}
    if "max_level" in inspect.signature(nx.community.louvain_communities).parameters:
        kwargs["max_level"] = 10
    communities = nx.community.louvain_communities(G, **kwargs)
    return {node: cid for cid, nodes in enumerate(communities) for node in nodes}


_MAX_COMMUNITY_FRACTION = 0.25
_MIN_SPLIT_SIZE = 10
_COHESION_SPLIT_THRESHOLD = 0.05
_COHESION_SPLIT_MIN_SIZE = 50


def cluster(G: nx.Graph) -> dict[int, list[str]]:
    """Run Leiden community detection. Returns {community_id: [node_ids]}.

    Community IDs are stable across runs: 0 = largest community after splitting.
    Oversized communities (> 25% of graph nodes, min 10) are split by running
    a second Leiden pass on the subgraph.

    Accepts directed or undirected graphs. DiGraphs are converted to undirected
    internally since Louvain/Leiden require undirected input.
    """
    if G.number_of_nodes() == 0:
        return {}
    if G.is_directed():
        G = G.to_undirected()
    if G.number_of_edges() == 0:
        return {i: [n] for i, n in enumerate(sorted(G.nodes))}

    isolates = [n for n in G.nodes() if G.degree(n) == 0]
    connected_nodes = [n for n in G.nodes() if G.degree(n) > 0]
    connected = G.subgraph(connected_nodes)

    raw: dict[int, list[str]] = {}
    if connected.number_of_nodes() > 0:
        partition = _partition(connected)
        for node, cid in partition.items():
            raw.setdefault(cid, []).append(node)

    next_cid = max(raw.keys(), default=-1) + 1
    for node in isolates:
        raw[next_cid] = [node]
        next_cid += 1

    max_size = max(_MIN_SPLIT_SIZE, int(G.number_of_nodes() * _MAX_COMMUNITY_FRACTION))
    final_communities: list[list[str]] = []
    for nodes in raw.values():
        if len(nodes) > max_size:
            final_communities.extend(_split_community(G, nodes))
        else:
            final_communities.append(nodes)

    second_pass: list[list[str]] = []
    for nodes in final_communities:
        if len(nodes) >= _COHESION_SPLIT_MIN_SIZE and cohesion_score(G, nodes) < _COHESION_SPLIT_THRESHOLD:
            splits = _split_community(G, nodes)
            second_pass.extend(splits if len(splits) > 1 else [nodes])
        else:
            second_pass.append(nodes)
    final_communities = second_pass

    final_communities.sort(key=len, reverse=True)
    return {i: sorted(nodes) for i, nodes in enumerate(final_communities)}


def _split_community(G: nx.Graph, nodes: list[str]) -> list[list[str]]:
    """Run a second Leiden pass on a community subgraph to split it further."""
    subgraph = G.subgraph(nodes)
    if subgraph.number_of_edges() == 0:
        return [[n] for n in sorted(nodes)]
    try:
        sub_partition = _partition(subgraph)
        sub_communities: dict[int, list[str]] = {}
        for node, cid in sub_partition.items():
            sub_communities.setdefault(cid, []).append(node)
        if len(sub_communities) <= 1:
            return [sorted(nodes)]
        return [sorted(v) for v in sub_communities.values()]
    except Exception:
        return [sorted(nodes)]


def cohesion_score(G: nx.Graph, community_nodes: list[str]) -> float:
    """Ratio of actual intra-community edges to maximum possible.

    Normalises to a simple undirected view so the result stays in [0, 1]
    regardless of whether G is a MultiDiGraph (0.4.0 default) or a plain Graph.
    """
    n = len(community_nodes)
    if n <= 1:
        return 1.0
    subgraph = G.subgraph(community_nodes)
    # Collapse parallel/directed edges to get a consistent density measure.
    simple = nx.Graph(subgraph)
    actual = simple.number_of_edges()
    possible = n * (n - 1) / 2
    return round(actual / possible, 2) if possible > 0 else 0.0


def score_all(G: nx.Graph, communities: dict[int, list[str]]) -> dict[int, float]:
    return {cid: cohesion_score(G, nodes) for cid, nodes in communities.items()}
