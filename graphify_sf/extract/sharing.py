"""Sharing Rules, Sharing Sets extractor (Epic B2)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ._ids import make_sf_id, object_id


def _get_ns(root_el: ET.Element) -> str:
    if root_el.tag.startswith("{"):
        return root_el.tag.split("}")[0][1:]
    return ""


def _find_text(el: ET.Element, tag: str, ns: str = "") -> str | None:
    if ns:
        child = el.find(f"{{{ns}}}{tag}")
        if child is None:
            child = el.find(tag)
    else:
        child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _findall(el: ET.Element, tag: str, ns: str = "") -> list[ET.Element]:
    if ns:
        results = el.findall(f"{{{ns}}}{tag}")
        if not results:
            results = el.findall(tag)
        return results
    return el.findall(tag)


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


def _object_name_from_stem(path: Path) -> str:
    """Derive the object API name from a sharingRules file stem.

    e.g. Account.sharingRules-meta.xml → Account
    """
    stem = path.name
    for suffix in (".sharingRules-meta.xml", ".sharingSet-meta.xml"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return path.stem


def extract_sharing_rules(path: Path) -> dict:
    """Parse a .sharingRules-meta.xml file.

    Emits CriteriaSharingRule / OwnerSharingRule nodes and
    SharingRule --references--> object EXTRACTED edges.
    """
    if not path.exists():
        return {"nodes": [], "edges": []}
    str_path = str(path)
    obj_name = _object_name_from_stem(path)
    obj_nid = object_id(obj_name)

    nodes: list[dict] = []
    edges: list[dict] = []

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)

        for rule_type, sf_type in (
            ("sharingCriteriaRules", "CriteriaSharingRule"),
            ("sharingOwnerRules", "OwnerSharingRule"),
            ("sharingGuestRules", "GuestSharingRule"),
            ("sharingTerritoryRules", "TerritorySharingRule"),
        ):
            for rule_el in _findall(root_el, rule_type, ns):
                rule_name = _find_text(rule_el, "fullName", ns) or _find_text(rule_el, "label", ns)
                if not rule_name:
                    continue
                rule_nid = make_sf_id(sf_type.lower(), obj_name, rule_name)
                nodes.append(
                    {
                        "id": rule_nid,
                        "label": f"{obj_name}: {rule_name}",
                        "sf_type": sf_type,
                        "file_type": "sharing",
                        "source_file": str_path,
                        "source_location": None,
                    }
                )
                edges.append(_make_edge(rule_nid, obj_nid, "references", "EXTRACTED", str_path))

                # Best-effort: if rule names a target group/role in <sharedTo>
                shared_to_el = rule_el.find(f"{{{ns}}}sharedTo") if ns else rule_el.find("sharedTo")
                if shared_to_el is not None:
                    for child in shared_to_el:
                        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        val = child.text.strip() if child.text else None
                        if val and tag in ("group", "role", "roleAndSubordinates", "queue"):
                            tgt_nid = make_sf_id(tag, val)
                            edges.append(_make_edge(rule_nid, tgt_nid, "references", "EXTRACTED", str_path))

    except (ET.ParseError, OSError):
        pass

    return {"nodes": nodes, "edges": edges}


def extract_sharing_set(path: Path) -> dict:
    """Parse a .sharingSet-meta.xml file → SharingSet node EXTRACTED."""
    if not path.exists():
        return {"nodes": [], "edges": []}
    str_path = str(path)

    # Derive name from stem
    stem = path.name
    if stem.endswith(".sharingSet-meta.xml"):
        name = stem[: -len(".sharingSet-meta.xml")]
    else:
        name = path.stem

    nid = make_sf_id("sharingset", name)
    nodes: list[dict] = [
        {
            "id": nid,
            "label": name,
            "sf_type": "SharingSet",
            "file_type": "sharing",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    return {"nodes": nodes, "edges": []}
