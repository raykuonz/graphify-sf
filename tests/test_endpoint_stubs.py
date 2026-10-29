"""0.6.0 E3: callout targets missing from the repo become stub nodes; real nodes always beat stubs; colliding host ids stay honest."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from graphify_sf._merge import three_way_merge
from graphify_sf.build import build_from_json, deduplicate_by_label, prefer_real

FIXTURES = Path(__file__).parent / "fixtures"


def _project(tmp_path: Path, classes: dict[str, str] | None = None, flows: dict[str, str] | None = None) -> Path:
    root = tmp_path / "proj" / "force-app" / "main" / "default"
    (root / "classes").mkdir(parents=True)
    for name, body in (classes or {}).items():
        (root / "classes" / f"{name}.cls").write_text(body, encoding="utf-8")
        (root / "classes" / f"{name}.cls-meta.xml").write_text("<ApexClass/>", encoding="utf-8")
    if flows:
        (root / "flows").mkdir()
        for name, body in flows.items():
            (root / "flows" / f"{name}.flow-meta.xml").write_text(body, encoding="utf-8")
    return tmp_path / "proj"


def _build(project: Path, out: Path) -> dict:
    from graphify_sf.__main__ import _run_pipeline

    _run_pipeline(project, out, update=False, directed=False, no_viz=True, max_workers=1, force=True)
    return json.loads((out / "graph.json").read_text())


def _flow(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<Flow xmlns="http://soap.sforce.com/2006/04/metadata">\n'
        f"<apiVersion>60.0</apiVersion>{body}</Flow>\n"
    )


def _callouts(data: dict) -> list[dict]:
    return [e for e in data["links"] if e["relation"] == "makes_callout"]


def _node(data: dict, nid: str) -> dict:
    return next(n for n in data["nodes"] if n["id"] == nid)


# ── G2: a Named Credential that is not in the repo ───────────────────────────────────


def test_missing_named_credential_becomes_a_stub_and_the_edge_stays_extracted(tmp_path):
    project = _project(
        tmp_path,
        {
            "Svc": "public class Svc { public void go() { HttpRequest req = new HttpRequest(); req.setEndpoint('callout:Not_In_Repo/orders'); } }"
        },
    )
    data = _build(project, tmp_path / "out")
    stub = _node(data, "namedcredential_not_in_repo")
    assert stub["stub"] is True and stub["sf_type"] == "NamedCredential"
    assert stub["label"] == "Not_In_Repo"  # original case, not the lossy id
    assert stub["source_file"] is None and stub["source_location"] is None
    edges = [e for e in _callouts(data) if e["target"] == "namedcredential_not_in_repo"]
    assert [(e["source"], e["confidence"]) for e in edges] == [("apex_svc", "EXTRACTED")]
    assert not any("_tgt_name" in e for e in data["links"]), "the private key must never reach graph.json"


def test_a_real_named_credential_is_not_stubbed(tmp_path):
    project = tmp_path / "proj"
    shutil.copytree(FIXTURES / "epicA_callout", project)
    data = _build(project, tmp_path / "out")
    node = _node(data, "namedcredential_my_nc")
    assert not node.get("stub") and node["source_file"]
    assert not any(n.get("stub") for n in data["nodes"] if n["sf_type"] == "NamedCredential")


def test_external_service_edge_to_a_missing_credential_gets_a_stub_too(tmp_path):
    root = tmp_path / "proj" / "force-app" / "main" / "default" / "externalServices"
    root.mkdir(parents=True)
    (root / "Pay.externalService-meta.xml").write_text(
        '<?xml version="1.0"?><ExternalServiceRegistration xmlns="http://soap.sforce.com/2006/04/metadata">'
        "<namedCredential>Pay_NC</namedCredential></ExternalServiceRegistration>",
        encoding="utf-8",
    )
    data = _build(tmp_path / "proj", tmp_path / "out")
    uses = [e for e in data["links"] if e["relation"] == "uses" and e["target"] == "namedcredential_pay_nc"]
    assert [(e["source"], e["confidence"]) for e in uses] == [("externalservice_pay", "EXTRACTED")]
    stub = _node(data, "namedcredential_pay_nc")
    assert stub["stub"] is True and stub["label"] == "Pay_NC"


# ── G4: a Flow literal URL needs no Apex class to survive ────────────────────────────


def test_flow_literal_url_creates_its_endpoint_node_without_any_apex(tmp_path):
    flow = _flow(
        "<actionCalls><name>Call</name><actionType>httpCallout</actionType>"
        "<inputParameters><name>url</name><value><stringValue>https://only-in-flow.example.com/a</stringValue></value></inputParameters>"
        "</actionCalls>"
    )
    data = _build(_project(tmp_path, flows={"LiteralOnly": flow}), tmp_path / "out")
    node = _node(data, "externalendpoint_only_in_flow_example_com")
    assert node["sf_type"] == "ExternalEndpoint" and node["label"] == "only-in-flow.example.com"
    assert [(e["source"], e["target"], e["confidence"]) for e in _callouts(data)] == [
        ("flow_literalonly", "externalendpoint_only_in_flow_example_com", "INFERRED")
    ]


# ── host-id collisions ───────────────────────────────────────────────────────────────


def test_hosts_that_share_an_id_are_marked_ambiguous_and_their_calls_inferred(tmp_path):
    classes = {
        "DotCaller": "public class DotCaller { public void go() { HttpRequest req = new HttpRequest(); req.setEndpoint('https://api.example.com/a'); } }",
        "DashCaller": "public class DashCaller { public void go() { HttpRequest req = new HttpRequest(); req.setEndpoint('https://api-example.com/b'); } }",
        "Other": "public class Other { public void go() { HttpRequest req = new HttpRequest(); req.setEndpoint('https://clean.example.org/c'); } }",
    }
    data = _build(_project(tmp_path, classes), tmp_path / "out")
    ep = _node(data, "externalendpoint_api_example_com")
    assert ep["identity_ambiguous"] is True and ep["hosts"] == ["api-example.com", "api.example.com"]
    to_ambiguous = [e for e in _callouts(data) if e["target"] == "externalendpoint_api_example_com"]
    assert len(to_ambiguous) == 2
    assert {(e["confidence"], e["inference_reason"]) for e in to_ambiguous} == {("INFERRED", "host_id_collision")}
    clean = _node(data, "externalendpoint_clean_example_org")
    assert "identity_ambiguous" not in clean and "hosts" not in clean


def test_a_named_credential_edge_is_never_downgraded_by_a_host_collision(tmp_path):
    classes = {
        "A": "public class A { public void go() { HttpRequest req = new HttpRequest(); req.setEndpoint('https://api.example.com/a'); } }",
        "B": "public class B { public void go() { HttpRequest req = new HttpRequest(); req.setEndpoint('https://api-example.com/b'); req.setEndpoint('callout:Keep_NC/x'); } }",
    }
    data = _build(_project(tmp_path, classes), tmp_path / "out")
    keep = [e for e in _callouts(data) if e["target"] == "namedcredential_keep_nc"]
    assert [e["confidence"] for e in keep] == ["EXTRACTED"]


# ── real beats stub, whatever the order ──────────────────────────────────────────────

REAL = {
    "id": "namedcredential_x",
    "label": "X",
    "sf_type": "NamedCredential",
    "file_type": "config",
    "source_file": "/p/X.namedCredential-meta.xml",
}
STUB = {
    "id": "namedcredential_x",
    "label": "X",
    "sf_type": "NamedCredential",
    "file_type": "config",
    "source_file": None,
    "stub": True,
}


def test_prefer_real():
    assert prefer_real(STUB, REAL) is REAL
    assert prefer_real(REAL, STUB) is REAL
    assert prefer_real(REAL, dict(REAL)) is None  # two real nodes merge normally
    assert prefer_real(STUB, dict(STUB)) is None


@pytest.mark.parametrize("order", [(REAL, STUB), (STUB, REAL)])
def test_build_from_json_keeps_the_real_node_in_either_order(order):
    G = build_from_json({"nodes": [dict(n) for n in order], "edges": []})
    attrs = G.nodes["namedcredential_x"]
    assert attrs["source_file"] and "stub" not in attrs


@pytest.mark.parametrize("order", [(REAL, STUB), (STUB, REAL)])
def test_deduplicate_by_label_keeps_the_real_node_in_either_order(order):
    nodes, _ = deduplicate_by_label([dict(n) for n in order], [])
    assert len(nodes) == 1 and not nodes[0].get("stub") and nodes[0]["source_file"]


@pytest.mark.parametrize("order", ["stub_ours", "stub_theirs"])
def test_three_way_merge_keeps_the_real_node_in_either_order(order):
    stub_graph = {"nodes": [dict(STUB)], "links": []}
    real_graph = {"nodes": [dict(REAL)], "links": []}
    ours, theirs = (stub_graph, real_graph) if order == "stub_ours" else (real_graph, stub_graph)
    nodes, _ = three_way_merge(None, ours, theirs)
    assert len(nodes) == 1 and nodes[0]["source_file"] and "stub" not in nodes[0]


def test_merge_graphs_union_keeps_the_real_node_in_either_order(tmp_path):
    from graphify_sf.__main__ import _union_graph_json

    for datas in ([{"nodes": [dict(STUB)], "links": []}, {"nodes": [dict(REAL)], "links": []}],
                  [{"nodes": [dict(REAL)], "links": []}, {"nodes": [dict(STUB)], "links": []}]):  # fmt: skip
        nodes, _ = _union_graph_json(datas)
        assert len(nodes) == 1 and nodes[0]["source_file"] and "stub" not in nodes[0]


# ── Apex declaration the regex misses ────────────────────────────────────────────────


def test_a_class_with_an_unrecognised_header_still_gets_a_node_and_is_analysed(tmp_path):
    body = "class Legacy {\n  public void go() { HttpRequest req = new HttpRequest(); req.setEndpoint('callout:Legacy_NC/x'); }\n}\n"
    data = _build(_project(tmp_path, {"Legacy": body}), tmp_path / "out")
    node = _node(data, "apex_legacy")
    assert node["sf_type"] == "ApexClass" and node["declaration_unparsed"] is True
    assert [(e["source"], e["target"]) for e in _callouts(data)] == [("apex_legacy", "namedcredential_legacy_nc")]


def test_a_normal_class_does_not_carry_the_unparsed_flag(tmp_path):
    data = _build(_project(tmp_path, {"Fine": "public class Fine { }"}), tmp_path / "out")
    assert "declaration_unparsed" not in _node(data, "apex_fine")


# ── existing consumers ───────────────────────────────────────────────────────────────


def _apex_inbound_extracted(data: dict) -> dict[str, int]:
    types = {n["id"]: n.get("sf_type") for n in data["nodes"]}
    counts: dict[str, int] = {}
    for e in data["links"]:
        if types.get(e["target"]) == "ApexClass" and e["confidence"] == "EXTRACTED" and e["relation"] != "contains":
            counts[e["target"]] = counts.get(e["target"], 0) + 1
    return counts


def test_apex_inbound_extracted_counts_are_unchanged_on_existing_fixtures(tmp_path):
    """sf-cockpit derives TD.ORPHAN-APEX from these counts; verified identical to 0.5.0 on every fixture."""
    project = tmp_path / "aura"
    shutil.copytree(FIXTURES / "epicD_aura_vf", project)
    assert _apex_inbound_extracted(_build(project, tmp_path / "out")) == {"apex_myctrl": 1}


# ── review follow-ups (E3 code review) ───────────────────────────────────────────────


def _real_nc(label="My_NC"):
    return {"id": "namedcredential_my_nc", "label": label, "sf_type": "NamedCredential", "source_file": "/r/My_NC.xml"}


def _stub_nc(label="My_NC"):
    return {
        "id": "namedcredential_my_nc",
        "label": label,
        "sf_type": "NamedCredential",
        "source_file": None,
        "stub": True,
    }


def test_three_way_merge_honours_a_deleted_credential_file_over_the_old_real_node():
    base = {"nodes": [_real_nc()], "links": []}
    ours = {"nodes": [_stub_nc()], "links": []}  # metadata file deleted; Apex still calls it
    theirs = {"nodes": [_real_nc()], "links": []}  # untouched
    nodes, _ = three_way_merge(base, ours, theirs)
    (node,) = nodes
    assert node.get("stub") is True and node["source_file"] is None
    # and the mirror image
    nodes, _ = three_way_merge(base, theirs, ours)
    assert nodes[0].get("stub") is True


def test_three_way_merge_still_prefers_real_when_both_sides_add_the_node():
    base = {"nodes": [], "links": []}
    nodes, _ = three_way_merge(base, {"nodes": [_stub_nc()], "links": []}, {"nodes": [_real_nc()], "links": []})
    assert nodes[0].get("stub") is None and nodes[0]["source_file"] == "/r/My_NC.xml"


def test_label_dedup_does_not_fold_a_stub_into_a_different_real_node():
    stub = {**_stub_nc("MyNC"), "id": "namedcredential_mync"}
    real = _real_nc("My_NC")
    nodes, edges = deduplicate_by_label(
        [stub, real], [{"source": "apexclass_a", "target": "namedcredential_mync", "relation": "makes_callout"}]
    )
    assert {n["id"] for n in nodes} == {"namedcredential_mync", "namedcredential_my_nc"}
    assert edges[0]["target"] == "namedcredential_mync"


def test_label_dedup_keeps_nodes_whose_label_has_no_ascii_letters():
    jp = {"id": "flow_x_label", "label": "ラベル", "sf_type": "FlowElement"}
    a = {"id": "object_account", "label": "Account", "sf_type": "CustomObject"}
    b = {"id": "object_account_c1", "label": "Account", "sf_type": "CustomObject"}
    nodes, _ = deduplicate_by_label([jp, a, b], [])
    assert "flow_x_label" in {n["id"] for n in nodes}


def test_query_string_does_not_become_part_of_the_credential_name(tmp_path):
    project = _project(
        tmp_path,
        {
            "Svc": "public class Svc { void go() { HttpRequest req = new HttpRequest(); req.setEndpoint('callout:My_NC?api=1'); } }"
        },
    )
    data = _build(project, tmp_path / "out")
    assert [e["target"] for e in _callouts(data)] == ["namedcredential_my_nc"]


def test_batchable_header_and_inner_types_do_not_rename_the_outer_class(tmp_path):
    body = """
