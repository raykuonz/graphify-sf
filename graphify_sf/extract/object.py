"""CustomObject, CustomField, and child metadata extractor."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ._ids import field_id, make_sf_id, object_id


def _find_text(el: ET.Element, tag: str, ns: str = "") -> str | None:
    if ns:
        child = el.find(f"{{{ns}}}{tag}")
        if child is None:
            child = el.find(tag)
    else:
        child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _get_ns(root_el: ET.Element) -> str:
    if root_el.tag.startswith("{"):
        return root_el.tag.split("}")[0][1:]
    return ""


def _make_edge(src: str, tgt: str, relation: str, confidence: str,
               source_file: str, weight: float = 1.0) -> dict:
    return {
        "source": src, "target": tgt,
        "relation": relation, "confidence": confidence,
        "source_file": source_file, "source_location": None,
        "weight": weight, "_src": src, "_tgt": tgt,
    }


def _object_name_from_stem(path: Path) -> str:
    """Extract the object API name from a .object-meta.xml file stem."""
    stem = path.stem
    if stem.endswith(".object-meta"):
        return stem[:-len(".object-meta")]
    return stem


def _parent_object_name(path: Path) -> str:
    """Infer the parent object name from a field/child metadata file path.

    Convention: objects/<ObjectName>/fields/<FieldName>.field-meta.xml
                objects/<ObjectName>/validationRules/<RuleName>.validationRule-meta.xml
    """
    # parent is the type dir (fields, validationRules, etc.)
    # grandparent is the object dir
    return path.parent.parent.name


def extract_custom_object(path: Path) -> dict:
    """Extract a CustomObject node from .object-meta.xml."""
    if not path.exists():
        return {"nodes": [], "edges": []}
    str_path = str(path)
    obj_name = _object_name_from_stem(path)
    obj_nid = object_id(obj_name)

    nodes: list[dict] = [{
        "id": obj_nid,
        "label": obj_name,
        "sf_type": "CustomObject",
        "file_type": "object",
        "source_file": str_path,
        "source_location": None,
    }]

    # Try to enrich with label/description from XML
    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)
        label = _find_text(root_el, "label", ns)
        if label:
            nodes[0]["display_label"] = label
        desc = _find_text(root_el, "description", ns)
        if desc:
            nodes[0]["description"] = desc[:200]
    except (ET.ParseError, OSError):
        pass

    return {"nodes": nodes, "edges": []}


def extract_custom_field(path: Path) -> dict:
    """Extract a CustomField node and its relationship to the parent object."""
    str_path = str(path)
    obj_name = _parent_object_name(path)

    # Field name from stem
    stem = path.stem
    for suffix in (".field-meta", ".field"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    field_name = stem

    field_nid = field_id(obj_name, field_name)
    obj_nid = object_id(obj_name)

    nodes: list[dict] = [{
        "id": field_nid,
        "label": f"{obj_name}.{field_name}",
        "sf_type": "CustomField",
        "file_type": "object",
        "source_file": str_path,
        "source_location": None,
    }]
    edges: list[dict] = [
        _make_edge(obj_nid, field_nid, "contains", "EXTRACTED", str_path),
    ]

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)
        field_type = _find_text(root_el, "type", ns)
        if field_type:
            nodes[0]["field_type"] = field_type
        label = _find_text(root_el, "label", ns)
        if label:
            nodes[0]["display_label"] = label

        # Lookup / MasterDetail → references the target object
        if field_type in ("Lookup", "MasterDetail", "Hierarchy"):
            ref_to = _find_text(root_el, "referenceTo", ns)
            if ref_to:
                edges.append(_make_edge(
                    field_nid, object_id(ref_to),
                    "references", "EXTRACTED", str_path,
                ))
    except (ET.ParseError, OSError):
        pass

    return {"nodes": nodes, "edges": edges}


# SF type map by file suffix
_CHILD_SF_TYPES: dict[str, str] = {
    "validationRule-meta.xml": "ValidationRule",
    "recordType-meta.xml": "RecordType",
    "listView-meta.xml": "ListView",
    "compactLayout-meta.xml": "CompactLayout",
    "webLink-meta.xml": "WebLink",
    "sharingReason-meta.xml": "SharingReason",
    "businessProcess-meta.xml": "BusinessProcess",
    "index-meta.xml": "Index",
}


def _child_sf_type(path: Path) -> str:
    for suffix, sf_type in _CHILD_SF_TYPES.items():
        if path.name.endswith(suffix):
            return sf_type
    return "ObjectChild"


def extract_child_object(path: Path) -> dict:
    """Generic handler for object child metadata (validation rules, record types, etc.)."""
    str_path = str(path)
    obj_name = _parent_object_name(path)

    # Build child name from stem (strip compound suffix)
    stem = path.name
    for suffix in _CHILD_SF_TYPES:
        if stem.endswith(suffix):
            stem = stem[: -(len(suffix) + 1)]  # +1 for the dot
            break
    else:
        stem = path.stem

    sf_type = _child_sf_type(path)
    child_nid = make_sf_id(sf_type.lower(), obj_name, stem)
    obj_nid = object_id(obj_name)

    nodes: list[dict] = [{
        "id": child_nid,
        "label": f"{obj_name}: {stem}",
        "sf_type": sf_type,
        "file_type": "object",
        "source_file": str_path,
        "source_location": None,
    }]
    edges: list[dict] = [
        _make_edge(obj_nid, child_nid, "contains", "EXTRACTED", str_path),
    ]

    return {"nodes": nodes, "edges": edges}
