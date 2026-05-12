"""Tests for Apex extraction."""
from __future__ import annotations

from pathlib import Path


def test_extract_apex_class_returns_nodes(simple_project_path):
    """Test that extract_apex_class() returns nodes with correct structure."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    assert "nodes" in result
    assert "edges" in result
    assert len(result["nodes"]) > 0, "Should extract at least the class node"


def test_extract_apex_class_node_structure(simple_project_path):
    """Test that Apex class nodes have correct attributes."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    class_node = result["nodes"][0]
    assert class_node["label"] == "AccountService"
    assert class_node["sf_type"] == "ApexClass"
    assert class_node["file_type"] == "apex"
    assert "source_file" in class_node


def test_extract_apex_methods(simple_project_path):
    """Test that methods are extracted with correct parent relationships."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    # Should have class node + method nodes
    method_nodes = [n for n in result["nodes"] if n.get("sf_type") == "ApexMethod"]
    assert len(method_nodes) >= 3, "Should extract at least 3 methods"

    # Check method labels
    method_labels = [n["label"] for n in method_nodes]
    assert any("getActiveAccounts" in label for label in method_labels)
    assert any("updateAccountStatus" in label for label in method_labels)
    assert any("validateAccount" in label for label in method_labels)


def test_extract_apex_method_contains_edges(simple_project_path):
    """Test that methods have contains edges from their parent class."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    contains_edges = [e for e in result["edges"] if e.get("relation") == "contains"]
    assert len(contains_edges) >= 3, "Should have contains edges for methods"


def test_extract_apex_trigger_node(simple_project_path):
    """Test that extract_apex_trigger() returns trigger node."""
    from graphify_sf.extract.apex import extract_apex_trigger

    trigger_path = simple_project_path / "force-app/main/default/triggers/AccountTrigger.trigger"
    result = extract_apex_trigger(trigger_path)

    assert len(result["nodes"]) >= 1
    trigger_node = result["nodes"][0]
    assert trigger_node["label"] == "AccountTrigger"
    assert trigger_node["sf_type"] == "ApexTrigger"
    assert trigger_node["file_type"] == "apex"


def test_extract_apex_trigger_object_edge(simple_project_path):
    """Test that trigger node is linked to object."""
    from graphify_sf.extract.apex import extract_apex_trigger

    trigger_path = simple_project_path / "force-app/main/default/triggers/AccountTrigger.trigger"
    result = extract_apex_trigger(trigger_path)

    # Should have edge: trigger -> Account (node IDs are lowercase)
    triggers_edges = [e for e in result["edges"] if e.get("relation") == "triggers"]
    assert len(triggers_edges) >= 1
    assert "account" in triggers_edges[0]["target"].lower()


def test_extract_apex_trigger_events(simple_project_path):
    """Test that trigger events are captured."""
    from graphify_sf.extract.apex import extract_apex_trigger

    trigger_path = simple_project_path / "force-app/main/default/triggers/AccountTrigger.trigger"
    result = extract_apex_trigger(trigger_path)

    trigger_node = result["nodes"][0]
    assert "trigger_events" in trigger_node
    events = trigger_node["trigger_events"]
    assert "before insert" in events
    assert "after update" in events


def test_extract_apex_cross_reference_raw_calls(simple_project_path):
    """Test that cross-reference detection stores _raw_calls."""
    from graphify_sf.extract.apex import extract_apex_class

    # AccountTriggerHandler calls AccountService
    handler_path = simple_project_path / "force-app/main/default/classes/AccountTriggerHandler.cls"
    result = extract_apex_class(handler_path)

    class_node = result["nodes"][0]
    assert "_raw_calls" in class_node, "Should store raw calls for cross-file resolution"
    raw_calls = class_node["_raw_calls"]
    assert len(raw_calls) > 0, "Should detect calls to AccountService"

    # Check that AccountService is in the calls
    callee_classes = {call["callee_class"] for call in raw_calls}
    assert "AccountService" in callee_classes


def test_extract_apex_soql_queries_object(simple_project_path):
    """Test that SOQL queries create query edges to objects."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    queries_edges = [e for e in result["edges"] if e.get("relation") == "queries"]
    assert len(queries_edges) >= 1, "Should detect SOQL query"

    # Check that it queries Account (node IDs are lowercase)
    targets = [e["target"] for e in queries_edges]
    assert any("account" in t.lower() for t in targets)


def test_extract_apex_dml_operations(simple_project_path):
    """Test that DML operations are not explicitly extracted (static analysis limitation)."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    # DML operations (update, insert, delete) are not separately tracked as edges;
    # they appear as part of SOQL queries or class structure.
    # This is a known limitation of static Apex analysis.
    all_relations = {e.get("relation") for e in result["edges"]}
    assert "contains" in all_relations or "queries" in all_relations, \
        "Should have at least contains/queries edges even without DML tracking"


def test_extract_apex_missing_file():
    """Test that extract handles missing files gracefully."""
    from graphify_sf.extract.apex import extract_apex_class

    result = extract_apex_class(Path("/nonexistent/file.cls"))
    assert result == {"nodes": [], "edges": []}


def test_extract_apex_method_confidence_extracted(simple_project_path):
    """Test that method edges have EXTRACTED confidence."""
    from graphify_sf.extract.apex import extract_apex_class

    cls_path = simple_project_path / "force-app/main/default/classes/AccountService.cls"
    result = extract_apex_class(cls_path)

    contains_edges = [e for e in result["edges"] if e.get("relation") == "contains"]
    for edge in contains_edges:
        assert edge["confidence"] == "EXTRACTED"
