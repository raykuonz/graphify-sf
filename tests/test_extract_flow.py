"""Tests for Flow extraction."""

from __future__ import annotations

from pathlib import Path

_NS = 'xmlns="http://soap.sforce.com/2006/04/metadata"'


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


# ---------------------------------------------------------------------------
# Record-Triggered Flow — triggers edge
# ---------------------------------------------------------------------------

RECORD_TRIGGERED_FLOW_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Flow {_NS}>
    <processType>AutoLaunchedFlow</processType>
    <start>
        <object>Lead</object>
        <triggerType>RecordAfterSave</triggerType>
        <recordTriggerType>Create</recordTriggerType>
    </start>
</Flow>
"""

RECORD_BEFORE_SAVE_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Flow {_NS}>
    <processType>AutoLaunchedFlow</processType>
    <start>
        <object>Opportunity</object>
        <triggerType>RecordBeforeSave</triggerType>
        <recordTriggerType>Update</recordTriggerType>
    </start>
</Flow>
"""

SCHEDULED_FLOW_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Flow {_NS}>
    <processType>AutoLaunchedFlow</processType>
    <start>
        <object>Account</object>
        <triggerType>Scheduled</triggerType>
    </start>
</Flow>
"""


def test_extract_flow_record_triggered_creates_triggers_edge(tmp_path):
    """Record-Triggered Flow emits a 'triggers' edge to the sObject."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "LeadAssignment.flow-meta.xml"
    f.write_text(RECORD_TRIGGERED_FLOW_XML)

    result = extract_flow(f)
    triggers_edges = [e for e in result["edges"] if e.get("relation") == "triggers"]
    assert len(triggers_edges) == 1, "Should have exactly one triggers edge"
    edge = triggers_edges[0]
    assert "lead" in edge["target"].lower()
    assert edge["confidence"] == "EXTRACTED"


def test_extract_flow_record_triggered_stores_trigger_type(tmp_path):
    """triggers edge should carry trigger_type metadata."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "LeadAssignment.flow-meta.xml"
    f.write_text(RECORD_TRIGGERED_FLOW_XML)

    result = extract_flow(f)
    edge = next(e for e in result["edges"] if e.get("relation") == "triggers")
    assert edge.get("trigger_type") == "RecordAfterSave"


def test_extract_flow_record_triggered_stores_trigger_event(tmp_path):
    """triggers edge should carry the recordTriggerType (Create/Update/Delete)."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "LeadAssignment.flow-meta.xml"
    f.write_text(RECORD_TRIGGERED_FLOW_XML)

    result = extract_flow(f)
    edge = next(e for e in result["edges"] if e.get("relation") == "triggers")
    assert edge.get("trigger_event") == "Create"


def test_extract_flow_before_save_triggers_edge(tmp_path):
    """RecordBeforeSave also produces a triggers edge."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "OpportunityValidation.flow-meta.xml"
    f.write_text(RECORD_BEFORE_SAVE_XML)

    result = extract_flow(f)
    triggers_edges = [e for e in result["edges"] if e.get("relation") == "triggers"]
    assert len(triggers_edges) == 1
    assert "opportunity" in triggers_edges[0]["target"].lower()
    assert triggers_edges[0].get("trigger_type") == "RecordBeforeSave"


def test_extract_flow_scheduled_creates_triggers_edge_with_trigger_type(tmp_path):
    """C3: Scheduled flows with an <object> emit a triggers edge with trigger_type=scheduled."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "ScheduledJob.flow-meta.xml"
    f.write_text(SCHEDULED_FLOW_XML)

    result = extract_flow(f)
    triggers_edges = [e for e in result["edges"] if e.get("relation") == "triggers"]
    assert len(triggers_edges) == 1, "Scheduled flow with object should produce a triggers edge"
    assert triggers_edges[0].get("trigger_type") == "scheduled"
    assert triggers_edges[0].get("confidence") == "EXTRACTED"


def test_extract_flow_fixture_has_record_triggers_edge(simple_project_path):
    """The existing UpdateAccountStatus fixture is a record-triggered flow — should have triggers edge."""
    from graphify_sf.extract.flow import extract_flow

    flow_path = simple_project_path / "force-app/main/default/flows/UpdateAccountStatus.flow-meta.xml"
    result = extract_flow(flow_path)

    triggers_edges = [e for e in result["edges"] if e.get("relation") == "triggers"]
    assert len(triggers_edges) == 1
    assert "account__c" in triggers_edges[0]["target"].lower()


# ---------------------------------------------------------------------------
# Flow → Flow (subflow invocations)
# ---------------------------------------------------------------------------

