"""Integration tests for Epic D — UI layer → backend linkage (graphify-sf v0.4.0).

Runs detect+extract on fixtures and asserts on nodes/edges.
Tests follow the same empirical style as test_automation_coverage.py.

CRITICAL: Run with .venv/bin/python -m pytest, NOT bare python (no networkx).

Edge-layer notes (EXTRACT vs graph.json):
  All tests below assert at the _extract layer (after _resolve_cross_references
  but before build_from_json).  All target nodes are provided in the fixtures so
  edges remain EXTRACTED and are NOT dropped by dangling-edge removal at build time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _extract(fixture_rel: str) -> dict:
    """Run detect + per-file extraction + cross-reference resolution on a fixture."""
    from graphify_sf.detect import detect
    from graphify_sf.extract import _extract_file, _resolve_cross_references
    from graphify_sf.extract.aura import extract_aura_bundle
    from graphify_sf.extract.lwc import extract_lwc_bundle

    src = FIXTURES / fixture_rel
    detection = detect(src)

    all_nodes: list[dict] = []
    all_edges: list[dict] = []

    for file_list in detection.get("files", {}).values():
        for f in file_list:
            r = _extract_file(f)
            all_nodes.extend(r.get("nodes", []))
            all_edges.extend(r.get("edges", []))

    for bundle_dir in detection.get("bundle_dirs", {}).get("lwc", []):
        r = extract_lwc_bundle(bundle_dir)
        all_nodes.extend(r.get("nodes", []))
        all_edges.extend(r.get("edges", []))

    for bundle_dir in detection.get("bundle_dirs", {}).get("aura", []):
        r = extract_aura_bundle(bundle_dir)
        all_nodes.extend(r.get("nodes", []))
        all_edges.extend(r.get("edges", []))

    resolved_nodes, resolved_edges = _resolve_cross_references(all_nodes, all_edges)
    return {"nodes": resolved_nodes, "edges": resolved_edges}


def _nodes_by_id(result: dict) -> dict[str, dict]:
    return {n["id"]: n for n in result.get("nodes", [])}


def _edges(result: dict) -> list[dict]:
    return result.get("edges", [])


# ---------------------------------------------------------------------------
# D1 — LWC @salesforce/schema + label + resource imports
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def d1_result():
    return _extract("epicD_lwc/force-app/main/default")


def test_d1_schema_field_references_edge_extracted(d1_result):
    """LWC @salesforce/schema/Account.Name → references field_account_name EXTRACTED."""
    edges = _edges(d1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "lwc_schemalwc"
            and e.get("target") == "field_account_name"
            and e.get("relation") == "references"
        ),
        None,
    )
    assert edge is not None, "expected LWC→field_account_name references edge"
    assert edge["confidence"] == "EXTRACTED"


def test_d1_label_uses_edge_extracted(d1_result):
    """LWC @salesforce/label/c.Greeting → uses label_greeting EXTRACTED."""
    edges = _edges(d1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "lwc_schemalwc"
            and e.get("target") == "label_greeting"
            and e.get("relation") == "uses"
        ),
        None,
    )
    assert edge is not None, "expected LWC→label_greeting uses edge"
    assert edge["confidence"] == "EXTRACTED"


def test_d1_resource_uses_edge_extracted(d1_result):
    """LWC @salesforce/resourceUrl/MyResource → uses staticresource_myresource EXTRACTED.

    Target node is provided by MyResource.resource-meta.xml via the D3 StaticResource extractor.
    """
    edges = _edges(d1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "lwc_schemalwc"
            and e.get("target") == "staticresource_myresource"
            and e.get("relation") == "uses"
        ),
        None,
    )
    assert edge is not None, "expected LWC→staticresource_myresource uses edge"
    assert edge["confidence"] == "EXTRACTED"


def test_d1_apex_method_calls_edge_extracted(d1_result):
    """LWC @salesforce/apex/MyService.doThing → calls method_myservice_dothing EXTRACTED.

    Target method node exists (MyService.cls has doThing method), so edge stays EXTRACTED.
    """
    edges = _edges(d1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "lwc_schemalwc"
            and e.get("target") == "method_myservice_dothing"
            and e.get("relation") == "calls"
        ),
        None,
    )
    assert edge is not None, "expected LWC→method_myservice_dothing calls edge"
    assert edge["confidence"] == "EXTRACTED"


def test_d1_negative_no_object_edge_for_field_import(d1_result):
    """Import of Account.Name must NOT emit a separate references→object_account edge.

    When the import specifies a field (Object.Field), only the field edge is emitted.
    """
    edges = _edges(d1_result)
    bad = [
        e
        for e in edges
        if e.get("source") == "lwc_schemalwc"
        and e.get("target") == "object_account"
        and e.get("relation") == "references"
    ]
    assert bad == [], f"schema Object.Field import must not also emit object edge: {bad}"


def test_d1_static_resource_node_exists(d1_result):
    """StaticResource node is created for MyResource.resource-meta.xml."""
    nodes = _nodes_by_id(d1_result)
    assert "staticresource_myresource" in nodes, "expected StaticResource node staticresource_myresource"
    assert nodes["staticresource_myresource"]["sf_type"] == "StaticResource"


# ---------------------------------------------------------------------------
# D2 — Aura controller + VF standardController/extensions linkage
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def d2_result():
    return _extract("epicD_aura_vf/force-app/main/default")


def test_d2_vf_standard_controller_references_object_extracted(d2_result):
    """VF page with standardController='Account' emits references→object_account EXTRACTED."""
    edges = _edges(d2_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "page_accountdetailpage"
            and e.get("target") == "object_account"
            and e.get("relation") == "references"
        ),
        None,
    )
    assert edge is not None, "expected ApexPage→object_account references edge"
    assert edge["confidence"] == "EXTRACTED"


def test_d2_vf_standard_controller_does_not_emit_phantom_apex_class(d2_result):
    """Regression: standardController='Account' must NOT also be parsed by the custom
    `controller=` regex and emit a phantom apex_account ApexClass reference. The substring
    `Controller="Account"` inside `standardController="Account"` previously matched
    _CONTROLLER_RE; a negative lookbehind now prevents it."""
    edges = _edges(d2_result)
    phantom = [e for e in edges if e.get("source") == "page_accountdetailpage" and e.get("target") == "apex_account"]
    assert phantom == [], f"phantom apex_account reference leaked from standardController: {phantom}"


def test_d2_vf_child_component_uses_edge_extracted(d2_result):
    """VF page with <c:MyHelper> emits uses→vfcomponent_myhelper EXTRACTED."""
    edges = _edges(d2_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "page_accountdetailpage"
            and e.get("target") == "vfcomponent_myhelper"
            and e.get("relation") == "uses"
        ),
        None,
    )
    assert edge is not None, "expected ApexPage→vfcomponent_myhelper uses edge"
    assert edge["confidence"] == "EXTRACTED"


def test_d2_aura_calls_apex_method_inferred(d2_result):
    """Aura JS .get('c.doThing') with controller='MyCtrl' → calls method_myctrl_dothing INFERRED."""
    edges = _edges(d2_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "aura_myaura"
            and e.get("target") == "method_myctrl_dothing"
            and e.get("relation") == "calls"
        ),
        None,
    )
    assert edge is not None, "expected Aura→method_myctrl_dothing calls edge"
    assert edge["confidence"] == "INFERRED", f"Aura server-action calls must be INFERRED, got {edge['confidence']!r}"


def test_d2_aura_still_references_controller_class_extracted(d2_result):
    """Aura controller= attr still emits references→apex_myctrl EXTRACTED (existing behaviour)."""
    edges = _edges(d2_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "aura_myaura"
            and e.get("target") == "apex_myctrl"
            and e.get("relation") == "references"
        ),
        None,
    )
    assert edge is not None, "expected Aura→apex_myctrl references edge (existing behaviour)"
    assert edge["confidence"] == "EXTRACTED"


def test_d2_negative_no_calls_edge_without_server_action(d2_result):
    """Components with no .get('c.method') call must not produce spurious calls edges."""
    edges = _edges(d2_result)
    aura_calls = [
        e
        for e in edges
        if e.get("source") == "aura_myaura"
        and e.get("relation") == "calls"
        and "method_myctrl" not in e.get("target", "")
    ]
    assert aura_calls == [], f"unexpected extra calls edges from aura_myaura: {aura_calls}"


# ---------------------------------------------------------------------------
# D3 — FlexiPage embeds (LWC + Aura) + StaticResource / QuickAction / CustomTab-App
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def d3_result():
    return _extract("epicD_config/force-app/main/default")


def test_d3_flexipage_contains_aura_extracted(d3_result):
    """FlexiPage with <componentName>c:MyAuraComp</componentName> → contains aura_myauracomp EXTRACTED."""
    edges = _edges(d3_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "flexipage_accountfp"
            and e.get("target") == "aura_myauracomp"
            and e.get("relation") == "contains"
        ),
        None,
    )
    assert edge is not None, "expected FlexiPage→aura_myauracomp contains edge"
    assert edge["confidence"] == "EXTRACTED"


def test_d3_flexipage_negative_no_lwc_edge_for_pascal_case(d3_result):
    """c:MyAuraComp is PascalCase → must NOT emit contains→lwc_myauracomp (it's Aura, not LWC)."""
    edges = _edges(d3_result)
    bad = [
        e
        for e in edges
        if e.get("source") == "flexipage_accountfp"
        and e.get("target") == "lwc_myauracomp"
        and e.get("relation") == "contains"
    ]
    assert bad == [], f"PascalCase c: embed must not produce LWC edge: {bad}"


def test_d3_static_resource_node_exists(d3_result):
    """MyResource.resource-meta.xml → StaticResource node staticresource_myresource exists."""
    nodes = _nodes_by_id(d3_result)
    assert "staticresource_myresource" in nodes, "expected StaticResource node"
    assert nodes["staticresource_myresource"]["sf_type"] == "StaticResource"


def test_d3_quickaction_references_object_extracted(d3_result):
    """QuickAction <targetObject>Account</targetObject> → references object_account EXTRACTED."""
    edges = _edges(d3_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "quickaction_newaccount"
            and e.get("target") == "object_account"
            and e.get("relation") == "references"
        ),
        None,
    )
    assert edge is not None, "expected QuickAction→object_account references edge"
    assert edge["confidence"] == "EXTRACTED"


