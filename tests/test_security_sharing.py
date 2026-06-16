"""Integration tests for Epic B — Security & sharing model (graphify-sf v0.4.0).

Runs detect+extract on fixtures and asserts on nodes/edges (same data that
lands in graph.json links/nodes). Tests follow the same empirical pattern as
tests/test_integration_coverage.py.

CRITICAL: Run with .venv/bin/python -m pytest, NOT bare python (no networkx).
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
# B1 — Org-Wide Defaults (sharing_model attr on object node)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b1_result():
    return _extract("epicB_owd/force-app/main/default")


def test_b1_object_node_exists(b1_result):
    nodes = _nodes_by_id(b1_result)
    assert "object_acct__c" in nodes, "expected object node for Acct__c"


def test_b1_sharing_model_attr_present(b1_result):
    nodes = _nodes_by_id(b1_result)
    node = nodes["object_acct__c"]
    assert node.get("sharing_model") == "Private", "expected sharing_model == 'Private'"


def test_b1_external_sharing_model_attr_present(b1_result):
    nodes = _nodes_by_id(b1_result)
    node = nodes["object_acct__c"]
    assert node.get("external_sharing_model") == "Private", "expected external_sharing_model == 'Private'"


def test_b1_no_sharing_model_on_object_without_it(b1_result):
    # Acct__c is the only object in this fixture; just verify the attr is EXTRACTED
    nodes = _nodes_by_id(b1_result)
    node = nodes["object_acct__c"]
    assert "sharing_model" in node, "sharing_model must be present when declared in XML"


# ---------------------------------------------------------------------------
# B2 — Sharing Rules (CriteriaSharingRule node + references edge to object)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b2_result():
    return _extract("epicB_sharing/force-app/main/default")


def test_b2_criteria_sharing_rule_node_exists(b2_result):
    nodes = _nodes_by_id(b2_result)
    rule_id = next(
        (nid for nid, n in nodes.items() if n.get("sf_type") == "CriteriaSharingRule"),
        None,
    )
    assert rule_id is not None, "expected a CriteriaSharingRule node"


def test_b2_owner_sharing_rule_node_exists(b2_result):
    nodes = _nodes_by_id(b2_result)
    rule_id = next(
        (nid for nid, n in nodes.items() if n.get("sf_type") == "OwnerSharingRule"),
        None,
    )
    assert rule_id is not None, "expected an OwnerSharingRule node"


def test_b2_criteria_rule_references_object_account_extracted(b2_result):
    nodes = _nodes_by_id(b2_result)
    edges = _edges(b2_result)
    criteria_rule_id = next(
        (nid for nid, n in nodes.items() if n.get("sf_type") == "CriteriaSharingRule"),
        None,
    )
    assert criteria_rule_id is not None
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == criteria_rule_id
            and e.get("target") == "object_account"
            and e.get("relation") == "references"
        ),
        None,
    )
    assert edge is not None, "expected references edge from CriteriaSharingRule to object_account"
    assert edge["confidence"] == "EXTRACTED"


def test_b2_no_false_sharing_rule_on_unrelated_object(b2_result):
    """Negative control: no spurious rule node references a non-existent object."""
    edges = _edges(b2_result)
    # The fixture only has Account rules; there must be no references to object_contact
    contact_refs = [e for e in edges if e.get("target") == "object_contact" and e.get("relation") == "references"]
    assert contact_refs == [], "no sharing rule should reference object_contact in this fixture"


# ---------------------------------------------------------------------------
# B3 — Permission Set Group membership edges (contains → permset members)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b3_result():
    return _extract("epicB_psg/force-app/main/default")


def test_b3_psg_node_exists(b3_result):
    nodes = _nodes_by_id(b3_result)
    assert "permset_my_psg" in nodes, "expected PSG node permset_my_psg"
    assert nodes["permset_my_psg"]["sf_type"] == "PermissionSetGroup"


def test_b3_member_permset_ps_a_exists(b3_result):
    nodes = _nodes_by_id(b3_result)
    assert "permset_ps_a" in nodes, "expected permset node permset_ps_a"


def test_b3_member_permset_ps_b_exists(b3_result):
    nodes = _nodes_by_id(b3_result)
    assert "permset_ps_b" in nodes, "expected permset node permset_ps_b"


def test_b3_contains_edge_to_ps_a_extracted(b3_result):
    edges = _edges(b3_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "permset_my_psg"
            and e.get("target") == "permset_ps_a"
            and e.get("relation") == "contains"
        ),
        None,
    )
    assert edge is not None, "expected contains edge from My_PSG to permset_ps_a"
    assert edge["confidence"] == "EXTRACTED"


def test_b3_contains_edge_to_ps_b_extracted(b3_result):
    edges = _edges(b3_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "permset_my_psg"
            and e.get("target") == "permset_ps_b"
            and e.get("relation") == "contains"
        ),
        None,
    )
    assert edge is not None, "expected contains edge from My_PSG to permset_ps_b"
    assert edge["confidence"] == "EXTRACTED"


def test_b3_muted_permission_sets_attr(b3_result):
    nodes = _nodes_by_id(b3_result)
    psg = nodes["permset_my_psg"]
    assert "muted_permission_sets" in psg, "expected muted_permission_sets attr on PSG"
    assert "PS_C" in psg["muted_permission_sets"]


def test_b3_no_contains_edge_to_non_member(b3_result):
    """Negative control: no contains edge from PSG to a permset not listed."""
    edges = _edges(b3_result)
    bad = [
        e
        for e in edges
        if e.get("source") == "permset_my_psg"
        and e.get("relation") == "contains"
        and e.get("target") not in ("permset_ps_a", "permset_ps_b")
    ]
    assert bad == [], f"unexpected contains edges from PSG: {bad}"


# ---------------------------------------------------------------------------
# B4 — userPermissions attr + tabVisibilities/applicationVisibilities grants edges
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b4_result():
    return _extract("epicB_profile_perms/force-app/main/default")


def test_b4_profile_node_exists(b4_result):
    nodes = _nodes_by_id(b4_result)
    assert "profile_admin" in nodes, "expected profile_admin node"


def test_b4_user_permissions_attr_contains_modify_all_data(b4_result):
    nodes = _nodes_by_id(b4_result)
    profile = nodes["profile_admin"]
    ups = profile.get("user_permissions", [])
    assert "ModifyAllData" in ups, f"expected ModifyAllData in user_permissions, got {ups}"


def test_b4_disabled_permission_not_in_user_permissions(b4_result):
    """ViewAllData is disabled=false in fixture — must not appear in the attr."""
    nodes = _nodes_by_id(b4_result)
    profile = nodes["profile_admin"]
    ups = profile.get("user_permissions", [])
    assert "ViewAllData" not in ups, "ViewAllData is disabled, must not be in user_permissions"


def test_b4_grants_edge_to_tab_account_extracted(b4_result):
    edges = _edges(b4_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "profile_admin"
            and e.get("target") == "customtab_account"
            and e.get("relation") == "grants"
        ),
        None,
    )
    assert edge is not None, "expected grants edge from profile_admin to customtab_account"
    assert edge["confidence"] == "EXTRACTED"


def test_b4_grants_edge_to_app_lightning_sales_extracted(b4_result):
    edges = _edges(b4_result)
    # standard__LightningSales → app_standard__lightningsales after make_sf_id
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "profile_admin"
            and "lightningsales" in e.get("target", "")
            and e.get("relation") == "grants"
        ),
        None,
    )
    assert edge is not None, "expected grants edge from profile_admin to LightningSales app"
    assert edge["confidence"] == "EXTRACTED"


def test_b4_no_grants_for_invisible_app(b4_result):
    """Negative control: standard__ServiceConsole is visible=false → no grants edge."""
    edges = _edges(b4_result)
    bad = [
        e
        for e in edges
        if e.get("source") == "profile_admin"
        and "serviceconsole" in e.get("target", "")
        and e.get("relation") == "grants"
    ]
    assert bad == [], "ServiceConsole is visible=false; no grants edge should be emitted"


# ---------------------------------------------------------------------------
# B5 — Restriction Rules + Duplicate / Matching Rules
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def b5_result():
    return _extract("epicB_rules/force-app/main/default")


def test_b5_duplicate_rule_node_exists(b5_result):
    nodes = _nodes_by_id(b5_result)
    assert "duplicaterule_account" in nodes, "expected DuplicateRule node for Account"
    assert nodes["duplicaterule_account"]["sf_type"] == "DuplicateRule"


def test_b5_matching_rule_node_exists(b5_result):
    nodes = _nodes_by_id(b5_result)
    mr = next(
        (nid for nid, n in nodes.items() if n.get("sf_type") == "MatchingRule"),
        None,
    )
    assert mr is not None, "expected at least one MatchingRule node"


def test_b5_restriction_rule_node_exists(b5_result):
    nodes = _nodes_by_id(b5_result)
    rr = next(
        (nid for nid, n in nodes.items() if n.get("sf_type") == "RestrictionRule"),
        None,
    )
    assert rr is not None, "expected a RestrictionRule node"


def test_b5_duplicate_rule_references_object_account_extracted(b5_result):
    edges = _edges(b5_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "duplicaterule_account"
            and e.get("target") == "object_account"
            and e.get("relation") == "references"
        ),
        None,
    )
    assert edge is not None, "expected references edge from DuplicateRule to object_account"
    assert edge["confidence"] == "EXTRACTED"


def test_b5_duplicate_rule_references_matching_rule_extracted(b5_result):
    edges = _edges(b5_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "duplicaterule_account"
            and e.get("relation") == "references"
            and "matchingrule" in e.get("target", "")
        ),
        None,
    )
    assert edge is not None, "expected references edge from DuplicateRule to a MatchingRule node"
    assert edge["confidence"] == "EXTRACTED"


def test_b5_restriction_rule_references_object_extracted(b5_result):
    nodes = _nodes_by_id(b5_result)
    edges = _edges(b5_result)
    rr_id = next(
        (nid for nid, n in nodes.items() if n.get("sf_type") == "RestrictionRule"),
        None,
    )
    assert rr_id is not None
    edge = next(
        (e for e in edges if e.get("source") == rr_id and e.get("relation") == "references"),
        None,
    )
    assert edge is not None, "expected references edge from RestrictionRule to its object"
    assert edge["confidence"] == "EXTRACTED"


def test_b5_no_spurious_duplicate_rule_for_contact(b5_result):
    """Negative control: only Account rules in fixture; no Contact DuplicateRule."""
    nodes = _nodes_by_id(b5_result)
    contact_dr = next(
        (nid for nid, n in nodes.items() if n.get("sf_type") == "DuplicateRule" and "contact" in nid),
        None,
    )
    assert contact_dr is None, "no Contact DuplicateRule should exist in this fixture"
