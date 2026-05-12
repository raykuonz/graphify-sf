"""Profile and PermissionSet extractor — uses iterparse for large file efficiency."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ._ids import apex_class_id, field_id, object_id, page_id, permset_id, profile_id


def _strip_ns(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _make_edge(src: str, tgt: str, relation: str, confidence: str,
               source_file: str, weight: float = 1.0) -> dict:
    return {
        "source": src, "target": tgt,
        "relation": relation, "confidence": confidence,
        "source_file": source_file, "source_location": None,
        "weight": weight, "_src": src, "_tgt": tgt,
    }


def _extract_permissions(path: Path, node_id_fn, sf_type: str) -> dict:
    """Shared logic for profiles and permission sets."""
    str_path = str(path)
    stem = path.stem
    # Strip compound suffix
    for suffix in (".profile-meta", ".permissionset-meta", ".permissionsetgroup-meta"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    perm_name = stem
    perm_nid = node_id_fn(perm_name)

    nodes: list[dict] = [{
        "id": perm_nid,
        "label": perm_name,
        "sf_type": sf_type,
        "file_type": "profile",
        "source_file": str_path,
        "source_location": None,
    }]
    edges: list[dict] = []
    seen: set[str] = set()

    def add_edge(tgt: str, relation: str, weight: float) -> None:
        key = f"{tgt}"
        if key not in seen:
            seen.add(key)
            edges.append(_make_edge(perm_nid, tgt, relation, "EXTRACTED", str_path, weight))

    # Use iterparse to handle large files
    current_section: str | None = None
    current_data: dict = {}

    try:
        for event, el in ET.iterparse(str_path, events=("start", "end")):
            tag = _strip_ns(el.tag)
            if event == "start":
                if tag in ("objectPermissions", "fieldPermissions", "classAccesses",
                           "pageAccesses", "tabVisibilities", "userPermissions"):
                    current_section = tag
                    current_data = {}
            elif event == "end":
                if tag in ("objectPermissions", "fieldPermissions", "classAccesses",
                           "pageAccesses", "tabVisibilities", "userPermissions"):
                    # Process collected data
                    if current_section == "objectPermissions":
                        obj = current_data.get("object") or current_data.get("objectApiName")
                        if obj:
                            add_edge(object_id(obj), "grants", 0.5)

                    elif current_section == "fieldPermissions":
                        field_raw = current_data.get("field")
                        if field_raw and "." in field_raw:
                            obj_name, field_name = field_raw.split(".", 1)
                            add_edge(field_id(obj_name, field_name), "grants", 0.3)

                    elif current_section == "classAccesses":
                        cls = current_data.get("apexClass")
                        if cls:
                            add_edge(apex_class_id(cls), "grants", 0.5)

                    elif current_section == "pageAccesses":
                        pg = current_data.get("apexPage")
                        if pg:
                            add_edge(page_id(pg), "grants", 0.5)

                    current_section = None
                    current_data = {}
                    el.clear()

                elif current_section and el.text and el.text.strip():
                    current_data[tag] = el.text.strip()

    except ET.ParseError:
        pass

    return {"nodes": nodes, "edges": edges}


def extract_profile(path: Path) -> dict:
    return _extract_permissions(path, profile_id, "Profile")


def extract_permset(path: Path) -> dict:
    stem = path.stem
    if stem.endswith(".permissionsetgroup-meta"):
        return _extract_permissions(path, permset_id, "PermissionSetGroup")
    return _extract_permissions(path, permset_id, "PermissionSet")
