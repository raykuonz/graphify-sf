"""Layout extractor."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ._ids import field_id, layout_id, object_id


def _find_all(root: ET.Element, tag: str, ns: str = "") -> list[ET.Element]:
    if ns:
        result = root.findall(f".//{{{ns}}}{tag}")
        if not result:
            result = root.findall(f".//{tag}")
    else:
        result = root.findall(f".//{tag}")
    return result


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


def extract_layout(path: Path) -> dict:
    """Extract a Layout node and its field references."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".layout-meta"):
        stem = stem[: -len(".layout-meta")]
    layout_name = stem

    # Infer object name: "Account-Account Layout" → "Account"
    obj_name = layout_name.split("-")[0] if "-" in layout_name else layout_name

    layout_nid = layout_id(layout_name)
    obj_nid = object_id(obj_name)

    nodes: list[dict] = [
        {
            "id": layout_nid,
            "label": layout_name,
            "sf_type": "Layout",
            "file_type": "layout",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = [
        _make_edge(layout_nid, obj_nid, "references", "EXTRACTED", str_path),
    ]

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = root_el.tag.split("}")[1] if root_el.tag.startswith("{") else ""
        seen_fields: set[str] = set()
        for item in _find_all(root_el, "layoutItem", ns):
            field_tag = f"{{{ns}}}field" if ns else "field"
            field_el = item.find(field_tag)
            if field_el is None:
                field_el = item.find("field")
            if field_el is not None and field_el.text:
                field_name = field_el.text.strip()
                if field_name and field_name not in seen_fields:
                    seen_fields.add(field_name)
                    edges.append(
                        _make_edge(
                            layout_nid,
                            field_id(obj_name, field_name),
                            "uses",
                            "EXTRACTED",
                            str_path,
                            0.5,
                        )
                    )
    except ET.ParseError:
        pass

    return {"nodes": nodes, "edges": edges}
