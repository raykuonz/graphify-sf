"""Profile and PermissionSet extractor — uses iterparse for large file efficiency."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ._ids import apex_class_id, field_id, make_sf_id, object_id, page_id, permset_id, profile_id


def _strip_ns(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


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

    nodes: list[dict] = [
        {
            "id": perm_nid,
            "label": perm_name,
            "sf_type": sf_type,
            "file_type": "profile",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = []
    seen: set[str] = set()
    user_permissions: list[str] = []
    stub_node_ids: set[str] = set()

    def add_edge(tgt: str, relation: str, weight: float) -> None:
        key = f"{relation}:{tgt}"
        if key not in seen:
            seen.add(key)
            edges.append(_make_edge(perm_nid, tgt, relation, "EXTRACTED", str_path, weight))

    # Use iterparse to handle large files
    current_section: str | None = None
    current_data: dict = {}

    _SECTION_TAGS = (
        "objectPermissions",
        "fieldPermissions",
        "classAccesses",
        "pageAccesses",
        "tabVisibilities",
        "userPermissions",
        "applicationVisibilities",
    )

    try:
        for event, el in ET.iterparse(str_path, events=("start", "end")):
            tag = _strip_ns(el.tag)
            if event == "start":
                if tag in _SECTION_TAGS:
                    current_section = tag
                    current_data = {}
            elif event == "end":
                if tag in _SECTION_TAGS:
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

                    elif current_section == "userPermissions":
                        # B4: collect enabled userPermissions as a node attr
                        perm_name_val = current_data.get("name")
                        enabled = current_data.get("enabled", "").lower() == "true"
                        if perm_name_val and enabled:
                            user_permissions.append(perm_name_val)

                    elif current_section == "tabVisibilities":
                        # B4: grants edge to a CustomTab stub node; create stub so
                        # cross-ref pass doesn't downgrade EXTRACTED → INFERRED.
                        tab_name = current_data.get("tab")
                        if tab_name:
                            tab_nid = make_sf_id("customtab", tab_name)
                            if tab_nid not in stub_node_ids:
                                stub_node_ids.add(tab_nid)
                                nodes.append(
                                    {
                                        "id": tab_nid,
                                        "label": tab_name,
                                        "sf_type": "CustomTab",
                                        "file_type": "profile",
                                        "source_file": str_path,
                                        "source_location": None,
                                    }
                                )
                            add_edge(tab_nid, "grants", 0.5)

                    elif current_section == "applicationVisibilities":
                        # B4: grants edge to App node when visible=true; stub node so
                        # cross-ref pass doesn't downgrade EXTRACTED → INFERRED.
                        app_name = current_data.get("application")
                        visible = current_data.get("visible", "").lower() == "true"
                        if app_name and visible:
                            app_nid = make_sf_id("app", app_name)
                            if app_nid not in stub_node_ids:
                                stub_node_ids.add(app_nid)
                                nodes.append(
                                    {
                                        "id": app_nid,
                                        "label": app_name,
                                        "sf_type": "App",
                                        "file_type": "profile",
                                        "source_file": str_path,
                                        "source_location": None,
                                    }
                                )
                            add_edge(app_nid, "grants", 0.5)

                    current_section = None
                    current_data = {}
                    el.clear()

                elif current_section and el.text and el.text.strip():
                    current_data[tag] = el.text.strip()

    except ET.ParseError:
        pass

    if user_permissions:
        nodes[0]["user_permissions"] = user_permissions

    return {"nodes": nodes, "edges": edges}


def _extract_psg_members(path: Path) -> dict:
    """Parse PermissionSetGroup: contains edges to member PermissionSets.

    Parses <permissionSets> children → PermissionSetGroup --contains--> PermissionSet
    EXTRACTED. Also collects <mutedPermissions> member names as a node attr.
    """
    str_path = str(path)
    stem = path.stem
    if stem.endswith(".permissionsetgroup-meta"):
        stem = stem[: -len(".permissionsetgroup-meta")]
    psg_name = stem
    psg_nid = permset_id(psg_name)

    nodes: list[dict] = [
        {
            "id": psg_nid,
            "label": psg_name,
            "sf_type": "PermissionSetGroup",
            "file_type": "profile",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = []
    muted: list[str] = []

    # Also collect regular permission data
    base = _extract_permissions(path, permset_id, "PermissionSetGroup")
    # Merge base edges (grants etc.)
    edges.extend(base["edges"])

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = root_el.tag.split("}")[0][1:] if root_el.tag.startswith("{") else ""

        def _find_tag(tag):
            if ns:
                results = root_el.findall(f"{{{ns}}}{tag}")
                if not results:
                    results = root_el.findall(tag)
                return results
            return root_el.findall(tag)

        for ps_el in _find_tag("permissionSets"):
            member_name = ps_el.text.strip() if ps_el.text else None
            if not member_name:
                continue
            member_nid = permset_id(member_name)
            edges.append(_make_edge(psg_nid, member_nid, "contains", "EXTRACTED", str_path))

        for mp_el in _find_tag("mutedPermissions"):
            name = mp_el.text.strip() if mp_el.text else None
            if name:
                muted.append(name)

    except ET.ParseError:
        pass

    if muted:
        nodes[0]["muted_permission_sets"] = muted

    # Copy any extra attrs from base node (e.g. user_permissions)
    if base["nodes"]:
        for k, v in base["nodes"][0].items():
            if k not in nodes[0]:
                nodes[0][k] = v

    return {"nodes": nodes, "edges": edges}


def extract_profile(path: Path) -> dict:
    return _extract_permissions(path, profile_id, "Profile")


def extract_permset(path: Path) -> dict:
    stem = path.stem
    if stem.endswith(".permissionsetgroup-meta"):
        return _extract_psg_members(path)
    return _extract_permissions(path, permset_id, "PermissionSet")
