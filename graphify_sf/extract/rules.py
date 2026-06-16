"""Restriction Rules, Duplicate Rules, and Matching Rules extractor (Epic B5)."""

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


def _object_from_path(path: Path, suffix: str) -> str:
    """Derive the object API name from a rule file path.

    Uses the file stem (everything before the compound suffix) as the object name.
    e.g. Account.duplicateRule-meta.xml → Account
    """
    name = path.name
    if name.endswith(suffix):
        return name[: -len(suffix)]
    return path.stem


def extract_restriction_rule(path: Path) -> dict:
    """Parse a .restrictionRule-meta.xml file → RestrictionRule node + references edge."""
    if not path.exists():
        return {"nodes": [], "edges": []}
    str_path = str(path)

    # Derive rule name and object from path
    # Convention: <ObjectName>.<RuleName>.restrictionRule-meta.xml or just flat
    stem_full = path.name
    suffix = ".restrictionRule-meta.xml"
    if stem_full.endswith(suffix):
        base = stem_full[: -len(suffix)]
    else:
        base = path.stem
    rule_nid = make_sf_id("restrictionrule", base)

    nodes: list[dict] = [
        {
            "id": rule_nid,
            "label": base,
            "sf_type": "RestrictionRule",
            "file_type": "rules",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = []

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)

        # <targetEntity> holds the object API name
        target_entity = _find_text(root_el, "targetEntity", ns)
        obj_name = target_entity or base  # fallback to file stem
        edges.append(_make_edge(rule_nid, object_id(obj_name), "references", "EXTRACTED", str_path))

    except (ET.ParseError, OSError):
        # Still emit references edge based on filename
        edges.append(_make_edge(rule_nid, object_id(base), "references", "EXTRACTED", str_path))

    return {"nodes": nodes, "edges": edges}


def extract_duplicate_rule(path: Path) -> dict:
    """Parse a .duplicateRule-meta.xml file.

    Emits DuplicateRule node + references edge to object + references edge to
    any MatchingRule named in <matchingRules> / <duplicateRuleMatchingRules>.
    """
    if not path.exists():
        return {"nodes": [], "edges": []}
    str_path = str(path)

    suffix = ".duplicateRule-meta.xml"
    stem_full = path.name
    if stem_full.endswith(suffix):
        base = stem_full[: -len(suffix)]
    else:
        base = path.stem

    rule_nid = make_sf_id("duplicaterule", base)

    nodes: list[dict] = [
        {
            "id": rule_nid,
            "label": base,
            "sf_type": "DuplicateRule",
            "file_type": "rules",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = []

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)

        # Object comes from <sobjectType> or the file base (object name before any dot)
        sobject_type = _find_text(root_el, "sobjectType", ns)
        # base may be "Account" or "Account.My_Rule"; extract the object part
        obj_name = sobject_type or base.split(".")[0]
        edges.append(_make_edge(rule_nid, object_id(obj_name), "references", "EXTRACTED", str_path))

        # Find matching rule references in <duplicateRuleMatchingRules>
        def _findall(el, tag):
            if ns:
                res = el.findall(f"{{{ns}}}{tag}")
                if not res:
                    res = el.findall(tag)
                return res
            return el.findall(tag)

        for dr_mr_el in _findall(root_el, "duplicateRuleMatchingRules"):
            mr_name = _find_text(dr_mr_el, "matchingRule", ns)
            if mr_name:
                mr_nid = make_sf_id("matchingrule", mr_name)
                edges.append(_make_edge(rule_nid, mr_nid, "references", "EXTRACTED", str_path))

        # Also check flat <matchingRules> children
        for mr_el in _findall(root_el, "matchingRules"):
            mr_name_text = mr_el.text.strip() if mr_el.text else None
            if mr_name_text:
                mr_nid = make_sf_id("matchingrule", mr_name_text)
                edges.append(_make_edge(rule_nid, mr_nid, "references", "EXTRACTED", str_path))

    except (ET.ParseError, OSError):
        obj_name = base.split(".")[0]
        edges.append(_make_edge(rule_nid, object_id(obj_name), "references", "EXTRACTED", str_path))

    return {"nodes": nodes, "edges": edges}


def extract_matching_rule(path: Path) -> dict:
    """Parse a .matchingRule-meta.xml file.

    A matchingRules file may bundle multiple <matchingRules> entries (like the
    standard Account.matchingRule-meta.xml format). Emits one MatchingRule node
    per entry (or one node for the file if no entries found).
    """
    if not path.exists():
        return {"nodes": [], "edges": []}
    str_path = str(path)

    suffix = ".matchingRule-meta.xml"
    stem_full = path.name
    if stem_full.endswith(suffix):
        base = stem_full[: -len(suffix)]
    else:
        base = path.stem

    nodes: list[dict] = []
    edges: list[dict] = []

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)

        def _findall(el, tag):
            if ns:
                res = el.findall(f"{{{ns}}}{tag}")
                if not res:
                    res = el.findall(tag)
                return res
            return el.findall(tag)

        rules = _findall(root_el, "matchingRules")
        if rules:
            for rule_el in rules:
                rule_name = _find_text(rule_el, "fullName", ns)
                if not rule_name:
                    continue
                # Canonical id matches what DuplicateRule references:
                # make_sf_id("matchingrule", "<ObjectName>.<RuleName>")
                full_name = f"{base}.{rule_name}"
                mr_nid = make_sf_id("matchingrule", full_name)
                nodes.append(
                    {
                        "id": mr_nid,
                        "label": full_name,
                        "sf_type": "MatchingRule",
                        "file_type": "rules",
                        "source_file": str_path,
                        "source_location": None,
                    }
                )
        else:
            # Single-rule file or bundle with no parsed entries — emit one node
            mr_nid = make_sf_id("matchingrule", base)
            nodes.append(
                {
                    "id": mr_nid,
                    "label": base,
                    "sf_type": "MatchingRule",
                    "file_type": "rules",
                    "source_file": str_path,
                    "source_location": None,
                }
            )

    except (ET.ParseError, OSError):
        mr_nid = make_sf_id("matchingrule", base)
        nodes.append(
            {
                "id": mr_nid,
                "label": base,
                "sf_type": "MatchingRule",
                "file_type": "rules",
                "source_file": str_path,
                "source_location": None,
            }
        )

    return {"nodes": nodes, "edges": edges}
