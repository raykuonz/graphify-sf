"""Config/labels/misc metadata extractor."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ._ids import aura_id, label_id, lwc_id, make_sf_id, object_id, page_id


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
    """Extract a FlexiPage node, its custom component references, and object link."""
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

        sobject_type = _find_text(root_el, "sobjectType", ns)
        if sobject_type:
            edges.append(_make_edge(nid, object_id(sobject_type), "record_page_for", "EXTRACTED", str_path))

        for comp_el in _find_all(root_el, "componentName", ns):
            if not comp_el.text:
                continue
            comp_name = comp_el.text.strip()
            if comp_name in seen:
                continue
            seen.add(comp_name)

            if comp_name.startswith("c__"):
                # c__ prefix → custom LWC
                normalized = comp_name[3:].replace("__", "_")
                edges.append(_make_edge(nid, lwc_id(normalized), "contains", "INFERRED", str_path, 0.7))
            elif comp_name.startswith("c:"):
                inner = comp_name[2:]
                if inner and inner[0].isupper():
                    # D3: PascalCase after c: → Aura component by Salesforce naming convention
                    edges.append(_make_edge(nid, aura_id(inner), "contains", "EXTRACTED", str_path))
                else:
                    # camelCase after c: → LWC (existing behaviour)
                    edges.append(_make_edge(nid, lwc_id(inner), "contains", "INFERRED", str_path, 0.7))
            # Other namespace:Component patterns (force:, lightning:, forceCommunity:, etc.)
            # are standard Salesforce platform components — skip them.
    except ET.ParseError:
        pass

    return {"nodes": nodes, "edges": edges}


def extract_remote_site_setting(path: Path) -> dict:
    """Extract a RemoteSiteSetting node with endpoint_url from <url>."""
    str_path = str(path)
    stem = path.stem
    for suffix in (".remoteSiteSetting-meta", ".remoteSite-meta"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    nid = make_sf_id("remotesitesetting", stem)
    node: dict = {
        "id": nid,
        "label": stem,
        "sf_type": "RemoteSiteSetting",
        "file_type": "config",
        "source_file": str_path,
        "source_location": None,
    }
    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)
        url = _find_text(root_el, "url", ns)
        if url:
            node["endpoint_url"] = url
    except ET.ParseError:
        pass
    return {"nodes": [node], "edges": []}


def extract_external_data_source(path: Path) -> dict:
    """Extract an ExternalDataSource node; emit uses→NamedCredential if present."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".externalDataSource-meta"):
        stem = stem[: -len(".externalDataSource-meta")]
    nid = make_sf_id("externaldatasource", stem)
    node: dict = {
        "id": nid,
        "label": stem,
        "sf_type": "ExternalDataSource",
        "file_type": "config",
        "source_file": str_path,
        "source_location": None,
    }
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
    return {"nodes": [node], "edges": edges}


def extract_auth_provider(path: Path) -> dict:
    """Extract an AuthProvider node."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".authprovider-meta"):
        stem = stem[: -len(".authprovider-meta")]
    nid = make_sf_id("authprovider", stem)
    return {
        "nodes": [
            {
                "id": nid,
                "label": stem,
                "sf_type": "AuthProvider",
                "file_type": "config",
                "source_file": str_path,
                "source_location": None,
            }
        ],
        "edges": [],
    }


def extract_csp_trusted_site(path: Path) -> dict:
    """Extract a CspTrustedSite node with endpoint_url from <endpointUrl> or <url>."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".cspTrustedSite-meta"):
        stem = stem[: -len(".cspTrustedSite-meta")]
    nid = make_sf_id("csptrustedsite", stem)
    node: dict = {
        "id": nid,
        "label": stem,
        "sf_type": "CspTrustedSite",
        "file_type": "config",
        "source_file": str_path,
        "source_location": None,
    }
    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)
        url = _find_text(root_el, "endpointUrl", ns) or _find_text(root_el, "url", ns)
        if url:
            node["endpoint_url"] = url
    except ET.ParseError:
        pass
    return {"nodes": [node], "edges": []}


