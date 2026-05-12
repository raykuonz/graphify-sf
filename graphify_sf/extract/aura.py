"""Aura bundle extractor."""

from __future__ import annotations

import re
from pathlib import Path

from ._ids import apex_class_id, aura_id, make_sf_id

_CONTROLLER_ATTR_RE = re.compile(r'controller\s*=\s*["\'](\w+)["\']', re.IGNORECASE)
_EXTENDS_ATTR_RE = re.compile(r'extends\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_CHILD_COMPONENT_RE = re.compile(r"<(c:|lightning:|force:|ui:)\s*([\w-]+)")
_ENQUEUE_RE = re.compile(r"\$A\.enqueueAction\s*\(\s*(\w+)", re.IGNORECASE)
_ACTION_GET_RE = re.compile(r'\.get\s*\(\s*["\']c\.(\w+)["\']', re.IGNORECASE)
_METHOD_RE = re.compile(r"^(\w+)\s*:\s*function\s*\(", re.MULTILINE)


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


def extract_aura_bundle(bundle_dir: Path) -> dict:
    """Extract nodes and edges from an Aura bundle directory."""
    bundle_dir = Path(bundle_dir)
    name = bundle_dir.name
    nid = aura_id(name)
    cmp_file = bundle_dir / f"{name}.cmp"
    str_cmp = str(cmp_file)

    nodes: list[dict] = [
        {
            "id": nid,
            "label": name,
            "sf_type": "AuraComponent",
            "file_type": "aura",
            "source_file": str_cmp,
            "source_location": None,
        }
    ]
    edges: list[dict] = []
    seen: set[str] = set()

    def add_edge(tgt: str, relation: str, confidence: str, weight: float = 1.0) -> None:
        key = f"{relation}:{tgt}"
        if key not in seen:
            seen.add(key)
            edges.append(_make_edge(nid, tgt, relation, confidence, str_cmp, weight))

    # Parse .cmp file
    if cmp_file.exists():
        try:
            cmp_text = cmp_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            cmp_text = ""

        # Controller attribute
        m = _CONTROLLER_ATTR_RE.search(cmp_text)
        if m:
            add_edge(apex_class_id(m.group(1)), "references", "EXTRACTED")

        # Extends attribute (Aura component inheritance)
        for em in _EXTENDS_ATTR_RE.finditer(cmp_text):
            parent = em.group(1)
            if ":" in parent:
                parent_name = parent.split(":")[1]
                add_edge(aura_id(parent_name), "extends", "INFERRED", 0.8)

        # Child components used in the template
        for cm in _CHILD_COMPONENT_RE.finditer(cmp_text):
            prefix = cm.group(1)
            comp_name = cm.group(2)
            if prefix == "c:":
                add_edge(aura_id(comp_name), "uses", "EXTRACTED")

    # Parse Controller.js
    ctrl_file = bundle_dir / f"{name}Controller.js"
    if ctrl_file.exists():
        try:
            ctrl_text = ctrl_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            ctrl_text = ""

        for m in _METHOD_RE.finditer(ctrl_text):
            method_name = m.group(1)
            method_nid = make_sf_id("auramethod", name, method_name)
            nodes.append(
                {
                    "id": method_nid,
                    "label": f"{name}.{method_name}()",
                    "sf_type": "AuraControllerMethod",
                    "file_type": "aura",
                    "source_file": str(ctrl_file),
                    "source_location": None,
                }
            )
            edges.append(_make_edge(nid, method_nid, "contains", "EXTRACTED", str(ctrl_file)))

    # Parse Helper.js
    helper_file = bundle_dir / f"{name}Helper.js"
    if helper_file.exists():
        try:
            helper_text = helper_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            helper_text = ""

        for m in _METHOD_RE.finditer(helper_text):
            method_name = m.group(1)
            method_nid = make_sf_id("aurahelper", name, method_name)
            nodes.append(
                {
                    "id": method_nid,
                    "label": f"{name}Helper.{method_name}()",
                    "sf_type": "AuraHelperMethod",
                    "file_type": "aura",
                    "source_file": str(helper_file),
                    "source_location": None,
                }
            )
            edges.append(_make_edge(nid, method_nid, "contains", "EXTRACTED", str(helper_file)))

    return {"nodes": nodes, "edges": edges}