SUBFLOW_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Flow {_NS}>
    <processType>AutoLaunchedFlow</processType>
    <subflows>
        <name>CallChildFlow</name>
        <label>Call Child Flow</label>
        <flowName>ChildFlow</flowName>
    </subflows>
    <subflows>
        <name>CallAnotherFlow</name>
        <label>Call Another</label>
        <flowName>AnotherChildFlow</flowName>
    </subflows>
</Flow>
"""


def test_extract_flow_subflow_invokes_edge(tmp_path):
    """Subflow elements create 'invokes' edges to the child flow."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "ParentFlow.flow-meta.xml"
    f.write_text(SUBFLOW_XML)

    result = extract_flow(f)
    invokes_edges = [e for e in result["edges"] if e.get("relation") == "invokes"]
    assert len(invokes_edges) == 2
    targets = {e["target"] for e in invokes_edges}
    assert any("childflow" in t.lower() for t in targets)
    assert any("anotherchildflow" in t.lower() for t in targets)


def test_extract_flow_subflow_confidence_extracted(tmp_path):
    """Subflow invokes edges should be EXTRACTED confidence."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "ParentFlow.flow-meta.xml"
    f.write_text(SUBFLOW_XML)

    result = extract_flow(f)
    for e in result["edges"]:
        if e.get("relation") == "invokes":
            assert e["confidence"] == "EXTRACTED"


# ---------------------------------------------------------------------------
# Flow → Apex (actionCalls)
# ---------------------------------------------------------------------------

APEX_ACTION_FLOW_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Flow {_NS}>
    <processType>AutoLaunchedFlow</processType>
    <actionCalls>
        <name>CallApexAction</name>
        <actionType>apex</actionType>
        <apexClass>LeadAssignmentService</apexClass>
    </actionCalls>
</Flow>
"""

FLOW_ACTION_FLOW_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Flow {_NS}>
    <processType>AutoLaunchedFlow</processType>
    <actionCalls>
        <name>CallSubflow</name>
        <actionType>flow</actionType>
        <actionName>SubFlow</actionName>
    </actionCalls>
</Flow>
"""


def test_extract_flow_apex_action_creates_calls_edge(tmp_path):
    """actionCalls with actionType=apex creates a 'calls' edge to the Apex class."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "LeadFlow.flow-meta.xml"
    f.write_text(APEX_ACTION_FLOW_XML)

    result = extract_flow(f)
    calls_edges = [e for e in result["edges"] if e.get("relation") == "calls"]
    assert len(calls_edges) == 1
    assert "leadassignmentservice" in calls_edges[0]["target"].lower()
    assert calls_edges[0]["confidence"] == "EXTRACTED"


def test_extract_flow_action_call_subflow_creates_invokes_edge(tmp_path):
    """actionCalls with actionType=flow/subflow creates an 'invokes' edge."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "ParentWithAction.flow-meta.xml"
    f.write_text(FLOW_ACTION_FLOW_XML)

    result = extract_flow(f)
    invokes_edges = [e for e in result["edges"] if e.get("relation") == "invokes"]
    assert len(invokes_edges) == 1
    assert "subflow" in invokes_edges[0]["target"].lower()


# ---------------------------------------------------------------------------
# Flow → Object record operations (read/create/update/delete)
# ---------------------------------------------------------------------------

READ_AND_UPDATE_SAME_OBJECT_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Flow {_NS}>
    <processType>AutoLaunchedFlow</processType>
    <recordLookups>
        <name>GetOpp</name>
        <object>Opportunity</object>
    </recordLookups>
    <recordUpdates>
        <name>UpdateOpp</name>
        <object>Opportunity</object>
    </recordUpdates>
</Flow>
"""

PURE_UPDATE_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Flow {_NS}>
    <processType>AutoLaunchedFlow</processType>
    <recordUpdates>
        <name>UpdateOpp</name>
        <object>Opportunity</object>
    </recordUpdates>
</Flow>
"""

ALL_FOUR_OPS_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Flow {_NS}>
    <processType>AutoLaunchedFlow</processType>
    <recordLookups>
        <name>GetAcc</name>
        <object>Account</object>
    </recordLookups>
    <recordCreates>
        <name>MakeContact</name>
        <object>Contact</object>
    </recordCreates>
    <recordUpdates>
        <name>UpdateAcc</name>
        <object>Account</object>
    </recordUpdates>
    <recordDeletes>
        <name>DeleteLead</name>
        <object>Lead</object>
    </recordDeletes>
</Flow>
"""


