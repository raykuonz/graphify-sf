"""0.6.0 E1: callout scans only real code, GraphML export works, and the merge paths are strict 3-way."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import networkx as nx
import pytest

from graphify_sf._merge import (
    GraphJsonError,
    edge_identity,
    load_base_graph_json,
    load_graph_json_strict,
    merge_attrs,
    three_way_merge,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ── Apex: setEndpoint must be real code ──────────────────────────────────────────────


def _apex_edges(tmp_path: Path, body: str) -> list[dict]:
    from graphify_sf.extract.apex import extract_apex_class

    cls = tmp_path / "Svc.cls"
    cls.write_text("public class Svc {\n" + body + "\n}\n", encoding="utf-8")
    return [e for e in extract_apex_class(cls)["edges"] if e["relation"] == "makes_callout"]


def test_real_setendpoint_is_still_extracted(tmp_path):
    edges = _apex_edges(
        tmp_path, "public void go() { HttpRequest req = new HttpRequest(); req.setEndpoint('callout:Real_NC/x'); }"
    )
    assert [(e["target"], e["confidence"]) for e in edges] == [("namedcredential_real_nc", "EXTRACTED")]


@pytest.mark.parametrize(
    "body",
    [
        "// req.setEndpoint('callout:Line_Comment_NC');",
        "/* req.setEndpoint('callout:Block_Comment_NC'); */",
        "String doc = \"call req.setEndpoint('callout:In_String_NC') later\";",
        "/*\n * req.setEndpoint('https://commented.example.com/x');\n */",
    ],
)
def test_commented_or_quoted_setendpoint_emits_no_edge(tmp_path, body):
    assert _apex_edges(tmp_path, body) == []


def test_comment_next_to_a_real_call_does_not_hide_it(tmp_path):
    body = "// req.setEndpoint('callout:Old_NC');\npublic void go() { req.setEndpoint('callout:New_NC/v1'); }"
    assert [e["target"] for e in _apex_edges(tmp_path, body)] == ["namedcredential_new_nc"]


def test_pipeline_keeps_the_extracted_edge_for_the_epica_fixture(tmp_path):
    from graphify_sf.__main__ import _run_pipeline

    project = tmp_path / "proj"
    shutil.copytree(FIXTURES / "epicA_callout", project)
    out = tmp_path / "out"
    _run_pipeline(project, out, update=False, directed=False, no_viz=True, max_workers=1, force=True)
    links = json.loads((out / "graph.json").read_text())["links"]
    callouts = [(e["source"], e["target"], e["confidence"]) for e in links if e["relation"] == "makes_callout"]
    assert ("apex_calloutnamed", "namedcredential_my_nc", "EXTRACTED") in callouts


# ── GraphML ──────────────────────────────────────────────────────────────────────────


def test_export_graphml_writes_a_real_graph_and_drops_graph_level_metadata(tmp_path):
    from graphify_sf.__main__ import _run_pipeline
    from graphify_sf.export import to_graphml

    project = tmp_path / "proj"
    shutil.copytree(FIXTURES / "epicA_callout", project)
    out = tmp_path / "out"
    _run_pipeline(project, out, update=False, directed=False, no_viz=True, max_workers=1, force=True)
    from graphify_sf.__main__ import _load_graph_from_json

    G, _ = _load_graph_from_json(out / "graph.json")
    assert any(a.get("source_location") is None for _, a in G.nodes(data=True)), "fixture must contain None attrs"
    G.graph["graphify_sf"] = {"analysis": {"x": {"status": "complete"}}}
    G.graph["hyperedges"] = [{"nodes": ["a", "b"]}]
    for _u, _v, a in G.edges(data=True):
        a["_tgt_name"] = "Original_Case"
        a["listy"] = ["a", "b"]
        break

    path = tmp_path / "g.graphml"
    to_graphml(G, {0: list(G.nodes())}, str(path))

    H = nx.read_graphml(path)
    assert H.number_of_nodes() == G.number_of_nodes()
    assert H.number_of_edges() == G.number_of_edges()
    assert "graphify_sf" not in H.graph and "hyperedges" not in H.graph
    assert all("_tgt_name" not in a for _, _, a in H.edges(data=True))
    assert any(json.loads(a["listy"]) == ["a", "b"] for _, _, a in H.edges(data=True) if "listy" in a)


# ── Merge: strict loading ────────────────────────────────────────────────────────────


def _graph(nodes, links=()):
    return {
        "nodes": [{"id": n, "label": n, "sf_type": "ApexClass", "file_type": "apex", **a} for n, a in nodes],
        "links": list(links),
    }


def _write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize("text", ["", "not json", "[]", '{"nodes": []}', '{"links": []}', '{"nodes": {}, "links": []}'])
def test_strict_loader_rejects_unusable_files(tmp_path, text):
    p = tmp_path / "graph.json"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(GraphJsonError):
        load_graph_json_strict(p)
    with pytest.raises(GraphJsonError):
        load_graph_json_strict(tmp_path / "missing.json")


def test_strict_loader_accepts_edges_alias_and_valid_empty_graph(tmp_path):
    assert load_graph_json_strict(_write(tmp_path / "a.json", {"nodes": [], "edges": []}))["links"] == []
    assert load_graph_json_strict(_write(tmp_path / "b.json", {"nodes": [], "links": []}))["nodes"] == []


def test_base_loader_treats_missing_and_zero_byte_as_no_base_but_not_garbage(tmp_path):
    assert load_base_graph_json(tmp_path / "missing.json") is None
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert load_base_graph_json(empty) is None
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    with pytest.raises(GraphJsonError):
        load_base_graph_json(bad)


# ── Merge: semantics ─────────────────────────────────────────────────────────────────


def _ids(nodes):
    return sorted(n["id"] for n in nodes)


def test_three_way_deletion_rules():
    base = _graph([("a", {}), ("b", {}), ("c", {})])
    ours = _graph([("a", {}), ("b", {}), ("d", {})])  # deleted c, added d
    theirs = _graph([("a", {}), ("c", {}), ("e", {})])  # deleted b, added e
    nodes, _ = three_way_merge(base, ours, theirs)
    assert _ids(nodes) == ["a", "d", "e"]  # b and c deleted by one side; additions kept


def test_node_only_in_base_is_gone_and_added_on_both_sides_is_kept():
    base = _graph([("gone", {})])
    nodes, _ = three_way_merge(base, _graph([("new", {})]), _graph([("new", {})]))
    assert _ids(nodes) == ["new"]


def test_no_base_is_a_plain_union():
    nodes, _ = three_way_merge(None, _graph([("a", {})]), _graph([("b", {})]))
    assert _ids(nodes) == ["a", "b"]


def test_attributes_merge_per_attribute_and_base_never_wins():
    base = {"x": 1, "y": 1, "z": 1}
    ours = {"x": 2, "y": 1, "z": 1}  # changed x
    theirs = {"x": 3, "y": 9, "z": 1}  # changed x (conflict) and y
    assert merge_attrs(base, ours, theirs) == {"x": 2, "y": 9, "z": 1}  # ours wins conflicts, theirs-only change kept
    assert merge_attrs(None, {"a": 1}, {"a": 2, "b": 3}) == {"a": 1, "b": 3}
    # an attribute dropped by one side and untouched by the other is dropped
    assert merge_attrs({"k": 1}, {}, {"k": 1}) == {}


def _callout(site_count, line, **extra):
    return {
        "source": "a",
        "target": "namedcredential_x",
        "relation": "makes_callout",
        "confidence": "EXTRACTED",
        "test_context": False,
        "site_count": site_count,
        "source_location": f"L{line}",
        **extra,
    }


def test_callout_edge_identity_ignores_mutable_site_attributes():
    assert edge_identity(_callout(1, 10)) == edge_identity(_callout(5, 99))
    assert edge_identity(_callout(1, 10)) != edge_identity(_callout(1, 10, confidence="INFERRED"))
    assert edge_identity(_callout(1, 10)) != edge_identity(_callout(1, 10, test_context=True))


def test_modified_on_one_side_deleted_on_the_other_stays_deleted_for_callout_edges():
    nodes = [("a", {}), ("namedcredential_x", {})]
    base = _graph(nodes, [_callout(1, 10)])
    ours = _graph(nodes, [_callout(3, 12)])  # a call site was added: site_count/location changed
    theirs = _graph(nodes, [])  # the callout was removed
    _, edges = three_way_merge(base, ours, theirs)
    assert edges == []


def test_callout_edge_modified_on_both_sides_merges_attributes_not_duplicates():
    nodes = [("a", {}), ("namedcredential_x", {})]
    base = _graph(nodes, [_callout(1, 10)])
    ours = _graph(nodes, [_callout(2, 10)])
    theirs = _graph(nodes, [_callout(1, 10, inference_reason=None)])
    _, edges = three_way_merge(base, ours, theirs)
    assert len(edges) == 1 and edges[0]["site_count"] == 2


def test_operation_distinct_edges_keep_their_full_identity():
    def dml(op):
        return {"source": "a", "target": "o", "relation": "dml", "operation": op, "confidence": "INFERRED"}

    nodes = [("a", {}), ("o", {})]
    base = _graph(nodes, [dml("create")])
    ours = _graph(nodes, [dml("create"), dml("update")])
    theirs = _graph(nodes, [dml("create")])
    _, edges = three_way_merge(base, ours, theirs)
    assert sorted(e["operation"] for e in edges) == ["create", "update"]


# ── Merge: commands ──────────────────────────────────────────────────────────────────


def test_merge_driver_fails_closed_and_leaves_ours_untouched(tmp_path):
    from graphify_sf.__main__ import _cmd_merge_driver

    base = _write(tmp_path / "base.json", _graph([("a", {}), ("b", {})]))
    ours = _write(tmp_path / "ours.json", _graph([("a", {}), ("b", {})]))
    theirs = tmp_path / "theirs.json"
    theirs.write_text("{ truncated", encoding="utf-8")
    before = ours.read_bytes()
    with pytest.raises(SystemExit) as exc:
        _cmd_merge_driver(base, ours, theirs)
    assert exc.value.code == 1
    assert ours.read_bytes() == before


def test_merge_driver_fails_closed_on_a_garbage_base(tmp_path):
    from graphify_sf.__main__ import _cmd_merge_driver

    base = tmp_path / "base.json"
    base.write_text("garbage", encoding="utf-8")
    ours = _write(tmp_path / "ours.json", _graph([("a", {})]))
    theirs = _write(tmp_path / "theirs.json", _graph([("a", {})]))
    before = ours.read_bytes()
    with pytest.raises(SystemExit):
        _cmd_merge_driver(base, ours, theirs)
    assert ours.read_bytes() == before


def test_merge_driver_zero_byte_base_is_a_union_and_deletions_apply(tmp_path):
    from graphify_sf.__main__ import _cmd_merge_driver

    base = tmp_path / "base.json"
    base.write_text("", encoding="utf-8")
    ours = _write(tmp_path / "ours.json", _graph([("a", {})]))
    theirs = _write(tmp_path / "theirs.json", _graph([("b", {})]))
    _cmd_merge_driver(base, ours, theirs)
    assert _ids(json.loads(ours.read_text())["nodes"]) == ["a", "b"]

    base = _write(tmp_path / "base2.json", _graph([("a", {}), ("b", {}), ("c", {})]))
    ours = _write(tmp_path / "ours2.json", _graph([("a", {}), ("b", {}), ("c", {})]))
    theirs = _write(tmp_path / "theirs2.json", _graph([("a", {}), ("b", {})]))  # theirs deleted c
    _cmd_merge_driver(base, ours, theirs)
    assert _ids(json.loads(ours.read_text())["nodes"]) == ["a", "b"]


def test_merge_graphs_aborts_on_a_malformed_input_without_writing(tmp_path, capsys):
    from graphify_sf.__main__ import _cmd_merge_graphs

    good = _write(tmp_path / "good.json", _graph([("a", {})]))
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    out = tmp_path / "merged" / "graph.json"
    with pytest.raises(SystemExit) as exc:
        _cmd_merge_graphs([good, bad], out, no_viz=True)
    assert exc.value.code == 1
    assert not out.exists() and not out.parent.exists()
    assert "bad.json" in capsys.readouterr().err
