"""VisualForce page and component extractor."""
from __future__ import annotations

import re
from pathlib import Path

from ._ids import apex_class_id, make_sf_id, page_id

_CONTROLLER_RE = re.compile(r'controller\s*=\s*["\'](\w+)["\']', re.IGNORECASE)
_EXTENSIONS_RE = re.compile(r'extensions\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_ACTION_RE = re.compile(r'action\s*=\s*["\']{\s*!\s*(\w+)\.', re.IGNORECASE)


def _make_edge(src: str, tgt: str, relation: str, confidence: str,
               source_file: str, weight: float = 1.0) -> dict:
    return {
        "source": src, "target": tgt,
        "relation": relation, "confidence": confidence,
        "source_file": source_file, "source_location": None,
        "weight": weight, "_src": src, "_tgt": tgt,
    }


def extract_vf_page(path: Path) -> dict:
    """Extract an ApexPage node and its controller/extension references."""
    str_path = str(path)
    stem = path.stem
    # Remove .page extension is already just the stem
    page_name = stem
    page_nid = page_id(page_name)

    nodes: list[dict] = [{
        "id": page_nid,
        "label": page_name,
        "sf_type": "ApexPage",
        "file_type": "visualforce",
        "source_file": str_path,
        "source_location": None,
    }]
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

    return {"nodes": nodes, "edges": edges}


def extract_vf_component(path: Path) -> dict:
    """Extract an ApexComponent node and its controller reference."""
    str_path = str(path)
    comp_name = path.stem
    comp_nid = make_sf_id("vfcomponent", comp_name)

    nodes: list[dict] = [{
        "id": comp_nid,
        "label": comp_name,
        "sf_type": "ApexComponent",
        "file_type": "visualforce",
        "source_file": str_path,
        "source_location": None,
    }]
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
