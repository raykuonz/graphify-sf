"""VisualForce page and component extractor."""

from __future__ import annotations

import re
from pathlib import Path

from ._ids import apex_class_id, make_sf_id, object_id, page_id

# Use a negative lookbehind so this does NOT match inside `standardController="..."`
# (the substring `Controller="Account"` would otherwise be parsed as a custom Apex
# controller and emit a phantom `apex_account` reference for a standard object).
# standardController is handled separately by _STD_CONTROLLER_RE below.
_CONTROLLER_RE = re.compile(r'(?<![a-zA-Z])controller\s*=\s*["\'](\w+)["\']', re.IGNORECASE)
_EXTENSIONS_RE = re.compile(r'extensions\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_ACTION_RE = re.compile(r'action\s*=\s*["\']{\s*!\s*(\w+)\.', re.IGNORECASE)
# D2: standardController="ObjectName"
_STD_CONTROLLER_RE = re.compile(r'standardController\s*=\s*["\'](\w+)["\']', re.IGNORECASE)
# D2: <c:componentName …> child VF component references
_CHILD_VF_COMPONENT_RE = re.compile(r"<c:(\w+)", re.IGNORECASE)


def _make_edge(src: str, tgt: str, relation: str, confidence: str, source_file: str, weight: float = 1.0) -> dict:
    return {
        "source": src,
        "target": tgt,
        "relation": relation,
        "confidence": confidence,
        "source_file": source_file,
        "source_location": None,
        "weight": weight,
        "_src": src,
        "_tgt": tgt,
    }


def extract_vf_page(path: Path) -> dict:
    """Extract an ApexPage node and its controller/extension references."""
    str_path = str(path)
    stem = path.stem
    # Remove .page extension is already just the stem
    page_name = stem
    page_nid = page_id(page_name)

    nodes: list[dict] = [
        {
            "id": page_nid,
            "label": page_name,
            "sf_type": "ApexPage",
            "file_type": "visualforce",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = []

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"nodes": nodes, "edges": edges}

    # Controller
    m = _CONTROLLER_RE.search(text)
    if m:
        ctrl = m.group(1)
        edges.append(_make_edge(page_nid, apex_class_id(ctrl), "references", "EXTRACTED", str_path))

    # Extensions (comma-separated)
    em = _EXTENSIONS_RE.search(text)
    if em:
        for ext in em.group(1).split(","):
            ext = ext.strip()
            if ext:
                edges.append(_make_edge(page_nid, apex_class_id(ext), "references", "EXTRACTED", str_path))

    # D2: standardController="ObjectName" → references object node
    sm = _STD_CONTROLLER_RE.search(text)
    if sm:
        edges.append(_make_edge(page_nid, object_id(sm.group(1)), "references", "EXTRACTED", str_path))

    # D2: <c:foo> child VF component tags → uses edge to vfcomponent
    seen_comps: set[str] = set()
    for cm in _CHILD_VF_COMPONENT_RE.finditer(text):
        comp_name = cm.group(1)
        if comp_name not in seen_comps:
            seen_comps.add(comp_name)
            edges.append(_make_edge(page_nid, make_sf_id("vfcomponent", comp_name), "uses", "EXTRACTED", str_path))

    return {"nodes": nodes, "edges": edges}


def extract_vf_component(path: Path) -> dict:
    """Extract an ApexComponent node and its controller reference."""
    str_path = str(path)
    comp_name = path.stem
    comp_nid = make_sf_id("vfcomponent", comp_name)

    nodes: list[dict] = [
        {
            "id": comp_nid,
            "label": comp_name,
            "sf_type": "ApexComponent",
            "file_type": "visualforce",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = []

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"nodes": nodes, "edges": edges}

    m = _CONTROLLER_RE.search(text)
    if m:
        ctrl = m.group(1)
        edges.append(_make_edge(comp_nid, apex_class_id(ctrl), "references", "EXTRACTED", str_path))

    return {"nodes": nodes, "edges": edges}
