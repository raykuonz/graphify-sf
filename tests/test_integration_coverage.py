"""Integration tests for Epic A — runs detect+extract on fixtures and asserts on
nodes/edges (same data that lands in graph.json links/nodes).

Each test calls detect() then extract() on a fixture directory and asserts on
node ids, edge relations, confidence values, and negative controls.
Follows the empirical style of tests/test_extract_pipeline.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _extract(fixture_rel: str) -> dict:
    """Run detect + per-file extraction + cross-reference resolution on a fixture.

    Bypasses the networkx graph-build stage (which needs the optional networkx dep)
    by calling _extract_file and _resolve_cross_references directly — the same
    nodes/edges that would land in graph.json links/nodes.
    """
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
# A1 — Apex outbound HTTP callouts
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def a1_result():
    return _extract("epicA_callout/force-app/main/default")


def test_a1_named_credential_node_exists(a1_result):
    nodes = _nodes_by_id(a1_result)
    assert "namedcredential_my_nc" in nodes


def test_a1_calloutnamed_makes_callout_nc_extracted(a1_result):
    edges = _edges(a1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "apex_calloutnamed"
            and e.get("target") == "namedcredential_my_nc"
            and e.get("relation") == "makes_callout"
        ),
        None,
    )
    assert edge is not None, "expected makes_callout edge from CalloutNamed to namedcredential_my_nc"
    assert edge["confidence"] == "EXTRACTED"


def test_a1_external_endpoint_node_exists(a1_result):
    nodes = _nodes_by_id(a1_result)
    ep = next((n for n in nodes.values() if n.get("sf_type") == "ExternalEndpoint"), None)
    assert ep is not None, "expected ExternalEndpoint node for literal URL"
    assert "netsuite" in ep["id"]


def test_a1_calloutliteral_makes_callout_inferred(a1_result):
    edges = _edges(a1_result)
    edge = next(
        (e for e in edges if e.get("source") == "apex_calloutliteral" and e.get("relation") == "makes_callout"),
        None,
    )
    assert edge is not None, "expected makes_callout edge from CalloutLiteral"
    assert edge["confidence"] == "INFERRED"


def test_a1_no_callout_class_emits_no_makes_callout_edge(a1_result):
    edges = _edges(a1_result)
    bad = [e for e in edges if e.get("source") == "apex_nocallout" and e.get("relation") == "makes_callout"]
    assert bad == [], "NoCallout class must not emit makes_callout edges"


# ---------------------------------------------------------------------------
# A2 — Flow callouts (shares fixture with A1)
# ---------------------------------------------------------------------------


def test_a2_flow_makes_callout_to_nc_extracted(a1_result):
    edges = _edges(a1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "flow_calloutflow"
            and e.get("target") == "namedcredential_my_nc"
            and e.get("relation") == "makes_callout"
        ),
        None,
    )
    assert edge is not None, "expected makes_callout edge from CalloutFlow to namedcredential_my_nc"
    assert edge["confidence"] == "EXTRACTED"


# ---------------------------------------------------------------------------
# A3 — RemoteSiteSetting correct extension + endpoint_url
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def a3_result():
    return _extract("epicA_remote_site/force-app/main/default")


def test_a3_remote_site_node_exists(a3_result):
    nodes = _nodes_by_id(a3_result)
    assert "remotesitesetting_foo" in nodes


def test_a3_remote_site_sf_type(a3_result):
    nodes = _nodes_by_id(a3_result)
    assert nodes["remotesitesetting_foo"]["sf_type"] == "RemoteSiteSetting"


def test_a3_remote_site_endpoint_url(a3_result):
    nodes = _nodes_by_id(a3_result)
    node = nodes["remotesitesetting_foo"]
    assert node.get("endpoint_url") == "https://api.example.com"


# ---------------------------------------------------------------------------
# A4 — External Data Source + External Object
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def a4_result():
    return _extract("epicA_ext_datasource/force-app/main/default")


def test_a4_external_datasource_node(a4_result):
    nodes = _nodes_by_id(a4_result)
    assert "externaldatasource_myeds" in nodes
    assert nodes["externaldatasource_myeds"]["sf_type"] == "ExternalDataSource"


def test_a4_external_object_node(a4_result):
    nodes = _nodes_by_id(a4_result)
    assert "object_myext__x" in nodes
    assert nodes["object_myext__x"]["sf_type"] == "ExternalObject"


def test_a4_eds_uses_nc_extracted(a4_result):
    edges = _edges(a4_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "externaldatasource_myeds"
            and e.get("target") == "namedcredential_my_nc"
            and e.get("relation") == "uses"
        ),
        None,
    )
    assert edge is not None, "expected uses edge from ExternalDataSource to NamedCredential"
    assert edge["confidence"] == "EXTRACTED"


def test_a4_external_object_backed_by_eds_extracted(a4_result):
    edges = _edges(a4_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "object_myext__x"
            and e.get("target") == "externaldatasource_myeds"
            and e.get("relation") == "backed_by"
        ),
        None,
    )
    assert edge is not None, "expected backed_by edge from ExternalObject to ExternalDataSource"
    assert edge["confidence"] == "EXTRACTED"


# ---------------------------------------------------------------------------
# A5 — Platform Events / CDC
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def a5_result():
    return _extract("epicA_platform_events/force-app/main/default")


def test_a5_platform_event_node_type(a5_result):
    nodes = _nodes_by_id(a5_result)
    assert "object_order_event__e" in nodes
    assert nodes["object_order_event__e"]["sf_type"] == "PlatformEvent"


def test_a5_publishes_edge_from_publisher(a5_result):
    edges = _edges(a5_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "apex_eventpublisher"
            and e.get("target") == "object_order_event__e"
            and e.get("relation") == "publishes"
        ),
        None,
    )
    assert edge is not None, "expected publishes edge from EventPublisher to Order_Event__e"
    assert edge["confidence"] == "EXTRACTED"


def test_a5_subscribes_edge_from_trigger(a5_result):
    edges = _edges(a5_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "trigger_ordereventtrigger"
            and e.get("target") == "object_order_event__e"
            and e.get("relation") == "subscribes"
        ),
        None,
    )
    assert edge is not None, "expected subscribes edge from OrderEventTrigger to Order_Event__e"
    assert edge["confidence"] == "EXTRACTED"


# ---------------------------------------------------------------------------
# A6 — Apex reads Custom Metadata / Custom Settings
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def a6_result():
    return _extract("epicA_config_read/force-app/main/default")


def test_a6_custom_setting_node_type(a6_result):
    nodes = _nodes_by_id(a6_result)
    assert "object_my_settings__c" in nodes
    assert nodes["object_my_settings__c"]["sf_type"] == "CustomSetting"


def test_a6_reads_config_edge_inferred(a6_result):
    edges = _edges(a6_result)
    edge = next(
        (e for e in edges if e.get("source") == "apex_configreader" and e.get("relation") == "reads_config"),
        None,
    )
    assert edge is not None, "expected reads_config edge from ConfigReader"
    assert edge["confidence"] == "INFERRED"


# ---------------------------------------------------------------------------
# A7 — AuthProvider / CSP Trusted Sites / CORS
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def a7_result():
    return _extract("epicA_auth_csp_cors/force-app/main/default")


def test_a7_auth_provider_node(a7_result):
    nodes = _nodes_by_id(a7_result)
    assert "authprovider_myauthprovider" in nodes
    assert nodes["authprovider_myauthprovider"]["sf_type"] == "AuthProvider"


def test_a7_csp_trusted_site_node_with_endpoint_url(a7_result):
    nodes = _nodes_by_id(a7_result)
    assert "csptrustedsite_mysite" in nodes
    node = nodes["csptrustedsite_mysite"]
    assert node["sf_type"] == "CspTrustedSite"
    assert node.get("endpoint_url") == "https://cdn.example.com"


def test_a7_cors_origin_node_with_url_pattern(a7_result):
    nodes = _nodes_by_id(a7_result)
    assert "corsorigin_myorigin" in nodes
    node = nodes["corsorigin_myorigin"]
    assert node["sf_type"] == "CorsOrigin"
    assert node.get("url_pattern") == "https://app.example.com"


# ---------------------------------------------------------------------------
# A8 — Workflow Outbound Messages
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def a8_result():
    return _extract("epicA_workflow_outbound/force-app/main/default")


def test_a8_outbound_message_node_exists(a8_result):
    nodes = _nodes_by_id(a8_result)
    assert "workflowoutboundmessage_account_sendorder" in nodes


def test_a8_outbound_message_sf_type(a8_result):
    nodes = _nodes_by_id(a8_result)
    node = nodes["workflowoutboundmessage_account_sendorder"]
    assert node["sf_type"] == "WorkflowOutboundMessage"


def test_a8_outbound_message_endpoint_url(a8_result):
    nodes = _nodes_by_id(a8_result)
    node = nodes["workflowoutboundmessage_account_sendorder"]
    assert node.get("endpoint_url") == "https://erp.example.com/orders"


def test_a8_workflow_contains_outbound_message_extracted(a8_result):
    edges = _edges(a8_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "workflow_account"
            and e.get("target") == "workflowoutboundmessage_account_sendorder"
            and e.get("relation") == "contains"
        ),
        None,
    )
    assert edge is not None, "expected contains edge from workflow_account to outbound message"
    assert edge["confidence"] == "EXTRACTED"
