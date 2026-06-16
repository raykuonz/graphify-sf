"""Reports, Dashboards, Report Types, and InstalledPackage extractors (Epic F)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ._ids import field_id, make_sf_id, object_id


def _get_ns(root_el: ET.Element) -> str:
    if root_el.tag.startswith("{"):
        return root_el.tag.split("}", 1)[0][1:]
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
    """Recursive findall with namespace fallback."""
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


def _stem_before(path: Path, suffix: str) -> str:
    name = path.name
    if name.endswith(suffix):
        return name[: -len(suffix)]
    return path.stem


def _emit_field_edge(
    src_nid: str,
    field_str: str,
    primary_obj: str | None,
    edges: list,
    str_path: str,
) -> None:
    """Emit a uses edge to a field node.

    "Object.Field" → EXTRACTED (object context explicit in the field name).
    Bare field with known primary_obj → INFERRED (heuristic resolution).
    No context → skip (never create phantom nodes).
    """
    if not field_str:
        return
    if "." in field_str:
        obj_name, field_name = field_str.split(".", 1)
        edges.append(_make_edge(src_nid, field_id(obj_name, field_name), "uses", "EXTRACTED", str_path))
    elif primary_obj:
        edges.append(_make_edge(src_nid, field_id(primary_obj, field_str), "uses", "INFERRED", str_path))
    # else: no context → do not emit (avoids phantom nodes for system formula fields)


def extract_report(path: Path) -> dict:
    """Parse a .report-meta.xml → Report node + references→ReportType + uses→fields.

    F1: Edges land in graph.json links. The reportType value is always expressed
    as reporttype_<x> — never as object_<x> — to avoid phantom nodes for
    standard Salesforce report-type names that are not object metadata.
    """
    if not path.exists():
        return {"nodes": [], "edges": []}
    str_path = str(path)
    name = _stem_before(path, ".report-meta.xml")
    nid = make_sf_id("report", name)

    nodes: list[dict] = [
        {
            "id": nid,
            "label": name,
            "sf_type": "Report",
            "file_type": "reporting",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = []

    try:
        tree = ET.parse(str_path)
        root = tree.getroot()
        ns = _get_ns(root)

        # <reportType> → references → reporttype_<x> EXTRACTED.
        # Use reporttype_ prefix always — do NOT emit object_ ids for standard
        # report-type names that aren't objects.
        report_type_val = _find_text(root, "reportType", ns)
        primary_obj: str | None = None
        if report_type_val:
            rt_nid = make_sf_id("reporttype", report_type_val)
            edges.append(_make_edge(nid, rt_nid, "references", "EXTRACTED", str_path))
            primary_obj = report_type_val

        # <columns><field> → uses → field EXTRACTED (Object.Field) or INFERRED (bare)
        for col_el in _find_all(root, "columns", ns):
            field_val = _find_text(col_el, "field", ns)
            _emit_field_edge(nid, field_val, primary_obj, edges, str_path)

        # <filter><criteriaItems><column> → uses → field
        for ci_el in _find_all(root, "criteriaItems", ns):
            col_val = _find_text(ci_el, "column", ns)
            _emit_field_edge(nid, col_val, primary_obj, edges, str_path)

        # <groupingsDown>/<groupingsAcross> → <field>
        for grp_el in _find_all(root, "groupingsDown", ns) + _find_all(root, "groupingsAcross", ns):
            field_val = _find_text(grp_el, "field", ns)
            _emit_field_edge(nid, field_val, primary_obj, edges, str_path)

    except (ET.ParseError, OSError):
        pass

    return {"nodes": nodes, "edges": edges}


def extract_dashboard(path: Path) -> dict:
    """Parse a .dashboard-meta.xml → Dashboard node + uses→Report edges EXTRACTED."""
    if not path.exists():
        return {"nodes": [], "edges": []}
    str_path = str(path)
    name = _stem_before(path, ".dashboard-meta.xml")
    nid = make_sf_id("dashboard", name)

    nodes: list[dict] = [
        {
            "id": nid,
            "label": name,
            "sf_type": "Dashboard",
            "file_type": "reporting",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = []

    try:
        tree = ET.parse(str_path)
        root = tree.getroot()
        ns = _get_ns(root)

        # <components><report> → uses → report_<name> EXTRACTED.
        # Report refs may be "FolderName/ReportApiName"; take the last segment.
        seen: set[str] = set()
        for report_el in _find_all(root, "report", ns):
            report_ref = report_el.text.strip() if report_el.text else None
            if not report_ref:
                continue
            report_name = report_ref.split("/")[-1]
            r_nid = make_sf_id("report", report_name)
            if r_nid not in seen:
                seen.add(r_nid)
                edges.append(_make_edge(nid, r_nid, "uses", "EXTRACTED", str_path))

    except (ET.ParseError, OSError):
        pass

    return {"nodes": nodes, "edges": edges}


def extract_report_type(path: Path) -> dict:
    """Parse a .reportType-meta.xml → ReportType node + references→object + uses→fields."""
    if not path.exists():
        return {"nodes": [], "edges": []}
    str_path = str(path)
    name = _stem_before(path, ".reportType-meta.xml")
    nid = make_sf_id("reporttype", name)

    nodes: list[dict] = [
        {
            "id": nid,
            "label": name,
            "sf_type": "ReportType",
            "file_type": "reporting",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = []

    try:
        tree = ET.parse(str_path)
        root = tree.getroot()
        ns = _get_ns(root)

        # <baseObject> → references → object_<x> EXTRACTED
        base_obj = _find_text(root, "baseObject", ns)
        if base_obj:
            edges.append(_make_edge(nid, object_id(base_obj), "references", "EXTRACTED", str_path))

        # <sections>/<columns>/<field> → uses → field_<baseObj>_<field> EXTRACTED
        if base_obj:
            for col_el in _find_all(root, "columns", ns):
                field_val = _find_text(col_el, "field", ns)
                if field_val:
                    edges.append(
                        _make_edge(nid, field_id(base_obj, field_val), "uses", "EXTRACTED", str_path)
                    )

    except (ET.ParseError, OSError):
        pass

    return {"nodes": nodes, "edges": edges}


def extract_installed_package(path: Path) -> dict:
    """Parse a .installedPackage-meta.xml → InstalledPackage node EXTRACTED (F2)."""
    if not path.exists():
        return {"nodes": [], "edges": []}
    str_path = str(path)
    name = _stem_before(path, ".installedPackage-meta.xml")
    nid = make_sf_id("installedpackage", name)

    node: dict = {
        "id": nid,
        "label": name,
        "sf_type": "InstalledPackage",
        "file_type": "packaging",
        "source_file": str_path,
        "source_location": None,
    }

    try:
        tree = ET.parse(str_path)
        root = tree.getroot()
        ns = _get_ns(root)
        version = _find_text(root, "versionNumber", ns)
        if version:
            node["version"] = version
        namespace = _find_text(root, "namespace", ns)
        if namespace:
            node["namespace"] = namespace
    except (ET.ParseError, OSError):
        pass

    return {"nodes": [node], "edges": []}