def test_d3_quickaction_uses_lwc_extracted(d3_result):
    """QuickAction <lightningComponent>createAccount</lightningComponent> → uses lwc_createaccount EXTRACTED."""
    edges = _edges(d3_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "quickaction_newaccount"
            and e.get("target") == "lwc_createaccount"
            and e.get("relation") == "uses"
        ),
        None,
    )
    assert edge is not None, "expected QuickAction→lwc_createaccount uses edge"
    assert edge["confidence"] == "EXTRACTED"


def test_d3_quickaction_node_exists(d3_result):
    """QuickAction node quickaction_newaccount must exist with sf_type=QuickAction."""
    nodes = _nodes_by_id(d3_result)
    assert "quickaction_newaccount" in nodes, "expected QuickAction node"
    assert nodes["quickaction_newaccount"]["sf_type"] == "QuickAction"


def test_d3_custom_tab_references_object_extracted(d3_result):
    """CustomTab <customObject>Account</customObject> → references object_account EXTRACTED."""
    edges = _edges(d3_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "customtab_accounttab"
            and e.get("target") == "object_account"
            and e.get("relation") == "references"
        ),
        None,
    )
    assert edge is not None, "expected CustomTab→object_account references edge"
    assert edge["confidence"] == "EXTRACTED"


def test_d3_custom_app_contains_tab_extracted(d3_result):
    """CustomApplication <tabs>AccountTab</tabs> → contains customtab_accounttab EXTRACTED."""
    edges = _edges(d3_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "customapplication_myapp"
            and e.get("target") == "customtab_accounttab"
            and e.get("relation") == "contains"
        ),
        None,
    )
    assert edge is not None, "expected CustomApplication→customtab_accounttab contains edge"
    assert edge["confidence"] == "EXTRACTED"


def test_d3_custom_app_node_exists(d3_result):
    """CustomApplication node customapplication_myapp must exist."""
    nodes = _nodes_by_id(d3_result)
    assert "customapplication_myapp" in nodes, "expected CustomApplication node"
    assert nodes["customapplication_myapp"]["sf_type"] == "CustomApplication"


def test_d3_custom_tab_node_exists(d3_result):
    """CustomTab node customtab_accounttab must exist."""
    nodes = _nodes_by_id(d3_result)
    assert "customtab_accounttab" in nodes, "expected CustomTab node"
    assert nodes["customtab_accounttab"]["sf_type"] == "CustomTab"


def test_d3_negative_no_spurious_quickaction_edges(d3_result):
    """QuickAction must not produce contains or references edges to unrelated targets."""
    edges = _edges(d3_result)
    qa_edges = [e for e in edges if e.get("source") == "quickaction_newaccount"]
    relations = {e["relation"] for e in qa_edges}
    allowed = {"references", "uses"}
    unexpected = relations - allowed
    assert not unexpected, f"unexpected relation types on QuickAction: {unexpected}"