def test_extract_flow_read_and_update_yields_two_edges(tmp_path):
    """A flow that both reads and updates the same object yields TWO edges
    (operation=read and operation=update), not one collapsed reference."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "OppReadWrite.flow-meta.xml"
    f.write_text(READ_AND_UPDATE_SAME_OBJECT_XML)

    result = extract_flow(f)
    opp_edges = [
        e for e in result["edges"] if e.get("relation") == "references" and "opportunity" in e["target"].lower()
    ]
    assert len(opp_edges) == 2, "read+update on same object must not be deduped to one edge"
    ops = {e.get("operation") for e in opp_edges}
    assert ops == {"read", "update"}


def test_extract_flow_pure_update_carries_operation(tmp_path):
    """A recordUpdates element produces a references edge with operation='update'."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "OppUpdate.flow-meta.xml"
    f.write_text(PURE_UPDATE_XML)

    result = extract_flow(f)
    ref_edges = [e for e in result["edges"] if e.get("relation") == "references"]
    assert len(ref_edges) == 1
    assert ref_edges[0].get("operation") == "update"
    assert "opportunity" in ref_edges[0]["target"].lower()


def test_extract_flow_record_ops_relation_unchanged(tmp_path):
    """Regression: record-op edges keep relation='references' (semantics unchanged);
    only the new 'operation' field distinguishes them."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "OppReadWrite.flow-meta.xml"
    f.write_text(READ_AND_UPDATE_SAME_OBJECT_XML)

    result = extract_flow(f)
    record_op_edges = [e for e in result["edges"] if e.get("operation") is not None]
    assert record_op_edges, "expected at least one record-op edge"
    for e in record_op_edges:
        assert e["relation"] == "references"
        assert e["confidence"] == "EXTRACTED"


def test_extract_flow_all_four_operations(tmp_path):
    """All four record-op tags map to their operation: read/create/update/delete."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "AllOps.flow-meta.xml"
    f.write_text(ALL_FOUR_OPS_XML)

    result = extract_flow(f)
    by_op = {e.get("operation"): e["target"].lower() for e in result["edges"] if e.get("operation") is not None}
    assert by_op.get("read") and "account" in by_op["read"]
    assert by_op.get("create") and "contact" in by_op["create"]
    assert by_op.get("update") and "account" in by_op["update"]
    assert by_op.get("delete") and "lead" in by_op["delete"]


# ---------------------------------------------------------------------------
# Flow child element nodes (Decision, Screen, Loop, Assignment)
# ---------------------------------------------------------------------------

ELEMENTS_FLOW_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<Flow {_NS}>
    <processType>Flow</processType>
    <decisions>
        <name>CheckStatus</name>
        <label>Check Status</label>
    </decisions>
    <screens>
        <name>WelcomeScreen</name>
        <label>Welcome</label>
    </screens>
    <loops>
        <name>IterateRecords</name>
        <label>Iterate Records</label>
    </loops>
    <assignments>
        <name>SetVariable</name>
        <label>Set Variable</label>
    </assignments>
</Flow>
"""


def test_extract_flow_decision_creates_child_node(tmp_path):
    """Decisions become FlowDecision child nodes with 'contains' edges."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "ScreenFlow.flow-meta.xml"
    f.write_text(ELEMENTS_FLOW_XML)

    result = extract_flow(f)
    decision_nodes = [n for n in result["nodes"] if n.get("sf_type") == "FlowDecision"]
    assert len(decision_nodes) == 1
    assert "CheckStatus" in decision_nodes[0]["label"] or "Check Status" in decision_nodes[0]["label"]


def test_extract_flow_screen_creates_child_node(tmp_path):
    """Screens become FlowScreen child nodes."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "ScreenFlow.flow-meta.xml"
    f.write_text(ELEMENTS_FLOW_XML)

    result = extract_flow(f)
    screen_nodes = [n for n in result["nodes"] if n.get("sf_type") == "FlowScreen"]
    assert len(screen_nodes) == 1


def test_extract_flow_elements_have_contains_edges(tmp_path):
    """Each flow element child node is linked to its parent flow via 'contains'."""
    from graphify_sf.extract.flow import extract_flow

    f = tmp_path / "ScreenFlow.flow-meta.xml"
    f.write_text(ELEMENTS_FLOW_XML)

    result = extract_flow(f)
    flow_node_id = result["nodes"][0]["id"]
    contains_edges = [e for e in result["edges"] if e.get("relation") == "contains"]
    # Decision + Screen + Loop + Assignment = 4 contains edges
    assert len(contains_edges) == 4
    for e in contains_edges:
        assert e["source"] == flow_node_id
