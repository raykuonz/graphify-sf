"""Graph analysis: god nodes (most connected), surprising connections
(cross-community), suggested questions.

Adapted from Graphify's analyze.py — replaced language-family and
file-category logic with Salesforce metadata type awareness.
"""

from __future__ import annotations

import networkx as nx

from graphify_sf.build import edge_data

# SF metadata file-type to category mapping
_SF_TYPE_CATEGORY: dict[str, str] = {
    "apex": "code",
    "trigger": "code",
    "flow": "automation",
    "automation": "automation",
    "object": "schema",
    "field": "schema",
    "visualforce": "ui",
    "lwc": "ui",
    "aura": "ui",
    "layout": "ui",
    "profile": "security",
    "permset": "security",
    "config": "config",
}


def _sf_type_category(file_type: str) -> str:
    """Return the high-level category for an SF metadata file_type."""
    return _SF_TYPE_CATEGORY.get((file_type or "").lower(), "other")


def _node_community_map(communities: dict[int, list[str]]) -> dict[str, int]:
    """Invert communities dict: node_id -> community_id."""
    return {n: cid for cid, nodes in communities.items() for n in nodes}


def _is_file_node(G: nx.Graph, node_id: str) -> bool:
    """Return True if this node is a low-value structural node that should be
    excluded from god-node / surprising-connection / knowledge-gap reporting.

    For Salesforce metadata:
    - ApexMethod nodes that only have a `contains` edge from their parent class
      are structural noise (the class is the meaningful entity, not the method stub)
    """
    attrs = G.nodes[node_id]
    sf_type = attrs.get("sf_type", "")

    # Method stubs with only contains edge
    if sf_type in ("ApexMethod", "LWCMethod"):
        if G.degree(node_id) <= 1:
            return True

    return False


def _is_concept_node(G: nx.Graph, node_id: str) -> bool:
    """Return True if this node is a semantic concept rather than a real SF entity.

    Signals:
    - Empty source_file
    - source_file has no file extension
    """
    data = G.nodes[node_id]
    source = data.get("source_file", "")
    if not source:
        return True
    if "." not in source.split("/")[-1]:
        return True
    return False


def god_nodes(G: nx.Graph, top_n: int = 10) -> list[dict]:
    """Return the top_n most-connected real SF entities - the core abstractions.

    Method stubs and concept nodes are excluded.
    """
    degree = dict(G.degree())
    sorted_nodes = sorted(degree.items(), key=lambda x: x[1], reverse=True)
    result = []
    for node_id, deg in sorted_nodes:
        if _is_file_node(G, node_id) or _is_concept_node(G, node_id):
            continue
        result.append(
            {
                "id": node_id,
                "label": G.nodes[node_id].get("label", node_id),
                "degree": deg,
                "sf_type": G.nodes[node_id].get("sf_type", ""),
            }
        )
        if len(result) >= top_n:
            break
    return result


def surprising_connections(
    G: nx.Graph,
    communities: dict[int, list[str]] | None = None,
    top_n: int = 5,
) -> list[dict]:
    """Find connections that are genuinely surprising.

    Strategy:
    - Multi-file corpora: cross-file edges between real entities, ranked by a
      composite surprise score.
    - Single-file / single-source: cross-community edges (betweenness-based).
    """
    source_files = {data.get("source_file", "") for _, data in G.nodes(data=True) if data.get("source_file", "")}
    is_multi_source = len(source_files) > 1

    if is_multi_source:
        return _cross_file_surprises(G, communities or {}, top_n)
    else:
        return _cross_community_surprises(G, communities or {}, top_n)


