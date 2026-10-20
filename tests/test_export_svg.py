"""SVG export ([svg] extra). Skipped unless matplotlib is installed."""

from __future__ import annotations

import networkx as nx
import pytest


@pytest.mark.parametrize("n", [20, 250])  # spring_layout branch; kamada_kawai_layout branch (needs scipy)
def test_to_svg_writes_svg(tmp_path, n):
    pytest.importorskip("matplotlib")
    from graphify_sf.export import to_svg

    G = nx.MultiDiGraph()
    for i in range(n):
        G.add_node(f"n{i}", label=f"N{i}", sf_type="ApexClass")
    for i in range(n - 1):
        G.add_edge(f"n{i}", f"n{i + 1}", relation="calls")
    out = tmp_path / "graph.svg"

    to_svg(G, {0: list(G.nodes())}, str(out), figsize=(4, 3), dpi=50)

    assert "<svg" in out.read_text()[:500]
