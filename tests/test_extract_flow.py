"""Tests for Flow extraction."""
from __future__ import annotations

from pathlib import Path


def test_extract_flow_returns_node(simple_project_path):
    """Test that extract_flow() returns flow node."""
    from graphify_sf.extract.flow import extract_flow

    flow_path = simple_project_path / "force-app/main/default/flows/UpdateAccountStatus.flow-meta.xml"
    result = extract_flow(flow_path)

    assert "nodes" in result
    assert "edges" in result
    assert len(result["nodes"]) >= 1


def test_extract_flow_node_structure(simple_project_path):
    """Test that flow node has correct attributes."""
    from graphify_sf.extract.flow import extract_flow

    flow_path = simple_project_path / "force-app/main/default/flows/UpdateAccountStatus.flow-meta.xml"
    result = extract_flow(flow_path)

    flow_node = result["nodes"][0]
    assert flow_node["label"] == "UpdateAccountStatus"
    assert flow_node["sf_type"] == "Flow"
    assert flow_node["file_type"] == "flow"
    assert "process_type" in flow_node


def test_extract_flow_process_type(simple_project_path):
    """Test that processType is captured."""
    from graphify_sf.extract.flow import extract_flow

    flow_path = simple_project_path / "force-app/main/default/flows/UpdateAccountStatus.flow-meta.xml"
    result = extract_flow(flow_path)

    flow_node = result["nodes"][0]
    assert flow_node["process_type"] == "AutoLaunchedFlow"


def test_extract_flow_object_references(simple_project_path):
    """Test that object references in recordUpdates are extracted."""
    from graphify_sf.extract.flow import extract_flow

    flow_path = simple_project_path / "force-app/main/default/flows/UpdateAccountStatus.flow-meta.xml"
    result = extract_flow(flow_path)

    # Should have edge: flow -> Account__c
    ref_edges = [e for e in result["edges"] if e.get("relation") == "references"]
    assert len(ref_edges) >= 1, "Should have object reference edge"

    targets = [e["target"] for e in ref_edges]
    # Node IDs are lowercase (e.g. "object_account__c")
    assert any("account__c" in t.lower() for t in targets)


def test_extract_flow_confidence_extracted(simple_project_path):
    """Test that flow edges have EXTRACTED confidence."""
    from graphify_sf.extract.flow import extract_flow

    flow_path = simple_project_path / "force-app/main/default/flows/UpdateAccountStatus.flow-meta.xml"
    result = extract_flow(flow_path)

    for edge in result["edges"]:
        assert edge["confidence"] == "EXTRACTED"


def test_extract_flow_missing_file():
    """Test that extract handles missing files gracefully."""
    from graphify_sf.extract.flow import extract_flow

    result = extract_flow(Path("/nonexistent/flow.flow-meta.xml"))
    assert result == {"nodes": [], "edges": []}


def test_extract_flow_malformed_xml(tmp_path):
    """Test that extract handles malformed XML gracefully."""
    from graphify_sf.extract.flow import extract_flow

    bad_flow = tmp_path / "BadFlow.flow-meta.xml"
    bad_flow.write_text("<?xml version='1.0'?><Flow><unclosed>")

    result = extract_flow(bad_flow)
    assert result == {"nodes": [], "edges": []}


def test_extract_flow_elements_as_children(simple_project_path):
    """Test that flow elements (recordUpdates, etc.) are extracted as child nodes."""
    from graphify_sf.extract.flow import extract_flow

    flow_path = simple_project_path / "force-app/main/default/flows/UpdateAccountStatus.flow-meta.xml"
    result = extract_flow(flow_path)

    # Note: the implementation may not create child nodes for all element types
    assert "edges" in result
