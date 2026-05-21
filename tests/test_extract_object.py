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


# ---------------------------------------------------------------------------
# Lookup / MasterDetail reference edges
# ---------------------------------------------------------------------------

_NS = 'xmlns="http://soap.sforce.com/2006/04/metadata"'


def test_extract_custom_field_lookup_creates_references_edge(tmp_path):
    """A Lookup field creates a 'references' edge to the target object."""
    from graphify_sf.extract.object import extract_custom_field

    obj_dir = tmp_path / "objects" / "Opportunity__c" / "fields"
    obj_dir.mkdir(parents=True)
    field = obj_dir / "Account__c.field-meta.xml"
    field.write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<CustomField {_NS}>
    <fullName>Account__c</fullName>
    <label>Account</label>
    <type>Lookup</type>
    <referenceTo>Account</referenceTo>
</CustomField>
""")

    result = extract_custom_field(field)
    ref_edges = [e for e in result["edges"] if e.get("relation") == "references"]
    assert len(ref_edges) == 1
    assert "account" in ref_edges[0]["target"].lower()
    assert ref_edges[0]["confidence"] == "EXTRACTED"


def test_extract_custom_field_master_detail_creates_master_detail_edge(tmp_path):
    """A MasterDetail field creates a 'master_detail' (not 'references') edge."""
    from graphify_sf.extract.object import extract_custom_field

    obj_dir = tmp_path / "objects" / "LineItem__c" / "fields"
    obj_dir.mkdir(parents=True)
    field = obj_dir / "Order__c.field-meta.xml"
    field.write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<CustomField {_NS}>
    <fullName>Order__c</fullName>
    <label>Order</label>
    <type>MasterDetail</type>
    <referenceTo>Order__c</referenceTo>
</CustomField>
""")

    result = extract_custom_field(field)
    md_edges = [e for e in result["edges"] if e.get("relation") == "master_detail"]
    ref_edges = [e for e in result["edges"] if e.get("relation") == "references"]
    assert len(md_edges) == 1, "Should use 'master_detail' relation for MasterDetail fields"
    assert len(ref_edges) == 0, "Should NOT use 'references' for MasterDetail"
    assert "order__c" in md_edges[0]["target"].lower()


def test_extract_custom_field_lookup_no_reference_to_no_edge(tmp_path):
    """A Lookup field without referenceTo produces no references edge."""
    from graphify_sf.extract.object import extract_custom_field

    obj_dir = tmp_path / "objects" / "MyObj__c" / "fields"
    obj_dir.mkdir(parents=True)
    field = obj_dir / "SomeField__c.field-meta.xml"
    field.write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<CustomField {_NS}>
    <fullName>SomeField__c</fullName>
    <label>Some Field</label>
    <type>Lookup</type>
</CustomField>
""")

    result = extract_custom_field(field)
    ref_edges = [e for e in result["edges"] if e.get("relation") in ("references", "master_detail")]
    assert len(ref_edges) == 0


# ---------------------------------------------------------------------------
# ValidationRule → field formula references
# ---------------------------------------------------------------------------


def test_extract_validation_rule_custom_field_reference(tmp_path):
    """ValidationRule formula referencing a custom field creates an INFERRED references edge."""
    from graphify_sf.extract.object import extract_child_object

    vr_dir = tmp_path / "objects" / "Opportunity" / "validationRules"
    vr_dir.mkdir(parents=True)
    vr = vr_dir / "RequireCloseDate.validationRule-meta.xml"
    vr.write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<ValidationRule {_NS}>
    <fullName>RequireCloseDate</fullName>
    <active>true</active>
    <errorConditionFormula>AND(ISBLANK(CloseDate__c), Stage__c = 'Closed')</errorConditionFormula>
    <errorMessage>Close date is required</errorMessage>
</ValidationRule>
""")

    result = extract_child_object(vr)
    ref_edges = [e for e in result["edges"] if e.get("relation") == "references"]
    assert len(ref_edges) >= 1
    targets = {e["target"] for e in ref_edges}
    assert any("closedate__c" in t.lower() for t in targets)
    for e in ref_edges:
        assert e["confidence"] == "INFERRED"


def test_extract_validation_rule_cross_object_formula_reference(tmp_path):
    """ValidationRule cross-object formula (e.g. Account__r.Name__c) also creates INFERRED edge."""
    from graphify_sf.extract.object import extract_child_object

    vr_dir = tmp_path / "objects" / "Contact" / "validationRules"
    vr_dir.mkdir(parents=True)
    vr = vr_dir / "CheckAccountField.validationRule-meta.xml"
    vr.write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<ValidationRule {_NS}>
    <fullName>CheckAccountField</fullName>
    <active>true</active>
    <errorConditionFormula>ISBLANK(Account__r.Rating__c)</errorConditionFormula>
    <errorMessage>Account rating required</errorMessage>
</ValidationRule>
""")

    result = extract_child_object(vr)
    ref_edges = [e for e in result["edges"] if e.get("relation") == "references"]
    assert len(ref_edges) >= 1
    targets = {e["target"] for e in ref_edges}
    assert any("rating__c" in t.lower() for t in targets)


def test_extract_validation_rule_no_formula_no_field_edges(tmp_path):
    """ValidationRule without formula produces no field reference edges."""
    from graphify_sf.extract.object import extract_child_object

    vr_dir = tmp_path / "objects" / "Lead" / "validationRules"
    vr_dir.mkdir(parents=True)
    vr = vr_dir / "SimpleRule.validationRule-meta.xml"
    vr.write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<ValidationRule {_NS}>
    <fullName>SimpleRule</fullName>
    <active>true</active>
</ValidationRule>
""")

    result = extract_child_object(vr)
    ref_edges = [e for e in result["edges"] if e.get("relation") == "references"]
    assert len(ref_edges) == 0


# ---------------------------------------------------------------------------
# Other child metadata types (RecordType, ListView, etc.)
# ---------------------------------------------------------------------------


def test_extract_child_object_record_type(tmp_path):
    """RecordType metadata produces a RecordType node."""
    from graphify_sf.extract.object import extract_child_object

    rt_dir = tmp_path / "objects" / "Account" / "recordTypes"
    rt_dir.mkdir(parents=True)
    rt = rt_dir / "Enterprise.recordType-meta.xml"
    rt.write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<RecordType {_NS}>
    <fullName>Enterprise</fullName>
    <active>true</active>
    <label>Enterprise</label>
</RecordType>
""")

    result = extract_child_object(rt)
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["sf_type"] == "RecordType"
    contains_edges = [e for e in result["edges"] if e.get("relation") == "contains"]
    assert len(contains_edges) == 1


def test_extract_child_object_list_view(tmp_path):
    """ListView metadata produces a ListView node."""
    from graphify_sf.extract.object import extract_child_object

    lv_dir = tmp_path / "objects" / "Lead" / "listViews"
    lv_dir.mkdir(parents=True)
    lv = lv_dir / "AllLeads.listView-meta.xml"
    lv.write_text(f"""\
<?xml version="1.0" encoding="UTF-8"?>
<ListView {_NS}>
    <fullName>AllLeads</fullName>
    <label>All Leads</label>
</ListView>
""")

    result = extract_child_object(lv)
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["sf_type"] == "ListView"