def _surprise_score(
    G: nx.Graph,
    u: str,
    v: str,
    data: dict,
    node_community: dict[str, int],
    u_type: str,
    v_type: str,
) -> tuple[int, list[str]]:
    """Score how surprising a cross-file edge is. Returns (score, reasons)."""
    score = 0
    reasons: list[str] = []

    conf = data.get("confidence", "EXTRACTED")
    conf_bonus = {"AMBIGUOUS": 3, "INFERRED": 2, "EXTRACTED": 1}.get(conf, 1)
    score += conf_bonus
    if conf in ("AMBIGUOUS", "INFERRED"):
        reasons.append(f"{conf.lower()} connection - not explicitly stated in source")

    # Cross SF-type-category bonus
    cat_u = _sf_type_category(u_type)
    cat_v = _sf_type_category(v_type)
    if cat_u != cat_v:
        score += 2
        reasons.append(f"crosses metadata categories ({cat_u} ↔ {cat_v})")

    # Cross-community bonus
    cid_u = node_community.get(u)
    cid_v = node_community.get(v)
    if cid_u is not None and cid_v is not None and cid_u != cid_v:
        score += 1
        reasons.append("bridges separate communities")

    # Peripheral→hub
    deg_u = G.degree(u)
    deg_v = G.degree(v)
    if min(deg_u, deg_v) <= 2 and max(deg_u, deg_v) >= 5:
        score += 1
        peripheral = G.nodes[u].get("label", u) if deg_u <= 2 else G.nodes[v].get("label", v)
        hub = G.nodes[v].get("label", v) if deg_u <= 2 else G.nodes[u].get("label", u)
        reasons.append(f"peripheral node `{peripheral}` unexpectedly reaches hub `{hub}`")

    return score, reasons


def _cross_file_surprises(G: nx.Graph, communities: dict[int, list[str]], top_n: int) -> list[dict]:
    """Cross-file edges between real entities, ranked by composite surprise score."""
    node_community = _node_community_map(communities)
    candidates = []

    for u, v, data in G.edges(data=True):
        relation = data.get("relation", "")
        if relation in ("contains", "method"):
            continue
        if _is_concept_node(G, u) or _is_concept_node(G, v):
            continue
        if _is_file_node(G, u) or _is_file_node(G, v):
            continue

        u_source = G.nodes[u].get("source_file", "")
        v_source = G.nodes[v].get("source_file", "")

        if not u_source or not v_source or u_source == v_source:
            continue

        u_type = G.nodes[u].get("file_type", "")
        v_type = G.nodes[v].get("file_type", "")

        score, reasons = _surprise_score(G, u, v, data, node_community, u_type, v_type)
        src_id = data.get("_src", u)
        if src_id not in G.nodes:
            src_id = u
        tgt_id = data.get("_tgt", v)
        if tgt_id not in G.nodes:
            tgt_id = v
        candidates.append(
            {
                "_score": score,
                "source": G.nodes[src_id].get("label", src_id),
                "target": G.nodes[tgt_id].get("label", tgt_id),
                "source_files": [
                    G.nodes[src_id].get("source_file", ""),
                    G.nodes[tgt_id].get("source_file", ""),
                ],
                "confidence": data.get("confidence", "EXTRACTED"),
                "relation": relation,
                "why": "; ".join(reasons) if reasons else "cross-file SF metadata connection",
            }
        )

    candidates.sort(key=lambda x: x["_score"], reverse=True)
    for c in candidates:
        c.pop("_score")

    if candidates:
        return candidates[:top_n]

    return _cross_community_surprises(G, communities, top_n)


def _cross_community_surprises(
    G: nx.Graph,
    communities: dict[int, list[str]],
    top_n: int,
) -> list[dict]:
    """Find edges that bridge different communities for single-source corpora."""
    if not communities:
        if G.number_of_edges() == 0:
            return []
        if G.number_of_nodes() > 5000:
            return []
        betweenness = nx.edge_betweenness_centrality(G)
        top_edges = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)[:top_n]
        result = []
        for (u, v), score in top_edges:
            data = edge_data(G, u, v)
            result.append(
                {
                    "source": G.nodes[u].get("label", u),
                    "target": G.nodes[v].get("label", v),
                    "source_files": [
                        G.nodes[u].get("source_file", ""),
                        G.nodes[v].get("source_file", ""),
                    ],
                    "confidence": data.get("confidence", "EXTRACTED"),
                    "relation": data.get("relation", ""),
                    "note": f"Bridges graph structure (betweenness={score:.3f})",
                }
            )
        return result

    node_community = _node_community_map(communities)
    surprises = []
    for u, v, data in G.edges(data=True):
        cid_u = node_community.get(u)
        cid_v = node_community.get(v)
        if cid_u is None or cid_v is None or cid_u == cid_v:
            continue
        if _is_file_node(G, u) or _is_file_node(G, v):
            continue
        relation = data.get("relation", "")
        if relation in ("contains", "method"):
            continue
        confidence = data.get("confidence", "EXTRACTED")
        src_id = data.get("_src", u)
        if src_id not in G.nodes:
            src_id = u
        tgt_id = data.get("_tgt", v)
        if tgt_id not in G.nodes:
            tgt_id = v
        surprises.append(
            {
                "source": G.nodes[src_id].get("label", src_id),
                "target": G.nodes[tgt_id].get("label", tgt_id),
                "source_files": [
                    G.nodes[src_id].get("source_file", ""),
                    G.nodes[tgt_id].get("source_file", ""),
                ],
                "confidence": confidence,
                "relation": relation,
                "note": f"Bridges community {cid_u} → community {cid_v}",
                "_pair": tuple(sorted([cid_u, cid_v])),
            }
        )

    order = {"AMBIGUOUS": 0, "INFERRED": 1, "EXTRACTED": 2}
    surprises.sort(key=lambda x: order.get(x["confidence"], 3))

    seen_pairs: set[tuple] = set()
    deduped = []
    for s in surprises:
        pair = s.pop("_pair")
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            deduped.append(s)
    return deduped[:top_n]


