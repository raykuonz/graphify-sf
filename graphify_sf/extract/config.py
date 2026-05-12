"""Config/labels/misc metadata extractor."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ._ids import label_id, make_sf_id


def _get_ns(root_el: ET.Element) -> str:
    if root_el.tag.startswith("{"):
        return root_el.tag.split("}", 1)[1]
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


def extract_custom_labels(path: Path) -> dict:
    """Extract CustomLabel nodes from CustomLabels.labels-meta.xml."""
    str_path = str(path)
    nodes: list[dict] = []
    edges: list[dict] = []

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)

        for label_el in _find_all(root_el, "labels", ns):
            full_name = _find_text(label_el, "fullName", ns)
            short_desc = _find_text(label_el, "shortDescription", ns)
            if full_name:
                nodes.append(
                    {
                        "id": label_id(full_name),
                        "label": full_name,
                        "sf_type": "CustomLabel",
                        "file_type": "config",
                        "source_file": str_path,
                        "source_location": None,
                        **({"description": short_desc[:200]} if short_desc else {}),
                    }
                )
    except ET.ParseError:
        pass

    return {"nodes": nodes, "edges": edges}


def extract_custom_metadata_record(path: Path) -> dict:
    """Extract a CustomMetadata record node from .md-meta.xml."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".md-meta"):
        stem = stem[: -len(".md-meta")]
    # stem is typically "Type.Record" e.g. "MyType.MyRecord"
    record_nid = make_sf_id("custommetadata", stem)

    nodes: list[dict] = [
        {
            "id": record_nid,
            "label": stem,
            "sf_type": "CustomMetadataRecord",
            "file_type": "config",
            "source_file": str_path,
            "source_location": None,
        }
    ]

    return {"nodes": nodes, "edges": []}


def extract_named_credential(path: Path) -> dict:
    """Extract a NamedCredential node."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".namedCredential-meta"):
        stem = stem[: -len(".namedCredential-meta")]
    nid = make_sf_id("namedcredential", stem)

    nodes: list[dict] = [
        {
            "id": nid,
            "label": stem,
            "sf_type": "NamedCredential",
            "file_type": "config",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    return {"nodes": nodes, "edges": []}


def extract_external_service(path: Path) -> dict:
    """Extract an ExternalService node and its uses edge to NamedCredential."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".externalService-meta"):
        stem = stem[: -len(".externalService-meta")]
    nid = make_sf_id("externalservice", stem)

    nodes: list[dict] = [
        {
            "id": nid,
            "label": stem,
            "sf_type": "ExternalService",
            "file_type": "config",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = []

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)
        nc = _find_text(root_el, "namedCredential", ns)
        if nc:
            edges.append(_make_edge(nid, make_sf_id("namedcredential", nc), "uses", "EXTRACTED", str_path))
    except ET.ParseError:
        pass

    return {"nodes": nodes, "edges": edges}


def extract_flexipage(path: Path) -> dict:
    """Extract a FlexiPage node and its embedded component references."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".flexipage-meta"):
        stem = stem[: -len(".flexipage-meta")]
    nid = make_sf_id("flexipage", stem)

    nodes: list[dict] = [
        {
            "id": nid,
            "label": stem,
            "sf_type": "FlexiPage",
            "file_type": "config",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = []
    seen: set[str] = set()

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)

        for comp_el in _find_all(root_el, "componentName", ns):
            if comp_el.text:
                comp_name = comp_el.text.strip()
                if comp_name and comp_name not in seen:
                    seen.add(comp_name)
                    # LWC components are typically c__ComponentName or c:ComponentName
                    from ._ids import lwc_id

                    # Normalize: c__AccountCard → accountCard, c:accountCard → accountCard
                    normalized = comp_name.replace("c__", "").replace("c:", "").replace("__", "_")
                    edges.append(_make_edge(nid, lwc_id(normalized), "contains", "INFERRED", str_path, 0.7))
    except ET.ParseError:
        pass

    return {"nodes": nodes, "edges": edges}


def extract_generic_config(path: Path) -> dict:
    """Generic extractor for config files not covered by specific extractors."""
    str_path = str(path)
    stem = path.stem
    # Remove compound suffix
    for suffix in (
        ".settings-meta",
        ".connectedApp-meta",
        ".app-meta",
        ".tab-meta",
        ".testSuite-meta",
        ".remoteSite-meta",
        ".role-meta",
        ".site-meta",
        ".network-meta",
    ):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break

    # Determine sf_type from the extension
    sf_type_map = {
        "settings-meta.xml": "Settings",
        "connectedApp-meta.xml": "ConnectedApp",
        "app-meta.xml": "CustomApplication",
        "tab-meta.xml": "CustomTab",
        "testSuite-meta.xml": "ApexTestSuite",
        "remoteSite-meta.xml": "RemoteSiteSetting",
        "role-meta.xml": "UserRole",
        "site-meta.xml": "CustomSite",
        "network-meta.xml": "Network",
    }
    sf_type = "Config"
    for key, val in sf_type_map.items():
        if path.name.endswith(key):
            sf_type = val
            break

    nid = make_sf_id(sf_type.lower(), stem)
    nodes: list[dict] = [
        {
            "id": nid,
            "label": stem,
            "sf_type": sf_type,
            "file_type": "config",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    return {"nodes": nodes, "edges": []}
