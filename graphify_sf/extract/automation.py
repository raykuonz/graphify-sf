"""Workflow, ApprovalProcess, and other automation metadata extractor."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ._ids import apex_class_id, make_sf_id, object_id


def _get_ns(root_el: ET.Element) -> str:
    if root_el.tag.startswith("{"):
        return root_el.tag.split("}", 1)[1]
    return ""


def _find_text(el: ET.Element, tag: str, ns: str = "") -> str | None:
    if ns:
        child = el.find(f"{{{ns}}}{tag}")
        if child is None:
            child = el.find(tag)
    else:
        child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _find_all(root: ET.Element, tag: str, ns: str = "") -> list[ET.Element]:
    if ns:
        result = root.findall(f".//{{{ns}}}{tag}")
        if not result:
            result = root.findall(f".//{tag}")
    else:
        result = root.findall(f".//{tag}")
    return result


def _make_edge(src: str, tgt: str, relation: str, confidence: str,
               source_file: str, weight: float = 1.0) -> dict:
    return {
        "source": src, "target": tgt,
        "relation": relation, "confidence": confidence,
        "source_file": source_file, "source_location": None,
        "weight": weight, "_src": src, "_tgt": tgt,
    }


def extract_workflow(path: Path) -> dict:
    """Extract workflow rules from a .workflow-meta.xml file."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".workflow-meta"):
        stem = stem[: -len(".workflow-meta")]
    obj_name = stem  # Workflow files are named after the object

    workflow_nid = make_sf_id("workflow", stem)
    nodes: list[dict] = [{
        "id": workflow_nid,
        "label": f"{stem} Workflow",
        "sf_type": "Workflow",
        "file_type": "automation",
        "source_file": str_path,
        "source_location": None,
    }]
    edges: list[dict] = [
        _make_edge(workflow_nid, object_id(obj_name), "triggers", "EXTRACTED", str_path),
    ]

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)

        # Workflow rules
        for rule in _find_all(root_el, "rules", ns):
            rule_name = _find_text(rule, "fullName", ns)
            if rule_name:
                rule_nid = make_sf_id("workflowrule", stem, rule_name)
                nodes.append({
                    "id": rule_nid,
                    "label": rule_name,
                    "sf_type": "WorkflowRule",
                    "file_type": "automation",
                    "source_file": str_path,
                    "source_location": None,
                })
                edges.append(_make_edge(workflow_nid, rule_nid, "contains", "EXTRACTED", str_path))

        # Email alerts referencing Apex
        for alert in _find_all(root_el, "alerts", ns):
            alert_name = _find_text(alert, "fullName", ns)
            if alert_name:
                alert_nid = make_sf_id("workflowalert", stem, alert_name)
                nodes.append({
                    "id": alert_nid,
                    "label": alert_name,
                    "sf_type": "WorkflowAlert",
                    "file_type": "automation",
                    "source_file": str_path,
                    "source_location": None,
                })
                edges.append(_make_edge(workflow_nid, alert_nid, "contains", "EXTRACTED", str_path))

    except ET.ParseError:
        pass

    return {"nodes": nodes, "edges": edges}


def extract_approval_process(path: Path) -> dict:
    """Extract an ApprovalProcess node and its connections."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".approvalProcess-meta"):
        stem = stem[: -len(".approvalProcess-meta")]

    process_nid = make_sf_id("approvalprocess", stem)
    nodes: list[dict] = [{
        "id": process_nid,
        "label": stem,
        "sf_type": "ApprovalProcess",
        "file_type": "automation",
        "source_file": str_path,
        "source_location": None,
    }]
    edges: list[dict] = []

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)

        # Object reference
        obj = _find_text(root_el, "object", ns)
        if obj:
            edges.append(_make_edge(process_nid, object_id(obj), "references", "EXTRACTED", str_path))

        # Apex initial submission actions
        for action in _find_all(root_el, "initialSubmissionActions", ns):
            action_type = _find_text(action, "type", ns)
            if action_type == "ApexApproval":
                cls = _find_text(action, "apexClass", ns)
                if cls:
                    edges.append(_make_edge(process_nid, apex_class_id(cls), "calls", "EXTRACTED", str_path))

    except ET.ParseError:
        pass

    return {"nodes": nodes, "edges": edges}


def extract_generic_automation(path: Path) -> dict:
    """Generic extractor for other automation metadata (escalation rules, etc.)."""
    str_path = str(path)
    stem = path.stem

    sf_type_map = {
        ".escalationRules-meta.xml": ("escalationrules", "EscalationRules"),
        ".assignmentRules-meta.xml": ("assignmentrules", "AssignmentRules"),
        ".autoResponseRules-meta.xml": ("autoresponserules", "AutoResponseRules"),
    }

    prefix, sf_type = "automation", "Automation"
    for suffix, (p, t) in sf_type_map.items():
        if path.name.endswith(suffix.lstrip(".")):
            prefix, sf_type = p, t
            stem_suffix = suffix.lstrip(".")
            if stem.endswith(stem_suffix.rstrip(".xml").replace(".xml", "")):
                stem = stem[: -(len(stem_suffix.rstrip(".xml")) + 1)]
            break

    nid = make_sf_id(prefix, stem)
    nodes: list[dict] = [{
        "id": nid,
        "label": stem,
        "sf_type": sf_type,
        "file_type": "automation",
        "source_file": str_path,
        "source_location": None,
    }]
    edges: list[dict] = []

    # Try to find the object reference
    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)
        obj = _find_text(root_el, "sObjectType", ns) or _find_text(root_el, "object", ns)
        if obj:
            edges.append(_make_edge(nid, object_id(obj), "references", "EXTRACTED", str_path))
    except ET.ParseError:
        pass

    return {"nodes": nodes, "edges": edges}