def suggest_questions(
    G: nx.Graph,
    communities: dict[int, list[str]],
    community_labels: dict[int, str],
    top_n: int = 7,
) -> list[dict]:
    """Generate questions the graph is uniquely positioned to answer.

    Based on: AMBIGUOUS edges, bridge nodes, underexplored god nodes, isolated nodes.
    """
    questions = []
    node_community = _node_community_map(communities)

    # 1. AMBIGUOUS edges → unresolved relationship questions
    for u, v, data in G.edges(data=True):
        if data.get("confidence") == "AMBIGUOUS":
            ul = G.nodes[u].get("label", u)
            vl = G.nodes[v].get("label", v)
            relation = data.get("relation", "related to")
            questions.append(
                {
                    "type": "ambiguous_edge",
                    "question": f"What is the exact relationship between `{ul}` and `{vl}`?",
                    "why": f"Edge tagged AMBIGUOUS (relation: {relation}) - confidence is low.",
                }
            )

    # 2. Bridge nodes → cross-cutting concern questions
    if G.number_of_edges() > 0:
        k = min(100, G.number_of_nodes()) if G.number_of_nodes() > 1000 else None
        betweenness = nx.betweenness_centrality(G, k=k, seed=42)
        bridges = sorted(
            [
                (n, s)
                for n, s in betweenness.items()
                if not _is_file_node(G, n) and not _is_concept_node(G, n) and s > 0
            ],
            key=lambda x: x[1],
            reverse=True,
        )[:3]
        for node_id, score in bridges:
            label = G.nodes[node_id].get("label", node_id)
            cid = node_community.get(node_id)
            comm_label = community_labels.get(cid, f"Community {cid}") if cid is not None else "unknown"
            neighbors = list(G.neighbors(node_id))
            neighbor_comms = {node_community.get(n) for n in neighbors if node_community.get(n) != cid}
            if neighbor_comms:
                other_labels = [community_labels.get(c, f"Community {c}") for c in neighbor_comms]
                questions.append(
                    {
                        "type": "bridge_node",
                        "question": f"Why does `{label}` connect `{comm_label}` to {', '.join(f'`{lbl}`' for lbl in other_labels)}?",
                        "why": f"High betweenness centrality ({score:.3f}) - cross-community bridge.",
                    }
                )

    # 3. God nodes with many INFERRED edges → verification questions
    degree = dict(G.degree())
    top_nodes = sorted(
        [(n, d) for n, d in degree.items() if not _is_file_node(G, n)],
        key=lambda x: x[1],
        reverse=True,
    )[:5]
    for node_id, _ in top_nodes:
        inferred = [(u, v, d) for u, v, d in G.edges(node_id, data=True) if d.get("confidence") == "INFERRED"]
        if len(inferred) >= 2:
            label = G.nodes[node_id].get("label", node_id)
            others = []
            for u, v, d in inferred[:2]:
                src_id = d.get("_src", u)
                if src_id not in G.nodes:
                    src_id = u
                tgt_id = d.get("_tgt", v)
                if tgt_id not in G.nodes:
                    tgt_id = v
                other_id = tgt_id if src_id == node_id else src_id
                others.append(G.nodes[other_id].get("label", other_id))
            questions.append(
                {
                    "type": "verify_inferred",
                    "question": f"Are the {len(inferred)} inferred relationships involving `{label}` (e.g. with `{others[0]}` and `{others[1]}`) actually correct?",
                    "why": f"`{label}` has {len(inferred)} INFERRED edges - static-analysis inferences that need verification.",
                }
            )

    # 4. Isolated nodes → exploration questions
    isolated = [n for n in G.nodes() if G.degree(n) <= 1 and not _is_file_node(G, n) and not _is_concept_node(G, n)]
    if isolated:
        labels = [G.nodes[n].get("label", n) for n in isolated[:3]]
        questions.append(
            {
                "type": "isolated_nodes",
                "question": f"What connects {', '.join(f'`{lbl}`' for lbl in labels)} to the rest of the system?",
                "why": f"{len(isolated)} weakly-connected nodes found - possible missing edges or undocumented components.",
            }
        )

    # 5. Low-cohesion communities → structural questions
    from graphify_sf.cluster import cohesion_score

    for cid, nodes in communities.items():
        score = cohesion_score(G, nodes)
        if score < 0.15 and len(nodes) >= 5:
            label = community_labels.get(cid, f"Community {cid}")
            questions.append(
                {
                    "type": "low_cohesion",
                    "question": f"Should `{label}` be split into smaller, more focused components?",
                    "why": f"Cohesion score {score} - nodes in this community are weakly interconnected.",
                }
            )

    if not questions:
        return [
            {
                "type": "no_signal",
                "question": None,
                "why": (
                    "Not enough signal to generate questions. "
                    "This usually means the corpus has no AMBIGUOUS edges, no bridge nodes, "
                    "no INFERRED relationships, and all communities are tightly cohesive."
                ),
            }
        ]

    return questions[:top_n]


