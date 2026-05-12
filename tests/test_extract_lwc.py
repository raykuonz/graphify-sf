"""Tests for LWC extraction."""

from __future__ import annotations

from pathlib import Path


def test_extract_lwc_bundle_returns_node(simple_project_path):
    """Test that extract_lwc_bundle() returns component node."""
    from graphify_sf.extract.lwc import extract_lwc_bundle

    bundle_dir = simple_project_path / "force-app/main/default/lwc/accountCard"
    result = extract_lwc_bundle(bundle_dir)

    assert "nodes" in result
    assert "edges" in result
    assert len(result["nodes"]) >= 1


def test_extract_lwc_node_structure(simple_project_path):
    """Test that LWC component node has correct attributes."""
    from graphify_sf.extract.lwc import extract_lwc_bundle

    bundle_dir = simple_project_path / "force-app/main/default/lwc/accountCard"
    result = extract_lwc_bundle(bundle_dir)

    comp_node = result["nodes"][0]
    assert comp_node["label"] == "accountCard"
    assert comp_node["sf_type"] == "LWCComponent"
    assert comp_node["file_type"] == "lwc"


def test_extract_lwc_apex_import_creates_edge(simple_project_path):
    """Test that Apex import creates a reference edge."""
    from graphify_sf.extract.lwc import extract_lwc_bundle

    bundle_dir = simple_project_path / "force-app/main/default/lwc/accountCard"
    result = extract_lwc_bundle(bundle_dir)

    # Should have edge: accountCard -> AccountService
    calls_edges = [e for e in result["edges"] if e.get("relation") == "calls"]
    assert len(calls_edges) >= 1, "Should detect Apex import"

    targets = [e["target"] for e in calls_edges]
    assert any("accountservice" in t.lower() for t in targets)


def test_extract_lwc_apex_import_confidence(simple_project_path):
    """Test that Apex import edges have EXTRACTED confidence."""
    from graphify_sf.extract.lwc import extract_lwc_bundle

    bundle_dir = simple_project_path / "force-app/main/default/lwc/accountCard"
    result = extract_lwc_bundle(bundle_dir)

    calls_edges = [e for e in result["edges"] if e.get("relation") == "calls"]
    for edge in calls_edges:
        assert edge["confidence"] == "EXTRACTED"


def test_extract_lwc_bundle_detection(simple_project_path):
    """Test that bundle is detected by presence of .js file."""
    from graphify_sf.extract.lwc import extract_lwc_bundle

    bundle_dir = simple_project_path / "force-app/main/default/lwc/accountCard"
    result = extract_lwc_bundle(bundle_dir)

    # Should successfully extract
    assert len(result["nodes"]) >= 1


def test_extract_lwc_method_nodes(simple_project_path):
    """Test that LWC methods are extracted as child nodes."""
    from graphify_sf.extract.lwc import extract_lwc_bundle

    bundle_dir = simple_project_path / "force-app/main/default/lwc/accountCard"
    result = extract_lwc_bundle(bundle_dir)

    method_nodes = [n for n in result["nodes"] if n.get("sf_type") == "LWCMethod"]
    # accountCard has at least: connectedCallback, loadAccounts
    assert len(method_nodes) >= 1, "Should extract at least one method"


def test_extract_lwc_method_contains_edges(simple_project_path):
    """Test that methods have contains edges from component."""
    from graphify_sf.extract.lwc import extract_lwc_bundle

    bundle_dir = simple_project_path / "force-app/main/default/lwc/accountCard"
    result = extract_lwc_bundle(bundle_dir)

    contains_edges = [e for e in result["edges"] if e.get("relation") == "contains"]
    assert len(contains_edges) >= 1, "Should have contains edges for methods"


def test_extract_lwc_missing_bundle():
    """Test that extract handles missing bundles gracefully."""
    from graphify_sf.extract.lwc import extract_lwc_bundle

    result = extract_lwc_bundle(Path("/nonexistent/bundle"))
    # Should return empty results since .js file doesn't exist
    assert "nodes" in result
    assert "edges" in result


def test_extract_lwc_html_child_component_detection(tmp_path):
    """Test that HTML template detects child LWC components."""
    from graphify_sf.extract.lwc import extract_lwc_bundle

    # Create a bundle with child component reference
    bundle_dir = tmp_path / "parentCard"
    bundle_dir.mkdir()

    (bundle_dir / "parentCard.js").write_text("""
import { LightningElement } from 'lwc';

export default class ParentCard extends LightningElement {
    handleClick() {
        console.log('clicked');
    }
}
""")

    (bundle_dir / "parentCard.html").write_text("""
<template>
    <c-account-card></c-account-card>
</template>
""")

    result = extract_lwc_bundle(bundle_dir)

    uses_edges = [e for e in result["edges"] if e.get("relation") == "uses"]
    assert len(uses_edges) >= 1, "Should detect child component usage"

    targets = [e["target"] for e in uses_edges]
    # Node IDs are lowercase (e.g. "lwc_accountcard")
    assert any("accountcard" in t.lower() for t in targets)


def test_extract_lwc_kebab_to_camel_conversion():
    """Test kebab-case to camelCase conversion for component names."""
    from graphify_sf.extract.lwc import _kebab_to_camel

    assert _kebab_to_camel("account-card") == "accountCard"
    assert _kebab_to_camel("my-component-name") == "myComponentName"
    assert _kebab_to_camel("simple") == "simple"


def test_extract_lwc_import_c_namespace(tmp_path):
    """Test that c/ imports create edges to other LWC components."""
    from graphify_sf.extract.lwc import extract_lwc_bundle

    bundle_dir = tmp_path / "testComp"
    bundle_dir.mkdir()

    (bundle_dir / "testComp.js").write_text("""
import { LightningElement } from 'lwc';
import childComponent from 'c/childComponent';

export default class TestComp extends LightningElement {}
""")

    result = extract_lwc_bundle(bundle_dir)

    calls_edges = [e for e in result["edges"] if e.get("relation") == "calls"]
    targets = [e["target"] for e in calls_edges]
    # Node IDs are lowercase (e.g. "lwc_childcomponent")
    assert any("childcomponent" in t.lower() for t in targets)
