"""Tests for Object extraction."""

from __future__ import annotations

from pathlib import Path


def test_extract_custom_object_returns_node(simple_project_path):
    """Test that extract_custom_object() returns object node."""
    from graphify_sf.extract.object import extract_custom_object

    obj_path = simple_project_path / "force-app/main/default/objects/Account__c/Account__c.object-meta.xml"
    result = extract_custom_object(obj_path)

    assert "nodes" in result
    assert "edges" in result
    assert len(result["nodes"]) == 1


def test_extract_custom_object_node_structure(simple_project_path):
    """Test that object node has correct attributes."""
    from graphify_sf.extract.object import extract_custom_object

    obj_path = simple_project_path / "force-app/main/default/objects/Account__c/Account__c.object-meta.xml"
    result = extract_custom_object(obj_path)

    obj_node = result["nodes"][0]
    assert obj_node["label"] == "Account__c"
    assert obj_node["sf_type"] == "CustomObject"
    assert obj_node["file_type"] == "object"
    assert "source_file" in obj_node


def test_extract_custom_object_display_label(simple_project_path):
    """Test that object display label is extracted from XML."""
    from graphify_sf.extract.object import extract_custom_object

    obj_path = simple_project_path / "force-app/main/default/objects/Account__c/Account__c.object-meta.xml"
    result = extract_custom_object(obj_path)

    obj_node = result["nodes"][0]
    assert "display_label" in obj_node
    assert obj_node["display_label"] == "Account Custom"


def test_extract_custom_field_returns_node_and_edge(simple_project_path):
    """Test that extract_custom_field() returns field node and edge."""
    from graphify_sf.extract.object import extract_custom_field

    field_path = simple_project_path / "force-app/main/default/objects/Account__c/fields/Status__c.field-meta.xml"
    result = extract_custom_field(field_path)

    assert len(result["nodes"]) == 1
    assert len(result["edges"]) >= 1


def test_extract_custom_field_node_structure(simple_project_path):
    """Test that field node has correct attributes."""
    from graphify_sf.extract.object import extract_custom_field

    field_path = simple_project_path / "force-app/main/default/objects/Account__c/fields/Status__c.field-meta.xml"
    result = extract_custom_field(field_path)

    field_node = result["nodes"][0]
    assert "Status__c" in field_node["label"]
    assert "Account__c" in field_node["label"]
    assert field_node["sf_type"] == "CustomField"
    assert field_node["file_type"] == "object"


def test_extract_custom_field_contains_edge(simple_project_path):
    """Test that field has contains edge from parent object."""
    from graphify_sf.extract.object import extract_custom_field

    field_path = simple_project_path / "force-app/main/default/objects/Account__c/fields/Status__c.field-meta.xml"
    result = extract_custom_field(field_path)

    contains_edges = [e for e in result["edges"] if e.get("relation") == "contains"]
    assert len(contains_edges) >= 1

    edge = contains_edges[0]
    # Node IDs are lowercase (e.g. "object_account__c")
    assert "account__c" in edge["source"].lower()
    assert edge["confidence"] == "EXTRACTED"


def test_extract_custom_field_type(simple_project_path):
    """Test that field type is captured."""
    from graphify_sf.extract.object import extract_custom_field

    field_path = simple_project_path / "force-app/main/default/objects/Account__c/fields/Status__c.field-meta.xml"
    result = extract_custom_field(field_path)

    field_node = result["nodes"][0]
    assert "field_type" in field_node
    assert field_node["field_type"] == "Picklist"


def test_extract_custom_field_display_label(simple_project_path):
    """Test that field display label is extracted."""
    from graphify_sf.extract.object import extract_custom_field

    field_path = simple_project_path / "force-app/main/default/objects/Account__c/fields/Status__c.field-meta.xml"
    result = extract_custom_field(field_path)

    field_node = result["nodes"][0]
    assert "display_label" in field_node
    assert field_node["display_label"] == "Status"


def test_extract_object_missing_file():
    """Test that extract handles missing files gracefully."""
    from graphify_sf.extract.object import extract_custom_object

    result = extract_custom_object(Path("/nonexistent/object.object-meta.xml"))
    assert result == {"nodes": [], "edges": []}


def test_extract_object_malformed_xml(tmp_path):
    """Test that extract handles malformed XML gracefully."""
    from graphify_sf.extract.object import extract_custom_object

    bad_obj = tmp_path / "BadObject.object-meta.xml"
    bad_obj.write_text("<?xml version='1.0'?><CustomObject><unclosed>")

    result = extract_custom_object(bad_obj)
    # Should still create the node from filename
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["label"] == "BadObject"


def test_extract_child_object_generic(tmp_path):
    """Test that child object metadata (validation rules, etc.) is extracted."""
    from graphify_sf.extract.object import extract_child_object

    # Create a validation rule file
    vr_dir = tmp_path / "objects" / "Account" / "validationRules"
    vr_dir.mkdir(parents=True)
    vr_path = vr_dir / "CheckStatus.validationRule-meta.xml"
    vr_path.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<ValidationRule xmlns="http://soap.sforce.com/2006/04/metadata">
    <fullName>CheckStatus</fullName>
    <active>true</active>
</ValidationRule>
""")

    result = extract_child_object(vr_path)

    assert len(result["nodes"]) == 1
    child_node = result["nodes"][0]
    assert child_node["sf_type"] == "ValidationRule"
    assert "CheckStatus" in child_node["label"]

    # Should have contains edge from parent object
    contains_edges = [e for e in result["edges"] if e.get("relation") == "contains"]
    assert len(contains_edges) == 1