def graph_diff(G_old: nx.Graph, G_new: nx.Graph) -> dict:
    """Compare two graph snapshots and return what changed."""
    old_nodes = set(G_old.nodes())
    new_nodes = set(G_new.nodes())

    added_node_ids = new_nodes - old_nodes
    removed_node_ids = old_nodes - new_nodes

    new_nodes_list = [{"id": n, "label": G_new.nodes[n].get("label", n)} for n in added_node_ids]
    removed_nodes_list = [{"id": n, "label": G_old.nodes[n].get("label", n)} for n in removed_node_ids]

    def edge_key(G: nx.Graph, u: str, v: str, data: dict) -> tuple:
        if G.is_directed():
            return (u, v, data.get("relation", ""))
        return (min(u, v), max(u, v), data.get("relation", ""))

    old_edge_keys = {edge_key(G_old, u, v, d) for u, v, d in G_old.edges(data=True)}
    new_edge_keys = {edge_key(G_new, u, v, d) for u, v, d in G_new.edges(data=True)}

    added_edge_keys = new_edge_keys - old_edge_keys
    removed_edge_keys = old_edge_keys - new_edge_keys

    new_edges_list = []
    for u, v, d in G_new.edges(data=True):
        if edge_key(G_new, u, v, d) in added_edge_keys:
            new_edges_list.append(
                {
                    "source": u,
                    "target": v,
                    "relation": d.get("relation", ""),
                    "confidence": d.get("confidence", ""),
                }
            )

    removed_edges_list = []
    for u, v, d in G_old.edges(data=True):
        if edge_key(G_old, u, v, d) in removed_edge_keys:
            removed_edges_list.append(
                {
                    "source": u,
                    "target": v,
                    "relation": d.get("relation", ""),
                    "confidence": d.get("confidence", ""),
                }
            )

    parts = []
    if new_nodes_list:
        parts.append(f"{len(new_nodes_list)} new node{'s' if len(new_nodes_list) != 1 else ''}")
    if new_edges_list:
        parts.append(f"{len(new_edges_list)} new edge{'s' if len(new_edges_list) != 1 else ''}")
    if removed_nodes_list:
        parts.append(f"{len(removed_nodes_list)} node{'s' if len(removed_nodes_list) != 1 else ''} removed")
    if removed_edges_list:
        parts.append(f"{len(removed_edges_list)} edge{'s' if len(removed_edges_list) != 1 else ''} removed")
    summary = ", ".join(parts) if parts else "no changes"

    return {
        "new_nodes": new_nodes_list,
        "removed_nodes": removed_nodes_list,
        "new_edges": new_edges_list,
        "removed_edges": removed_edges_list,
        "summary": summary,
    }
