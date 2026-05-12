"""Apex class and trigger extractor — regex-based (no tree-sitter needed)."""
from __future__ import annotations

import re
from pathlib import Path

from ._ids import apex_class_id, apex_method_id, object_id, trigger_id

# ---------------------------------------------------------------------------
# Apex regex patterns
# ---------------------------------------------------------------------------
_CLASS_RE = re.compile(
    r'(?:public|private|global|protected)\s+'
    r'(?:(?:virtual|abstract|with\s+sharing|without\s+sharing|inherited\s+sharing)\s+)*'
    r'(class|interface|enum)\s+(\w+)'
    r'(?:\s+extends\s+(\w+))?'
    r'(?:\s+implements\s+([\w\s,<>]+?))?'
    r'\s*(?:\{|$)',
    re.IGNORECASE | re.MULTILINE,
)

_METHOD_RE = re.compile(
    r'(?:(?:public|private|protected|global|webservice|override|virtual|abstract|static|testMethod)\s+){1,6}'
    r'(?:[\w<>\[\]]+\s+)+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{',
    re.MULTILINE,
)

_SOQL_RE = re.compile(
    r'\[\s*SELECT\s.{1,2000}?\sFROM\s+(\w+)',
    re.IGNORECASE | re.DOTALL,
)

_DML_RE = re.compile(
    r'\b(insert|update|delete|upsert|merge|undelete)\s+(\w+)\s*;',
    re.IGNORECASE,
)

_CALL_RE = re.compile(r'(\w+)\.(\w+)\s*\(')

_TRIGGER_RE = re.compile(
    r'trigger\s+(\w+)\s+on\s+(\w+)\s*\(([^)]+)\)',
    re.IGNORECASE,
)

# Apex keywords that look like calls but aren't class references
_APEX_KEYWORDS = frozenset({
    "system", "string", "integer", "decimal", "double", "long", "boolean",
    "date", "datetime", "time", "blob", "id", "list", "set", "map", "object",
    "sobject", "database", "schema", "limits", "math", "json", "jsonparser",
    "trigger", "test", "apexpage", "pagereference", "httpresponse", "httprequest",
    "http", "restcontext", "restrequest", "restresponse", "userinfo",
})


