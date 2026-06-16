"""Integration tests for Epic F — Reporting & Packaging (graphify-sf v0.4.0).

Runs detect+extract on fixtures and asserts on nodes/edges (same data that
lands in graph.json links/nodes). Tests follow the same empirical pattern as
the other epic integration tests.

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
# F1 — Reports / Dashboards / Report Types
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def f1_result():
    return _extract("epicF_reporting/force-app/main/default")


# Report node


def test_f1_report_node_exists(f1_result):
    nodes = _nodes_by_id(f1_result)
    assert "report_accountsales" in nodes, "expected Report node report_accountsales"
    assert nodes["report_accountsales"]["sf_type"] == "Report"


# ReportType node


def test_f1_report_type_node_exists(f1_result):
    nodes = _nodes_by_id(f1_result)
    assert "reporttype_accountcustom" in nodes, "expected ReportType node reporttype_accountcustom"
    assert nodes["reporttype_accountcustom"]["sf_type"] == "ReportType"


# Dashboard node


def test_f1_dashboard_node_exists(f1_result):
    nodes = _nodes_by_id(f1_result)
    assert "dashboard_salesdashboard" in nodes, "expected Dashboard node dashboard_salesdashboard"
    assert nodes["dashboard_salesdashboard"]["sf_type"] == "Dashboard"


# Report --references--> ReportType EXTRACTED


def test_f1_report_references_report_type_extracted(f1_result):
    edges = _edges(f1_result)
    edge = next(
        (
            e
            for e in edges
            if e["source"] == "report_accountsales"
            and e["target"] == "reporttype_accountcustom"
            and e["relation"] == "references"
        ),
        None,
    )
    assert edge is not None, "expected references edge from Report to ReportType"
    assert edge["confidence"] == "EXTRACTED"


# Report --uses--> field_account_industry EXTRACTED (Account.Industry in XML)


def test_f1_report_uses_field_industry_extracted(f1_result):
    edges = _edges(f1_result)
    edge = next(
        (
            e
            for e in edges
            if e["source"] == "report_accountsales"
            and e["target"] == "field_account_industry"
            and e["relation"] == "uses"
        ),
        None,
    )
    assert edge is not None, "expected uses edge from Report to field_account_industry"
    assert edge["confidence"] == "EXTRACTED", "Object.Field format must be EXTRACTED"


# Report --uses--> field_account_annualrevenue EXTRACTED (columns + filter)


def test_f1_report_uses_field_annualrevenue_extracted(f1_result):
    edges = _edges(f1_result)
    edge = next(
        (
            e
            for e in edges
            if e["source"] == "report_accountsales"
            and e["target"] == "field_account_annualrevenue"
            and e["relation"] == "uses"
        ),
        None,
    )
    assert edge is not None, "expected uses edge from Report to field_account_annualrevenue"
    assert edge["confidence"] == "EXTRACTED"


# Dashboard --uses--> Report EXTRACTED


def test_f1_dashboard_uses_report_extracted(f1_result):
    edges = _edges(f1_result)
    edge = next(
        (
            e
            for e in edges
            if e["source"] == "dashboard_salesdashboard"
            and e["target"] == "report_accountsales"
            and e["relation"] == "uses"
        ),
        None,
    )
    assert edge is not None, "expected uses edge from Dashboard to Report"
    assert edge["confidence"] == "EXTRACTED"


# ReportType --references--> object_account EXTRACTED


def test_f1_report_type_references_object_account_extracted(f1_result):
    edges = _edges(f1_result)
    edge = next(
        (
            e
            for e in edges
            if e["source"] == "reporttype_accountcustom"
            and e["target"] == "object_account"
            and e["relation"] == "references"
        ),
        None,
    )
    assert edge is not None, "expected references edge from ReportType to object_account"
    assert edge["confidence"] == "EXTRACTED"


# ReportType --uses--> field_account_industry EXTRACTED (from sections)


def test_f1_report_type_uses_field_industry_extracted(f1_result):
    edges = _edges(f1_result)
    edge = next(
        (
            e
            for e in edges
            if e["source"] == "reporttype_accountcustom"
            and e["target"] == "field_account_industry"
            and e["relation"] == "uses"
        ),
        None,
    )
    assert edge is not None, "expected uses edge from ReportType to field_account_industry"
    assert edge["confidence"] == "EXTRACTED"


# NEGATIVE: the standard report-type name "AccountCustom" must NOT create an
# object_ node — Report references reporttype_accountcustom, never object_accountcustom.


def test_f1_negative_no_phantom_object_for_report_type_name(f1_result):
    nodes = _nodes_by_id(f1_result)
    assert "object_accountcustom" not in nodes, (
        "the reportType value 'AccountCustom' must not create an object_ node; "
        "it should only create a reporttype_ reference edge"
    )


# NEGATIVE: the CREATED_DATE standard formula column must NOT create any new
# CustomObject or ApexClass nodes.


def test_f1_negative_no_phantom_apex_or_object_for_standard_field(f1_result):
    nodes = _nodes_by_id(f1_result)
    spurious = [
        nid
        for nid, n in nodes.items()
        if "created_date" in nid and n.get("sf_type") in ("CustomObject", "ApexClass")
    ]
    assert spurious == [], f"standard field CREATED_DATE must not spawn object/apex nodes: {spurious}"


# NEGATIVE: dashboard must not use a report that doesn't exist in the fixture.


def test_f1_negative_dashboard_no_spurious_report_edge(f1_result):
    edges = _edges(f1_result)
    spurious = [
        e
        for e in edges
        if e["source"] == "dashboard_salesdashboard"
        and e["relation"] == "uses"
        and e["target"] != "report_accountsales"
    ]
    assert spurious == [], f"dashboard should only reference AccountSales report: {spurious}"


# ---------------------------------------------------------------------------
# F2 — Packaging & managed-namespace tagging
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def f2_result():
    return _extract("epicF_packaging/force-app/main/default")


# InstalledPackage node exists


def test_f2_installed_package_node_exists(f2_result):
    nodes = _nodes_by_id(f2_result)
    assert "installedpackage_npsp" in nodes, "expected InstalledPackage node installedpackage_npsp"
    assert nodes["installedpackage_npsp"]["sf_type"] == "InstalledPackage"


# InstalledPackage carries version attr from XML


def test_f2_installed_package_version_attr(f2_result):
    nodes = _nodes_by_id(f2_result)
    node = nodes["installedpackage_npsp"]
    assert node.get("version") == "3.200.0", f"expected version 3.200.0, got {node.get('version')}"


# Namespaced object node gets namespace attr


def test_f2_namespaced_object_node_exists(f2_result):
    nodes = _nodes_by_id(f2_result)
    assert "object_npsp__dataimport__c" in nodes, "expected npsp__DataImport__c object node"


def test_f2_namespace_attr_set_on_namespaced_object(f2_result):
    nodes = _nodes_by_id(f2_result)
    node = nodes["object_npsp__dataimport__c"]
    assert node.get("namespace") == "npsp", (
        f"expected namespace='npsp' on npsp__DataImport__c node, got {node.get('namespace')!r}"
    )


# NEGATIVE: a non-namespaced node must NOT have a namespace attr set


def test_f2_negative_no_namespace_on_plain_node(f1_result):
    """Account object in F1 fixture has no ns__ prefix — must have no namespace attr."""
    nodes = _nodes_by_id(f1_result)
    account = nodes.get("object_account")
    assert account is not None, "object_account should exist in F1 fixture"
    assert "namespace" not in account, (
        "plain Account object must not have a namespace attr"
    )


# NEGATIVE: InstalledPackage node must have no outgoing edges (F2 descoped sfdx-project.json)


def test_f2_no_depends_on_edges_for_installed_package(f2_result):
    edges = _edges(f2_result)
    pkg_edges = [e for e in edges if e["source"] == "installedpackage_npsp"]
    assert pkg_edges == [], (
        "sfdx-project.json Package/dependsOn wiring was descoped; "
        f"InstalledPackage should have no outgoing edges, got {pkg_edges}"
    )
