"""Flow XML extractor."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ._ids import apex_class_id, flow_id, make_sf_id, object_id

_SF_NS = "http://soap.sforce.com/2006/04/metadata"


def _strip_ns(tag: str) -> str:
    """Strip XML namespace from a tag string."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _find_text(el: ET.Element, tag: str, ns: str = "") -> str | None:
    """Find a child element and return its text, trying with/without namespace."""
    if ns:
        child = el.find(f"{{{ns}}}{tag}")
        if child is None:
            child = el.find(tag)
    else:
        child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _find_all(root: ET.Element, tag: str, ns: str = "") -> list[ET.Element]:
    """Find all descendants with given tag, trying with/without namespace."""
    if ns:
        result = root.findall(f".//{{{ns}}}{tag}")
        if not result:
            result = root.findall(f".//{tag}")
    else:
        result = root.findall(f".//{tag}")
    return result


def _make_edge(src: str, tgt: str, relation: str, confidence: str, source_file: str) -> dict:
    return {
        "source": src,
        "target": tgt,
        "relation": relation,
        "confidence": confidence,
        "source_file": source_file,
        "source_location": None,
        "weight": 1.0,
        "_src": src,
        "_tgt": tgt,
    }


def extract_flow(path: Path) -> dict:
    """Extract nodes and edges from a Flow XML file."""
    str_path = str(path)
    nodes: list[dict] = []
    edges: list[dict] = []

    # Derive flow name from stem: "Create_Account.flow-meta" → "Create_Account"
    stem = path.stem
    if stem.endswith(".flow-meta"):
        stem = stem[: -len(".flow-meta")]
    flow_name = stem
    flow_nid = flow_id(flow_name)

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
    except (ET.ParseError, FileNotFoundError, OSError):
        return {"nodes": [], "edges": []}

    # Detect namespace
    ns = ""
    if root_el.tag.startswith("{"):
        ns = root_el.tag.split("}")[0][1:]

    process_type = _find_text(root_el, "processType", ns) or "Flow"
    trigger_type = _find_text(root_el, "triggerType", ns)

    nodes.append(
        {
            "id": flow_nid,
            "label": flow_name,
            "sf_type": "Flow",
            "file_type": "flow",
            "source_file": str_path,
            "source_location": None,
            "process_type": process_type,
            **({"trigger_type": trigger_type} if trigger_type else {}),
        }
    )

    # Record-Triggered Flow: <start> element
    start_el = root_el.find(f"{{{ns}}}start") if ns else root_el.find("start")
    if start_el is not None:
        trigger_obj = _find_text(start_el, "object", ns)
        record_trigger_type = _find_text(start_el, "recordTriggerType", ns)
        start_trigger_type = _find_text(start_el, "triggerType", ns)
        if trigger_obj and start_trigger_type in (
            "RecordAfterSave",
            "RecordBeforeSave",
            "RecordBeforeDelete",
        ):
            trigger_edge = _make_edge(flow_nid, object_id(trigger_obj), "triggers", "EXTRACTED", str_path)
            trigger_edge["trigger_type"] = start_trigger_type
            if record_trigger_type:
                trigger_edge["trigger_event"] = record_trigger_type
            edges.append(trigger_edge)

    # Action calls (Apex, email alerts, etc.)
    for action in _find_all(root_el, "actionCalls", ns):
        action_type = _find_text(action, "actionType", ns)
        if action_type == "apex":
            apex_name = _find_text(action, "apexClass", ns) or _find_text(action, "actionName", ns)
            if apex_name:
                edges.append(_make_edge(flow_nid, apex_class_id(apex_name), "calls", "EXTRACTED", str_path))
        elif action_type in ("flow", "subflow"):
            sub_name = _find_text(action, "actionName", ns)
            if sub_name:
                edges.append(_make_edge(flow_nid, flow_id(sub_name), "invokes", "EXTRACTED", str_path))

    # Object record operations. The relation stays "references" (a generic relation
    # reused by many extractors — never change its semantics), but each edge carries an
    # "operation" field (read/create/update/delete) so downstream can distinguish
    # read-only access from writes. Dedup is by (object, operation) so a flow that both
    # reads and updates the same object yields two edges, not one collapsed reference.
    _record_op_tags = {
        "recordLookups": "read",
        "recordCreates": "create",
        "recordUpdates": "update",
        "recordDeletes": "delete",
    }
    seen_record_ops: set[tuple[str, str]] = set()
    for tag, operation in _record_op_tags.items():
        for el in _find_all(root_el, tag, ns):
            obj = _find_text(el, "object", ns)
            if obj and (obj, operation) not in seen_record_ops:
                seen_record_ops.add((obj, operation))
                edge = _make_edge(flow_nid, object_id(obj), "references", "EXTRACTED", str_path)
                edge["operation"] = operation
                edges.append(edge)

    # Subflows
    for subflow in _find_all(root_el, "subflows", ns):
        child_name = _find_text(subflow, "flowName", ns)
        if child_name:
            edges.append(_make_edge(flow_nid, flow_id(child_name), "invokes", "EXTRACTED", str_path))

    # Flow elements as child nodes (decisions, screens, loops, etc.)
    element_tags = {
        "decisions": "FlowDecision",
        "loops": "FlowLoop",
        "screens": "FlowScreen",
        "assignments": "FlowAssignment",
        "collectionProcessors": "FlowCollectionProcessor",
    }
    for tag, sf_type in element_tags.items():
        for el in _find_all(root_el, tag, ns):
            elem_name = _find_text(el, "name", ns)
            elem_label = _find_text(el, "label", ns) or elem_name
            if elem_name:
                elem_nid = make_sf_id("flowelement", flow_name, elem_name)
                nodes.append(
                    {
                        "id": elem_nid,
                        "label": elem_label,
                        "sf_type": sf_type,
                        "file_type": "flow",
                        "source_file": str_path,
                        "source_location": None,
                    }
                )
                edges.append(_make_edge(flow_nid, elem_nid, "contains", "EXTRACTED", str_path))

    return {"nodes": nodes, "edges": edges}