def _make_edge(src: str, tgt: str, relation: str, confidence: str,
               source_file: str, weight: float = 1.0,
               confidence_score: float | None = None) -> dict:
    edge: dict = {
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
    if confidence_score is not None:
        edge["confidence_score"] = confidence_score
    return edge


def extract_apex_class(path: Path) -> dict:
    """Extract nodes and edges from an Apex class (.cls) file."""
    str_path = str(path)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"nodes": [], "edges": []}

    nodes: list[dict] = []
    edges: list[dict] = []

    # Find the class declaration
    m = _CLASS_RE.search(text)
    if not m:
        # Fallback: try to extract class name from filename
        class_name = path.stem
    else:
        kind = m.group(1).lower()  # class / interface / enum
        class_name = m.group(2)
        superclass = (m.group(3) or "").strip()
        interfaces_raw = (m.group(4) or "").strip()

        class_nid = apex_class_id(class_name)
        sf_type = "ApexInterface" if kind == "interface" else "ApexEnum" if kind == "enum" else "ApexClass"

        nodes.append({
            "id": class_nid,
            "label": class_name,
            "sf_type": sf_type,
            "file_type": "apex",
            "source_file": str_path,
            "source_location": None,
        })

        # Superclass edge
        if superclass and superclass.lower() not in _APEX_KEYWORDS:
            edges.append(_make_edge(
                class_nid, apex_class_id(superclass),
                "extends", "INFERRED", str_path,
                confidence_score=0.9,
            ))

        # Interface edges
        if interfaces_raw:
            for iface in re.split(r",\s*", interfaces_raw):
                iface = iface.strip()
                if iface and iface.lower() not in _APEX_KEYWORDS:
                    edges.append(_make_edge(
                        class_nid, apex_class_id(iface),
                        "implements", "INFERRED", str_path,
                        confidence_score=0.9,
                    ))

        # Method extraction
        raw_calls: list[dict] = []
        for mm in _METHOD_RE.finditer(text):
            method_name = mm.group(1)
            if method_name.lower() in _APEX_KEYWORDS:
                continue
            method_nid = apex_method_id(class_name, method_name)
            line_no = text[:mm.start()].count("\n") + 1
            nodes.append({
                "id": method_nid,
                "label": f"{class_name}.{method_name}()",
                "sf_type": "ApexMethod",
                "file_type": "apex",
                "source_file": str_path,
                "source_location": f"L{line_no}",
            })
            edges.append(_make_edge(
                class_nid, method_nid, "contains", "EXTRACTED", str_path,
            ))

            # Collect method calls within this method for cross-file resolution
            # (Find the method body: from { to matching })
            start = mm.end() - 1  # position of {
            for cm in _CALL_RE.finditer(text, start):
                callee_class = cm.group(1)
                callee_method = cm.group(2)
                if callee_class.lower() not in _APEX_KEYWORDS:
                    raw_calls.append({
                        "caller_id": method_nid,
                        "callee_class": callee_class,
                        "callee_method": callee_method,
                    })

        # SOQL → queries edges
        seen_soql_targets: set[str] = set()
        for sm in _SOQL_RE.finditer(text):
            obj_name = sm.group(1)
            if obj_name.lower() not in _APEX_KEYWORDS and obj_name not in seen_soql_targets:
                seen_soql_targets.add(obj_name)
                edges.append(_make_edge(
                    class_nid, object_id(obj_name),
                    "queries", "EXTRACTED", str_path,
                ))

        # DML → dml edges
        seen_dml_targets: set[str] = set()
        for dm in _DML_RE.finditer(text):
            obj_var = dm.group(2)
            # obj_var is a variable name, not necessarily an object API name.
            # We record it as INFERRED since we can't always resolve the type statically.
            if obj_var.lower() not in _APEX_KEYWORDS and obj_var not in seen_dml_targets:
                seen_dml_targets.add(obj_var)
                # Only add the edge if it looks like a type name (capitalized) or known object
                if obj_var[0].isupper():
                    edges.append(_make_edge(
                        class_nid, object_id(obj_var),
                        "dml", "INFERRED", str_path,
                        confidence_score=0.7,
                    ))

        # Stash raw_calls in the class node for cross-file resolution
        if raw_calls and nodes:
            nodes[0]["_raw_calls"] = raw_calls

    return {"nodes": nodes, "edges": edges}


def extract_apex_trigger(path: Path) -> dict:
    """Extract nodes and edges from an Apex trigger (.trigger) file."""
    str_path = str(path)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"nodes": [], "edges": []}

    nodes: list[dict] = []
    edges: list[dict] = []

    m = _TRIGGER_RE.search(text)
    if not m:
        trigger_name = path.stem
        trigger_nid = trigger_id(trigger_name)
        nodes.append({
            "id": trigger_nid,
            "label": trigger_name,
            "sf_type": "ApexTrigger",
            "file_type": "apex",
            "source_file": str_path,
            "source_location": None,
        })
        return {"nodes": nodes, "edges": edges}

    trigger_name = m.group(1)
    obj_name = m.group(2)
    events = m.group(3)

    trigger_nid = trigger_id(trigger_name)
    nodes.append({
        "id": trigger_nid,
        "label": trigger_name,
        "sf_type": "ApexTrigger",
        "file_type": "apex",
        "source_file": str_path,
        "source_location": "L1",
        "trigger_events": events.strip(),
    })

    # triggers edge to the object
    edges.append(_make_edge(
        trigger_nid, object_id(obj_name),
        "triggers", "EXTRACTED", str_path,
    ))

    # Collect raw calls for cross-file resolution
    raw_calls: list[dict] = []
    for cm in _CALL_RE.finditer(text, m.end()):
        callee_class = cm.group(1)
        callee_method = cm.group(2)
        if callee_class.lower() not in _APEX_KEYWORDS and callee_class[0].isupper():
            raw_calls.append({
                "caller_id": trigger_nid,
                "callee_class": callee_class,
                "callee_method": callee_method,
            })

    if raw_calls:
        nodes[0]["_raw_calls"] = raw_calls

    return {"nodes": nodes, "edges": edges}