global class Nightly implements Database.Batchable<sObject> {
  public class Inner { }
  global Database.QueryLocator start(Database.BatchableContext bc) { return null; }
}
"""
    project = _project(tmp_path, {"Nightly": body})
    data = _build(project, tmp_path / "out")
    node = _node(data, "apex_nightly")
    assert node["label"] == "Nightly" and node["declaration_unparsed"] is True


def test_dotted_interface_header_keeps_its_real_kind(tmp_path):
    project = _project(tmp_path, {"Contract": "public interface Contract extends Outer.Base { }"})
    data = _build(project, tmp_path / "out")
    assert next(n for n in data["nodes"] if n["label"] == "Contract")["sf_type"] == "ApexInterface"


def test_a_cls_file_that_is_not_apex_makes_no_node(tmp_path):
    project = _project(
        tmp_path,
        {"Paper": "\\documentclass{article}\n\\begin{document}hi\\end{document}", "Real": "public class Real { }"},
    )
    data = _build(project, tmp_path / "out")
    assert not [n for n in data["nodes"] if n["label"] == "Paper"]


def test_flow_literal_urls_are_deduped_and_merge_fields_are_skipped(tmp_path):
    action = (
        "<actionCalls><name>{n}</name><actionType>httpCallout</actionType><inputParameters><name>url</name>"
        "<value><stringValue>{u}</stringValue></value></inputParameters></actionCalls>"
    )
    body = "".join(
        action.format(n=f"a{i}", u=u)
        for i, u in enumerate(["https://api.example.com/a", "https://api.example.com/b", "https://{!Host}/x"])
    )
    project = _project(tmp_path, flows={"F": _flow(body)})
    data = _build(project, tmp_path / "out")
    assert [e["target"] for e in _callouts(data)] == ["externalendpoint_api_example_com"]
    assert len([n for n in data["nodes"] if n["sf_type"] == "ExternalEndpoint"]) == 1


def test_stub_label_is_independent_of_edge_order():
    from graphify_sf.extract import _stub_missing_endpoints

    def run(names):
        edges = [
            {"source": f"apexclass_{i}", "target": "namedcredential_my_nc", "relation": "makes_callout", "_tgt_name": n}
            for i, n in enumerate(names)
        ]
        nodes: list[dict] = []
        _stub_missing_endpoints(nodes, edges)
        return nodes[0]["label"]

    assert run(["MY_NC", "My_Nc"]) == run(["My_Nc", "MY_NC"]) == "MY_NC"