def extract_cors_origin(path: Path) -> dict:
    """Extract a CorsOrigin node with url_pattern from <urlPattern>."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".corsWhitelistOrigins-meta"):
        stem = stem[: -len(".corsWhitelistOrigins-meta")]
    nid = make_sf_id("corsorigin", stem)
    node: dict = {
        "id": nid,
        "label": stem,
        "sf_type": "CorsOrigin",
        "file_type": "config",
        "source_file": str_path,
        "source_location": None,
    }
    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)
        url_pattern = _find_text(root_el, "urlPattern", ns)
        if url_pattern:
            node["url_pattern"] = url_pattern
    except ET.ParseError:
        pass
    return {"nodes": [node], "edges": []}


def extract_static_resource(path: Path) -> dict:
    """Extract a StaticResource node from .resource-meta.xml."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".resource-meta"):
        stem = stem[: -len(".resource-meta")]
    nid = make_sf_id("staticresource", stem)
    return {
        "nodes": [
            {
                "id": nid,
                "label": stem,
                "sf_type": "StaticResource",
                "file_type": "config",
                "source_file": str_path,
                "source_location": None,
            }
        ],
        "edges": [],
    }


def extract_quick_action(path: Path) -> dict:
    """Extract a QuickAction node; emit references→object and uses→LWC/VF if present."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".quickAction-meta"):
        stem = stem[: -len(".quickAction-meta")]
    nid = make_sf_id("quickaction", stem)
    nodes: list[dict] = [
        {
            "id": nid,
            "label": stem,
            "sf_type": "QuickAction",
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

        target_obj = _find_text(root_el, "targetObject", ns)
        if target_obj:
            edges.append(_make_edge(nid, make_sf_id("object", target_obj), "references", "EXTRACTED", str_path))

        lightning_comp = _find_text(root_el, "lightningComponent", ns)
        if lightning_comp:
            edges.append(_make_edge(nid, lwc_id(lightning_comp), "uses", "EXTRACTED", str_path))

        vf_page = _find_text(root_el, "page", ns)
        if vf_page:
            edges.append(_make_edge(nid, page_id(vf_page), "uses", "EXTRACTED", str_path))
    except ET.ParseError:
        pass

    return {"nodes": nodes, "edges": edges}


def extract_custom_tab(path: Path) -> dict:
    """Extract a CustomTab node; emit references→object or flexipage if present."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".tab-meta"):
        stem = stem[: -len(".tab-meta")]
    nid = make_sf_id("customtab", stem)
    nodes: list[dict] = [
        {
            "id": nid,
            "label": stem,
            "sf_type": "CustomTab",
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

        custom_obj = _find_text(root_el, "customObject", ns)
        if custom_obj:
            edges.append(_make_edge(nid, make_sf_id("object", custom_obj), "references", "EXTRACTED", str_path))

        flexi = _find_text(root_el, "flexiPage", ns)
        if flexi:
            edges.append(_make_edge(nid, make_sf_id("flexipage", flexi), "references", "EXTRACTED", str_path))
    except ET.ParseError:
        pass

    return {"nodes": nodes, "edges": edges}


def extract_custom_app(path: Path) -> dict:
    """Extract a CustomApplication node; emit contains→CustomTab for each listed tab."""
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".app-meta"):
        stem = stem[: -len(".app-meta")]
    nid = make_sf_id("customapplication", stem)
    nodes: list[dict] = [
        {
            "id": nid,
            "label": stem,
            "sf_type": "CustomApplication",
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

        for tab_el in _find_all(root_el, "tabs", ns):
            if tab_el.text and tab_el.text.strip():
                tab_name = tab_el.text.strip()
                edges.append(_make_edge(nid, make_sf_id("customtab", tab_name), "contains", "EXTRACTED", str_path))
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
