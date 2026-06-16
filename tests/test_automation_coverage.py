"""Integration tests for Epic C — Automation completeness (graphify-sf v0.4.0).

Runs detect+extract on fixtures and asserts on nodes/edges (same data that
lands in graph.json links/nodes). Tests follow the empirical style of
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
# C1 — Workflow Field Updates + Tasks
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def c1_result():
    return _extract("epicC_workflow/force-app/main/default")


def test_c1_workflow_node_exists(c1_result):
    nodes = _nodes_by_id(c1_result)
    assert "workflow_account" in nodes, "expected Workflow node for Account"


def test_c1_field_update_node_exists(c1_result):
    nodes = _nodes_by_id(c1_result)
    assert "workflowfieldupdate_account_updatestatus" in nodes, "expected WorkflowFieldUpdate node"


def test_c1_field_update_sf_type(c1_result):
    nodes = _nodes_by_id(c1_result)
    assert nodes["workflowfieldupdate_account_updatestatus"]["sf_type"] == "WorkflowFieldUpdate"


def test_c1_workflow_contains_field_update_extracted(c1_result):
    edges = _edges(c1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "workflow_account"
            and e.get("target") == "workflowfieldupdate_account_updatestatus"
            and e.get("relation") == "contains"
        ),
        None,
    )
    assert edge is not None, "expected contains edge from workflow to WorkflowFieldUpdate"
    assert edge["confidence"] == "EXTRACTED"


def test_c1_field_update_references_field(c1_result):
    """WorkflowFieldUpdate emits a references edge to the updated field."""
    edges = _edges(c1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "workflowfieldupdate_account_updatestatus"
            and e.get("target") == "field_account_status__c"
            and e.get("relation") == "references"
        ),
        None,
    )
    assert edge is not None, "expected references edge from WorkflowFieldUpdate to Status__c field"


def test_c1_task_node_exists(c1_result):
    nodes = _nodes_by_id(c1_result)
    assert "workflowtask_account_sendfollowup" in nodes, "expected WorkflowTask node"


def test_c1_task_sf_type(c1_result):
    nodes = _nodes_by_id(c1_result)
    assert nodes["workflowtask_account_sendfollowup"]["sf_type"] == "WorkflowTask"


def test_c1_workflow_contains_task_extracted(c1_result):
    edges = _edges(c1_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "workflow_account"
            and e.get("target") == "workflowtask_account_sendfollowup"
            and e.get("relation") == "contains"
        ),
        None,
    )
    assert edge is not None, "expected contains edge from workflow to WorkflowTask"
    assert edge["confidence"] == "EXTRACTED"


def test_c1_negative_no_spurious_task_nodes(c1_result):
    """Only one WorkflowTask node should exist (one task in the fixture)."""
    nodes = _nodes_by_id(c1_result)
    task_nodes = [n for n in nodes.values() if n.get("sf_type") == "WorkflowTask"]
    assert len(task_nodes) == 1, f"expected exactly 1 WorkflowTask, got {len(task_nodes)}"


# ---------------------------------------------------------------------------
# C2 — Process Builder distinguished from Flow
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def c2_result():
    return _extract("epicC_flow_processbuilder/force-app/main/default")


def test_c2_process_builder_node_exists(c2_result):
    nodes = _nodes_by_id(c2_result)
    assert "flow_myprocessbuilder" in nodes, "expected ProcessBuilder node for MyProcessBuilder"


def test_c2_process_builder_sf_type(c2_result):
    """A flow with processType=Workflow must be typed as ProcessBuilder, not Flow."""
    nodes = _nodes_by_id(c2_result)
    node = nodes["flow_myprocessbuilder"]
    assert node["sf_type"] == "ProcessBuilder", f"expected sf_type=ProcessBuilder, got {node['sf_type']!r}"


def test_c2_normal_flow_sf_type_unchanged(c2_result):
    """A regular AutoLaunchedFlow must NOT be mislabeled as ProcessBuilder (negative control)."""
    nodes = _nodes_by_id(c2_result)
    assert "flow_mynormalflow" in nodes, "expected Flow node for MyNormalFlow"
    node = nodes["flow_mynormalflow"]
    assert node["sf_type"] == "Flow", f"MyNormalFlow must keep sf_type=Flow, got {node['sf_type']!r}"


def test_c2_process_builder_process_type_attr_preserved(c2_result):
    """process_type attribute should still be stored on the node."""
    nodes = _nodes_by_id(c2_result)
    node = nodes["flow_myprocessbuilder"]
    assert node.get("process_type") == "Workflow"


# ---------------------------------------------------------------------------
# C3 — Flow trigger completeness (platform-event & scheduled starts)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def c3_result():
    return _extract("epicC_flow_triggers/force-app/main/default")


def test_c3_platform_event_flow_node_exists(c3_result):
    nodes = _nodes_by_id(c3_result)
    assert "flow_platformeventflow" in nodes, "expected flow node for PlatformEventFlow"


def test_c3_platform_event_triggers_edge_exists(c3_result):
    """PlatformEvent-triggered flow emits a triggers edge to the __e object."""
    edges = _edges(c3_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "flow_platformeventflow"
            and e.get("target") == "object_order_event__e"
            and e.get("relation") == "triggers"
        ),
        None,
    )
    assert edge is not None, "expected triggers edge from PlatformEventFlow to object_order_event__e"


def test_c3_platform_event_trigger_type_attr(c3_result):
    """The triggers edge must carry trigger_type=platform_event."""
    edges = _edges(c3_result)
    edge = next(
        (e for e in edges if e.get("source") == "flow_platformeventflow" and e.get("relation") == "triggers"),
        None,
    )
    assert edge is not None
    assert edge.get("trigger_type") == "platform_event", (
        f"expected trigger_type=platform_event, got {edge.get('trigger_type')!r}"
    )


def test_c3_scheduled_flow_node_exists(c3_result):
    nodes = _nodes_by_id(c3_result)
    assert "flow_scheduledflow" in nodes, "expected flow node for ScheduledFlow"


def test_c3_scheduled_triggers_edge_exists(c3_result):
    """Scheduled flow emits a triggers edge to its target object."""
    edges = _edges(c3_result)
    edge = next(
        (e for e in edges if e.get("source") == "flow_scheduledflow" and e.get("relation") == "triggers"),
        None,
    )
    assert edge is not None, "expected triggers edge from ScheduledFlow"


def test_c3_scheduled_trigger_type_attr(c3_result):
    """The scheduled triggers edge must carry trigger_type=scheduled."""
    edges = _edges(c3_result)
    edge = next(
        (e for e in edges if e.get("source") == "flow_scheduledflow" and e.get("relation") == "triggers"),
        None,
    )
    assert edge is not None
    assert edge.get("trigger_type") == "scheduled", f"expected trigger_type=scheduled, got {edge.get('trigger_type')!r}"


def test_c3_negative_record_trigger_unchanged(c3_result):
    """Record-triggered flows in a different fixture must not be affected.

    Confirm that the platform-event and scheduled flows themselves do NOT carry
    a RecordAfterSave-style triggers edge (wrong relation type for their kind).
    """
    edges = _edges(c3_result)
    bad = [
        e
        for e in edges
        if e.get("source") in ("flow_platformeventflow", "flow_scheduledflow")
        and e.get("relation") == "triggers"
        and e.get("trigger_type") in ("RecordAfterSave", "RecordBeforeSave", "RecordBeforeDelete")
    ]
    assert bad == [], f"record-trigger type must not appear on PE/Scheduled flows: {bad}"


# ---------------------------------------------------------------------------
# C4 — Validation Rule: standard fields (INFERRED)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def c4_result():
    return _extract("epicC_vr_stdfields/force-app/main/default")


def test_c4_validation_rule_node_exists(c4_result):
    nodes = _nodes_by_id(c4_result)
    assert "validationrule_account_amountcheck" in nodes, "expected ValidationRule node"


def test_c4_custom_field_reference_inferred(c4_result):
    """Custom__c in the formula produces an INFERRED references edge (existing behaviour)."""
    edges = _edges(c4_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "validationrule_account_amountcheck"
            and e.get("target") == "field_account_custom__c"
            and e.get("relation") == "references"
        ),
        None,
    )
    assert edge is not None, "expected references edge to field_account_custom__c"
    assert edge["confidence"] == "INFERRED"


def test_c4_standard_field_reference_inferred(c4_result):
    """Amount in the formula produces an INFERRED references edge (new C4 behaviour)."""
    edges = _edges(c4_result)
    edge = next(
        (
            e
            for e in edges
            if e.get("source") == "validationrule_account_amountcheck"
            and e.get("target") == "field_account_amount"
            and e.get("relation") == "references"
        ),
        None,
    )
    assert edge is not None, "expected INFERRED references edge to field_account_amount (standard field detection)"
    assert edge["confidence"] == "INFERRED"


def test_c4_negative_formula_function_not_a_field(c4_result):
    """Formula function names (ISBLANK, OR, etc.) must not produce spurious field edges."""
    edges = _edges(c4_result)
    forbidden_targets = {
        "field_account_isblank",
        "field_account_or",
        "field_account_and",
        "field_account_not",
        "field_account_true",
        "field_account_false",
        "field_account_null",
    }
    bad = [
        e
        for e in edges
        if e.get("source") == "validationrule_account_amountcheck"
        and e.get("relation") == "references"
        and e.get("target") in forbidden_targets
    ]
    assert bad == [], f"formula function names must not become field references: {bad}"


def test_c4_both_references_present(c4_result):
    """Both Amount (standard) and Custom__c (custom) references land in the edge list."""
    edges = _edges(c4_result)
    vr_refs = [
        e
        for e in edges
        if e.get("source") == "validationrule_account_amountcheck" and e.get("relation") == "references"
    ]
    targets = {e["target"] for e in vr_refs}
    assert "field_account_amount" in targets, "standard field Amount missing from references"
    assert "field_account_custom__c" in targets, "custom field Custom__c missing from references"
