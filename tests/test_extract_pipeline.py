"""Tests for the extract pipeline — _resolve_cross_references and stub node ordering.

These tests verify the two-pass extraction coordinator in extract/__init__.py,
focusing on the critical ordering of _ensure_stub_nodes before
_resolve_cross_references so that edges to standard objects (Lead, Account, etc.)
are not incorrectly downgraded from EXTRACTED to INFERRED.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# _resolve_cross_references — confidence downgrade
# ---------------------------------------------------------------------------


def test_resolve_cross_references_downgrades_extracted_to_inferred_for_unknown_target():
    """EXTRACTED edges pointing to unknown node IDs are downgraded to INFERRED."""
    from graphify_sf.extract import _resolve_cross_references

    nodes = [{"id": "flow_myflow", "label": "MyFlow", "sf_type": "Flow"}]
    edges = [
        {
            "source": "flow_myflow",
            "target": "object_lead",  # No node exists for this ID
            "relation": "triggers",
            "confidence": "EXTRACTED",
        }
    ]

    _, resolved = _resolve_cross_references(nodes, edges)
    assert resolved[0]["confidence"] == "INFERRED"
    assert resolved[0].get("confidence_score") == 0.7


def test_resolve_cross_references_preserves_extracted_for_known_target():
    """EXTRACTED edges to known node IDs keep EXTRACTED confidence."""
    from graphify_sf.extract import _resolve_cross_references

    nodes = [
        {"id": "flow_myflow", "label": "MyFlow", "sf_type": "Flow"},
        {"id": "object_account", "label": "Account", "sf_type": "CustomObject"},
    ]
    edges = [
        {
            "source": "flow_myflow",
            "target": "object_account",
            "relation": "triggers",
            "confidence": "EXTRACTED",
        }
    ]

    _, resolved = _resolve_cross_references(nodes, edges)
    assert resolved[0]["confidence"] == "EXTRACTED"


def test_resolve_cross_references_keeps_inferred_unchanged():
    """Edges already marked INFERRED are not changed."""
    from graphify_sf.extract import _resolve_cross_references

    nodes = [{"id": "apex_handler", "label": "Handler", "sf_type": "ApexClass"}]
    edges = [
        {
            "source": "apex_handler",
            "target": "object_unknown",
            "relation": "dml",
            "confidence": "INFERRED",
            "confidence_score": 0.7,
        }
    ]

    _, resolved = _resolve_cross_references(nodes, edges)
    assert resolved[0]["confidence"] == "INFERRED"


def test_resolve_cross_references_resolves_raw_calls_to_known_class():
    """_raw_calls on an Apex node produce INFERRED calls edges to known classes."""
    from graphify_sf.extract import _resolve_cross_references

    nodes = [
        {
            "id": "apex_handler",
            "label": "Handler",
            "sf_type": "ApexClass",
            "source_file": "/some/path.cls",
            "_raw_calls": [{"caller_id": "apex_handler", "callee_class": "AccountService", "callee_method": "run"}],
        },
        {"id": "apex_accountservice", "label": "AccountService", "sf_type": "ApexClass"},
    ]
    edges = []

    nodes_out, edges_out = _resolve_cross_references(nodes, edges)
    call_edges = [e for e in edges_out if e.get("relation") == "calls"]
    assert len(call_edges) == 1
    assert "accountservice" in call_edges[0]["target"].lower()
    # _raw_calls should be consumed (removed from node)
    handler = next(n for n in nodes_out if n["id"] == "apex_handler")
    assert "_raw_calls" not in handler


def test_resolve_cross_references_resolves_raw_calls_to_unknown_class_as_inferred():
    """_raw_calls to an unknown class produce INFERRED calls edges with low confidence_score."""
    from graphify_sf.extract import _resolve_cross_references

    nodes = [
        {
            "id": "apex_handler",
            "label": "Handler",
            "sf_type": "ApexClass",
            "source_file": "/some/path.cls",
            "_raw_calls": [{"caller_id": "apex_handler", "callee_class": "MysteryClass", "callee_method": "run"}],
        }
    ]
    edges = []

    _, edges_out = _resolve_cross_references(nodes, edges)
    call_edges = [e for e in edges_out if e.get("relation") == "calls"]
    assert len(call_edges) == 1
    assert call_edges[0]["confidence"] == "INFERRED"
    assert call_edges[0]["confidence_score"] <= 0.5


# ---------------------------------------------------------------------------
# Stub node ordering: stubs created BEFORE confidence downgrade
# ---------------------------------------------------------------------------


def test_stub_nodes_created_before_confidence_downgrade_in_extract_pipeline(tmp_path):
    """End-to-end: a Flow triggers a standard object (Lead, no .object-meta.xml).
    The triggers edge should be EXTRACTED, not INFERRED, because _ensure_stub_nodes
    runs before _resolve_cross_references.
    """
    from graphify_sf.detect import detect
    from graphify_sf.extract import extract

    # Create a minimal SFDX project with a record-triggered flow for Lead
    flows_dir = tmp_path / "force-app" / "main" / "default" / "flows"
    flows_dir.mkdir(parents=True)
    flow_file = flows_dir / "LeadAssignment.flow-meta.xml"
    flow_file.write_text("""\
<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
    <processType>AutoLaunchedFlow</processType>
    <start>
        <object>Lead</object>
        <triggerType>RecordAfterSave</triggerType>
        <recordTriggerType>Create</recordTriggerType>
    </start>
</Flow>
""")

    result = detect(tmp_path)
    extraction = extract(result, parallel=False)

    triggers_edges = [
        e for e in extraction["edges"] if e.get("relation") == "triggers" and "lead" in e.get("target", "").lower()
    ]
    assert len(triggers_edges) == 1, f"Expected 1 triggers edge for Lead, got {len(triggers_edges)}"
    assert triggers_edges[0]["confidence"] == "EXTRACTED", (
        f"Expected EXTRACTED confidence, got {triggers_edges[0]['confidence']} — "
        "stub node for Lead was probably not created before _resolve_cross_references ran"
    )


def test_stub_node_exists_for_standard_object_after_extract(tmp_path):
    """After extraction, a stub node for Lead should exist in the nodes list."""
    from graphify_sf.detect import detect
    from graphify_sf.extract import extract

    flows_dir = tmp_path / "force-app" / "main" / "default" / "flows"
    flows_dir.mkdir(parents=True)
    (flows_dir / "LeadFlow.flow-meta.xml").write_text("""\
<?xml version="1.0" encoding="UTF-8"?>
<Flow xmlns="http://soap.sforce.com/2006/04/metadata">
    <processType>AutoLaunchedFlow</processType>
    <start>
        <object>Lead</object>
        <triggerType>RecordAfterSave</triggerType>
    </start>
</Flow>
""")

    result = detect(tmp_path)
    extraction = extract(result, parallel=False)

    node_ids = {n["id"] for n in extraction["nodes"]}
    assert "object_lead" in node_ids, "Stub node for Lead should be present in extraction output"

    lead_node = next(n for n in extraction["nodes"] if n["id"] == "object_lead")
    assert lead_node.get("stub") is True
