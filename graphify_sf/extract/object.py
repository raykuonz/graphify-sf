"""CustomObject, CustomField, and child metadata extractor."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ._ids import field_id, make_sf_id, object_id

# Regex to extract custom field API names from formula strings.
# Matches names ending in __c or __r (custom fields/relationships), or
# cross-object references like Account.Name (Object.Field pattern).
# Intentionally conservative to minimise false positives.
_VR_CUSTOM_FIELD_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*__[cr])\b")
_VR_CROSS_OBJECT_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]+)\.([A-Za-z][A-Za-z0-9_]*__[cr])\b")

# C4: Standard (non-custom) field detection in ValidationRule formulas. Stays
# INFERRED because regex cannot distinguish a field reference from a formula
# function name at every callsite. Conservative strategy: only match identifiers
# that appear in a direct comparison context OR as the first argument of common
# field-inspection functions. False-positive sources: formula function names that
# happen to be CamelCase (TEXT, VALUE…) are excluded via _VR_FORMULA_FUNCTIONS;
# identifiers not in these positions are silently ignored to limit noise.
_VR_FORMULA_FUNCTIONS = frozenset(
    {
        "AND",
        "OR",
        "NOT",
        "IF",
        "CASE",
        "WHEN",
        "THEN",
        "ELSE",
        "END",
        "TEXT",
        "VALUE",
        "DATE",
        "DATEVALUE",
        "DATETIMEVALUE",
        "TODAY",
        "NOW",
        "YEAR",
        "MONTH",
        "DAY",
        "HOUR",
        "MINUTE",
        "SECOND",
        "WEEKDAY",
        "ADDMONTHS",
        "ISBLANK",
        "ISNULL",
        "ISCHANGED",
        "ISNEW",
        "ISPICKVAL",
        "LEFT",
        "RIGHT",
        "MID",
        "LEN",
        "FIND",
        "SUBSTITUTE",
        "TRIM",
        "UPPER",
        "LOWER",
        "CONTAINS",
        "BEGINS",
        "INCLUDES",
        "EXCLUDES",
        "MAX",
        "MIN",
        "ABS",
        "SQRT",
        "MOD",
        "ROUND",
        "MROUND",
        "FLOOR",
        "CEILING",
        "LOG",
        "EXP",
        "LN",
        "BLANKVALUE",
        "NULLVALUE",
        "PRIORVALUE",
        "REGEX",
        "IMAGE",
        "HYPERLINK",
        "BR",
        "VLOOKUP",
        "TRUE",
        "FALSE",
        "NULL",
        "LABEL",
        "GETRECORDIDS",
        "PARENTGROUPVAL",
        "PREVGROUPVAL",
    }
)
# Identifier immediately before a comparison operator (not preceded by a dot,
# so cross-object path segments like Account__r.Field are not double-counted).
_VR_STD_FIELD_CMP_RE = re.compile(r"(?<!\.)(\b[A-Z][A-Za-z0-9_]*\b)\s*(?:!=|<>|<=|>=|<|>|==|=(?!=))")
# Identifier as first argument of common field-inspection functions.
_VR_STD_FIELD_FUNC_RE = re.compile(
    r"\b(?:ISBLANK|ISNULL|ISPICKVAL|ISCHANGED|PRIORVALUE)\s*\(\s*(\b[A-Z][A-Za-z0-9_]*\b)",
    re.IGNORECASE,
)


def _find_text(el: ET.Element, tag: str, ns: str = "") -> str | None:
    if ns:
        child = el.find(f"{{{ns}}}{tag}")
        if child is None:
            child = el.find(tag)
    else:
        child = el.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _get_ns(root_el: ET.Element) -> str:
    if root_el.tag.startswith("{"):
        return root_el.tag.split("}")[0][1:]
    return ""


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


def _object_name_from_stem(path: Path) -> str:
    """Extract the object API name from a .object-meta.xml file stem."""
    stem = path.stem
    if stem.endswith(".object-meta"):
        return stem[: -len(".object-meta")]
    return stem


def _parent_object_name(path: Path) -> str:
    """Infer the parent object name from a field/child metadata file path.

    Convention: objects/<ObjectName>/fields/<FieldName>.field-meta.xml
                objects/<ObjectName>/validationRules/<RuleName>.validationRule-meta.xml
    """
    # parent is the type dir (fields, validationRules, etc.)
    # grandparent is the object dir
    return path.parent.parent.name


def extract_custom_object(path: Path) -> dict:
    """Extract a CustomObject node from .object-meta.xml.

    Detects special object types by API-name suffix:
    - ``__x`` → ExternalObject (A4)
    - ``__e`` → PlatformEvent (A5)
    - ``<customSettingsType>`` element → CustomSetting (A6)
    """
    if not path.exists():
        return {"nodes": [], "edges": []}
    str_path = str(path)
    obj_name = _object_name_from_stem(path)
    obj_nid = object_id(obj_name)

    # Determine sf_type from object API name suffix
    if obj_name.endswith("__x"):
        sf_type = "ExternalObject"
    elif obj_name.endswith("__e"):
        sf_type = "PlatformEvent"
    else:
        sf_type = "CustomObject"  # may be overridden by <customSettingsType> below

    nodes: list[dict] = [
        {
            "id": obj_nid,
            "label": obj_name,
            "sf_type": sf_type,
            "file_type": "object",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = []

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)
        label = _find_text(root_el, "label", ns)
        if label:
            nodes[0]["display_label"] = label
        desc = _find_text(root_el, "description", ns)
        if desc:
            nodes[0]["description"] = desc[:200]

        # CustomSetting: <customSettingsType> overrides sf_type for __c objects
        if sf_type == "CustomObject":
            custom_settings_type = _find_text(root_el, "customSettingsType", ns)
            if custom_settings_type:
                nodes[0]["sf_type"] = "CustomSetting"

        # B1: Org-Wide Defaults — read sharing model declarations
        sharing_model = _find_text(root_el, "sharingModel", ns)
        if sharing_model:
            nodes[0]["sharing_model"] = sharing_model
        ext_sharing_model = _find_text(root_el, "externalSharingModel", ns)
        if ext_sharing_model:
            nodes[0]["external_sharing_model"] = ext_sharing_model

        # ExternalObject: parse <externalDataSource> → backed_by edge (A4)
        if sf_type == "ExternalObject":
            ext_ds = _find_text(root_el, "externalDataSource", ns)
            if ext_ds:
                edges.append(
                    _make_edge(
                        obj_nid,
                        make_sf_id("externaldatasource", ext_ds),
                        "backed_by",
                        "EXTRACTED",
                        str_path,
                    )
                )
    except (ET.ParseError, OSError):
        pass

    return {"nodes": nodes, "edges": edges}


def extract_custom_field(path: Path) -> dict:
    """Extract a CustomField node and its relationship to the parent object."""
    str_path = str(path)
    obj_name = _parent_object_name(path)

    # Field name from stem
    stem = path.stem
    for suffix in (".field-meta", ".field"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    field_name = stem

    field_nid = field_id(obj_name, field_name)
    obj_nid = object_id(obj_name)

    nodes: list[dict] = [
        {
            "id": field_nid,
            "label": f"{obj_name}.{field_name}",
            "sf_type": "CustomField",
            "file_type": "object",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = [
        _make_edge(obj_nid, field_nid, "contains", "EXTRACTED", str_path),
    ]

    try:
        tree = ET.parse(str_path)
        root_el = tree.getroot()
        ns = _get_ns(root_el)
        field_type = _find_text(root_el, "type", ns)
        if field_type:
            nodes[0]["field_type"] = field_type
        label = _find_text(root_el, "label", ns)
        if label:
            nodes[0]["display_label"] = label

        # Lookup / MasterDetail / Hierarchy → references the target object
        # MasterDetail gets its own relation name to distinguish ownership semantics.
        if field_type in ("Lookup", "MasterDetail", "Hierarchy"):
            ref_to = _find_text(root_el, "referenceTo", ns)
            if ref_to:
                relation = "master_detail" if field_type == "MasterDetail" else "references"
                edges.append(
                    _make_edge(
                        field_nid,
                        object_id(ref_to),
                        relation,
                        "EXTRACTED",
                        str_path,
                    )
                )
    except (ET.ParseError, OSError):
        pass

    return {"nodes": nodes, "edges": edges}


# SF type map by file suffix
_CHILD_SF_TYPES: dict[str, str] = {
    "validationRule-meta.xml": "ValidationRule",
    "recordType-meta.xml": "RecordType",
    "listView-meta.xml": "ListView",
    "compactLayout-meta.xml": "CompactLayout",
    "webLink-meta.xml": "WebLink",
    "sharingReason-meta.xml": "SharingReason",
    "businessProcess-meta.xml": "BusinessProcess",
    "index-meta.xml": "Index",
}


def _child_sf_type(path: Path) -> str:
    for suffix, sf_type in _CHILD_SF_TYPES.items():
        if path.name.endswith(suffix):
            return sf_type
    return "ObjectChild"


def extract_child_object(path: Path) -> dict:
    """Generic handler for object child metadata (validation rules, record types, etc.)."""
    str_path = str(path)
    obj_name = _parent_object_name(path)

    # Build child name from stem (strip compound suffix)
    stem = path.name
    for suffix in _CHILD_SF_TYPES:
        if stem.endswith(suffix):
            stem = stem[: -(len(suffix) + 1)]  # +1 for the dot
            break
    else:
        stem = path.stem

    sf_type = _child_sf_type(path)
    child_nid = make_sf_id(sf_type.lower(), obj_name, stem)
    obj_nid = object_id(obj_name)

    nodes: list[dict] = [
        {
            "id": child_nid,
            "label": f"{obj_name}: {stem}",
            "sf_type": sf_type,
            "file_type": "object",
            "source_file": str_path,
            "source_location": None,
        }
    ]
    edges: list[dict] = [
        _make_edge(obj_nid, child_nid, "contains", "EXTRACTED", str_path),
    ]

    # For ValidationRules: extract field references from the formula expression.
    # These are INFERRED edges because regex-based formula parsing is imprecise.
    if sf_type == "ValidationRule":
        try:
            tree = ET.parse(str_path)
            root_el = tree.getroot()
            ns = _get_ns(root_el)
            formula = _find_text(root_el, "errorConditionFormula", ns) or ""
            if formula:
                seen_fields: set[str] = set()
                # Custom fields on the same object: e.g. Amount__c, Status__r
                for m in _VR_CUSTOM_FIELD_RE.finditer(formula):
                    fname = m.group(1)
                    fid = field_id(obj_name, fname)
                    if fid not in seen_fields:
                        seen_fields.add(fid)
                        edges.append(
                            _make_edge(
                                child_nid,
                                fid,
                                "references",
                                "INFERRED",
                                str_path,
                                weight=0.7,
                            )
                        )
                # Cross-object custom field references: e.g. Account__r.Name__c
                for m in _VR_CROSS_OBJECT_RE.finditer(formula):
                    cross_obj, cross_field = m.group(1), m.group(2)
                    cross_fid = field_id(cross_obj, cross_field)
                    if cross_fid not in seen_fields:
                        seen_fields.add(cross_fid)
                        edges.append(
                            _make_edge(
                                child_nid,
                                cross_fid,
                                "references",
                                "INFERRED",
                                str_path,
                                weight=0.7,
                            )
                        )
                # C4: Standard field references — identifiers in comparison context or
                # as first arg of field-inspection functions. Weight 0.5 (lower than
                # custom fields) because standard-field regex has higher noise risk.
                # Dangling targets (no field node in the graph) are kept as-is; the
                # cross-ref pass leaves INFERRED edges alone regardless of target existence.
                for pat in (_VR_STD_FIELD_CMP_RE, _VR_STD_FIELD_FUNC_RE):
                    for m in pat.finditer(formula):
                        fname = m.group(1)
                        if fname.upper() in _VR_FORMULA_FUNCTIONS:
                            continue
                        if fname.endswith(("__c", "__r", "__x", "__e")):
                            continue  # custom / event types — handled by other patterns
                        fid = field_id(obj_name, fname)
                        if fid not in seen_fields:
                            seen_fields.add(fid)
                            edges.append(
                                _make_edge(
                                    child_nid,
                                    fid,
                                    "references",
                                    "INFERRED",
                                    str_path,
                                    weight=0.5,
                                )
                            )
        except (ET.ParseError, OSError):
            pass

    return {"nodes": nodes, "edges": edges}
