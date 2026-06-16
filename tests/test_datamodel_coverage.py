"""Integration tests for Epic E — Data model completeness (graphify-sf v0.4.0).

Asserts at the _extract layer (detect + extract + _resolve_cross_references).
All fixtures include target node source files so edges remain EXTRACTED and
would survive into graph.json without being dropped by dangling-edge removal.

CRITICAL: Run with .venv/bin/python -m pytest, NOT bare python (no networkx).

Layer note: these tests assert at the extractor layer (post cross-ref resolution)
rather than parsing a written graph.json file.  All target nodes are present in
the fixtures, so EXTRACTED confidence is preserved through _resolve_cross_references.
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
# E1 — Field Sets + Global Value Sets
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def e1_result():
    return _extract("epicE_fieldsets/force-app/main/default")


def test_e1_fieldset_node_exists(e1_result):
    """FieldSet node is created with sf_type=FieldSet."""
    nodes = _nodes_by_id(e1_result)
    assert "fieldset_account_account_fs" in nodes, "expected FieldSet node fieldset_account_account_fs"
    assert nodes["fieldset_account_account_fs"]["sf_type"] == "FieldSet"


def test_e1_object_contains_fieldset_extracted(e1_result):
    """Account object --contains--> FieldSet EXTRACTED."""
    edges = _edges(e1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "object_account"
            and e.get("target") == "fieldset_account_account_fs"
            and e.get("relation") == "contains"
        ),
        None,
    )
    assert edge is not None, "expected object_account --contains--> fieldset EXTRACTED"
    assert edge["confidence"] == "EXTRACTED"


def test_e1_fieldset_contains_name_field_extracted(e1_result):
    """FieldSet --contains--> field_account_name EXTRACTED."""
    edges = _edges(e1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "fieldset_account_account_fs"
            and e.get("target") == "field_account_name"
            and e.get("relation") == "contains"
        ),
        None,
    )
    assert edge is not None, "expected fieldset --contains--> field_account_name EXTRACTED"
    assert edge["confidence"] == "EXTRACTED"


def test_e1_fieldset_contains_phone_field_extracted(e1_result):
    """FieldSet --contains--> field_account_phone EXTRACTED."""
    edges = _edges(e1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "fieldset_account_account_fs"
            and e.get("target") == "field_account_phone"
            and e.get("relation") == "contains"
        ),
        None,
    )
    assert edge is not None, "expected fieldset --contains--> field_account_phone EXTRACTED"
    assert edge["confidence"] == "EXTRACTED"


def test_e1_gvs_node_exists(e1_result):
    """GlobalValueSet node is created with sf_type=GlobalValueSet."""
    nodes = _nodes_by_id(e1_result)
    assert "globalvalueset_my_gvs" in nodes, "expected GlobalValueSet node globalvalueset_my_gvs"
    assert nodes["globalvalueset_my_gvs"]["sf_type"] == "GlobalValueSet"


def test_e1_picklist_uses_gvs_extracted(e1_result):
    """Rating__c picklist field --uses--> GlobalValueSet EXTRACTED."""
    edges = _edges(e1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "field_account_rating__c"
            and e.get("target") == "globalvalueset_my_gvs"
            and e.get("relation") == "uses"
        ),
        None,
    )
    assert edge is not None, "expected field_account_rating__c --uses--> globalvalueset_my_gvs EXTRACTED"
    assert edge["confidence"] == "EXTRACTED"


def test_e1_negative_no_gvs_edge_for_non_picklist(e1_result):
    """Text and Phone fields must not emit spurious uses-GVS edges."""
    edges = _edges(e1_result)
    bad = [
        e
        for e in edges
        if e.get("target") == "globalvalueset_my_gvs"
        and e.get("source") not in ("field_account_rating__c",)
    ]
    assert bad == [], f"unexpected GVS edges from non-picklist fields: {bad}"


# ---------------------------------------------------------------------------
# E2 — CompactLayout / ListView / RecordType inner field refs
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def e2_result():
    return _extract("epicE_layout_refs/force-app/main/default")


def test_e2_compactlayout_node_exists(e2_result):
    """CompactLayout node exists with sf_type=CompactLayout."""
    nodes = _nodes_by_id(e2_result)
    assert "compactlayout_account_account_cl" in nodes, "expected CompactLayout node"
    assert nodes["compactlayout_account_account_cl"]["sf_type"] == "CompactLayout"


def test_e2_compactlayout_uses_name_field_extracted(e2_result):
    """CompactLayout --uses--> field_account_name EXTRACTED."""
    edges = _edges(e2_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "compactlayout_account_account_cl"
            and e.get("target") == "field_account_name"
            and e.get("relation") == "uses"
        ),
        None,
    )
    assert edge is not None, "expected CompactLayout --uses--> field_account_name EXTRACTED"
    assert edge["confidence"] == "EXTRACTED"


def test_e2_compactlayout_uses_phone_field_extracted(e2_result):
    """CompactLayout --uses--> field_account_phone EXTRACTED."""
    edges = _edges(e2_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "compactlayout_account_account_cl"
            and e.get("target") == "field_account_phone"
            and e.get("relation") == "uses"
        ),
        None,
    )
    assert edge is not None, "expected CompactLayout --uses--> field_account_phone EXTRACTED"
    assert edge["confidence"] == "EXTRACTED"


def test_e2_listview_node_exists(e2_result):
    """ListView node exists with sf_type=ListView."""
    nodes = _nodes_by_id(e2_result)
    assert "listview_account_allaccounts" in nodes, "expected ListView node"
    assert nodes["listview_account_allaccounts"]["sf_type"] == "ListView"


def test_e2_listview_uses_name_field_extracted(e2_result):
    """ListView --uses--> field_account_name EXTRACTED."""
    edges = _edges(e2_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "listview_account_allaccounts"
            and e.get("target") == "field_account_name"
            and e.get("relation") == "uses"
        ),
        None,
    )
    assert edge is not None, "expected ListView --uses--> field_account_name EXTRACTED"
    assert edge["confidence"] == "EXTRACTED"


def test_e2_listview_uses_industry_field_extracted(e2_result):
    """ListView --uses--> field_account_industry EXTRACTED."""
    edges = _edges(e2_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "listview_account_allaccounts"
            and e.get("target") == "field_account_industry"
            and e.get("relation") == "uses"
        ),
        None,
    )
    assert edge is not None, "expected ListView --uses--> field_account_industry EXTRACTED"
    assert edge["confidence"] == "EXTRACTED"


def test_e2_recordtype_references_business_process_extracted(e2_result):
    """RecordType --references--> BusinessProcess EXTRACTED when <businessProcess> present."""
    edges = _edges(e2_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "recordtype_account_enterprise"
            and e.get("relation") == "references"
            and "businessprocess" in e.get("target", "")
        ),
        None,
    )
    assert edge is not None, "expected RecordType --references--> businessprocess EXTRACTED"
    assert edge["confidence"] == "EXTRACTED"


def test_e2_negative_compactlayout_no_spurious_uses_edges(e2_result):
    """CompactLayout must not emit uses edges to targets other than the declared fields."""
    edges = _edges(e2_result)
    cl_uses = [
        e
        for e in edges
        if e.get("source") == "compactlayout_account_account_cl" and e.get("relation") == "uses"
    ]
    targets = {e["target"] for e in cl_uses}
    allowed = {"field_account_name", "field_account_phone"}
    unexpected = targets - allowed
    assert not unexpected, f"CompactLayout emitted unexpected uses targets: {unexpected}"


# ---------------------------------------------------------------------------
# E3 — Polymorphic lookups (multiple referenceTo)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def e3_result():
    return _extract("epicE_poly_lookup/force-app/main/default")


def test_e3_whoid_references_contact_extracted(e3_result):
    """Polymorphic WhoId__c --references--> object_contact EXTRACTED."""
    edges = _edges(e3_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "field_task__c_whoid__c"
            and e.get("target") == "object_contact"
            and e.get("relation") == "references"
        ),
        None,
    )
    assert edge is not None, "expected WhoId__c --references--> object_contact EXTRACTED"
    assert edge["confidence"] == "EXTRACTED"


def test_e3_whoid_references_lead_extracted(e3_result):
    """Polymorphic WhoId__c --references--> object_lead EXTRACTED."""
    edges = _edges(e3_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "field_task__c_whoid__c"
            and e.get("target") == "object_lead"
            and e.get("relation") == "references"
        ),
        None,
    )
    assert edge is not None, "expected WhoId__c --references--> object_lead EXTRACTED"
    assert edge["confidence"] == "EXTRACTED"


def test_e3_polymorphic_lookup_emits_exactly_two_references_edges(e3_result):
    """WhoId__c with two referenceTo elements must emit exactly 2 references edges."""
    edges = _edges(e3_result)
    ref_edges = [
        e
        for e in edges
        if e.get("source") == "field_task__c_whoid__c" and e.get("relation") == "references"
    ]
    assert len(ref_edges) == 2, (
        f"expected exactly 2 references edges from WhoId__c, got {len(ref_edges)}: {ref_edges}"
    )


def test_e3_negative_single_lookup_emits_exactly_one_references_edge(e3_result):
    """Single-referenceTo Lookup (Account__c → Account) must emit exactly ONE references edge.

    Negative control: the polymorphic-loop change must not affect single-referenceTo fields.
    """
    edges = _edges(e3_result)
    ref_edges = [
        e
        for e in edges
        if e.get("source") == "field_opportunity_account__c" and e.get("relation") == "references"
    ]
    assert len(ref_edges) == 1, (
        f"single-referenceTo lookup must emit exactly 1 references edge, got {len(ref_edges)}: {ref_edges}"
    )
    assert ref_edges[0]["target"] == "object_account"
    assert ref_edges[0]["confidence"] == "EXTRACTED"


def test_e3_negative_no_extra_edges_from_polymorphic_field(e3_result):
    """WhoId__c must produce no edges other than the 2 references edges (no phantom targets)."""
    edges = _edges(e3_result)
    who_edges = [e for e in edges if e.get("source") == "field_task__c_whoid__c"]
    non_ref = [e for e in who_edges if e.get("relation") != "references"]
    assert non_ref == [], f"unexpected non-references edges from WhoId__c: {non_ref}"
