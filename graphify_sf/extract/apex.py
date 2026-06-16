"""Apex class and trigger extractor — regex-based (no tree-sitter needed)."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from ._ids import apex_class_id, apex_method_id, flow_id, make_sf_id, object_id, trigger_id

# ---------------------------------------------------------------------------
# Apex regex patterns
# ---------------------------------------------------------------------------
_CLASS_RE = re.compile(
    r"(?:public|private|global|protected)\s+"
    r"(?:(?:virtual|abstract|with\s+sharing|without\s+sharing|inherited\s+sharing)\s+)*"
    r"(class|interface|enum)\s+(\w+)"
    r"(?:\s+extends\s+(\w+))?"
    r"(?:\s+implements\s+([\w\s,<>]+?))?"
    r"\s*(?:\{|$)",
    re.IGNORECASE | re.MULTILINE,
)

_METHOD_RE = re.compile(
    r"(?:(?:public|private|protected|global|webservice|override|virtual|abstract|static|testMethod)\s+){1,6}"
    r"(?:[\w<>\[\]]+\s+)+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{",
    re.MULTILINE,
)

_SOQL_RE = re.compile(
    r"\[\s*SELECT\s.{1,2000}?\sFROM\s+(\w+)",
    re.IGNORECASE | re.DOTALL,
)

_DML_RE = re.compile(
    r"\b(insert|update|delete|upsert|merge|undelete)\s+(\w+)\s*;",
    re.IGNORECASE,
)

_CALL_RE = re.compile(r"(\w+)\.(\w+)\s*\(")

_TRIGGER_RE = re.compile(
    r"trigger\s+(\w+)\s+on\s+(\w+)\s*\(([^)]+)\)",
    re.IGNORECASE,
)

# Apex → Flow: Flow.Interview.FlowApiName
_FLOW_INVOKE_RE = re.compile(r"Flow\.Interview\.(\w+)", re.IGNORECASE)

# A1: HTTP callout detection — endpoint literal in setEndpoint('...')
_ENDPOINT_RE = re.compile(r'\.setEndpoint\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE)

# A5: EventBus.publish(new SomeEvent__e(...)) — extract the platform event type name
_EVENT_BUS_PUBLISH_RE = re.compile(r"EventBus\.publish\s*\(\s*new\s+(\w+__e)\s*\(", re.IGNORECASE)

# A6: Custom Metadata type access: SomeType__mdt.getInstance(...)
_CUSTOM_MDT_ACCESS_RE = re.compile(r"\b(\w+__mdt)\s*\.\s*getInstance\s*\(", re.IGNORECASE)

# A6: Custom Settings access: SomeType__c.getInstance(...) or .getOrgDefaults(...)
_CUSTOM_SETTING_ACCESS_RE = re.compile(r"\b(\w+__c)\s*\.\s*(?:getInstance|getOrgDefaults)\s*\(", re.IGNORECASE)

# Variable declaration patterns used to resolve DML operands to their declared SObject type.
# Simple: TypeName varName [= ...] ; or TypeName varName , or TypeName varName )
_VAR_DECL_SIMPLE_RE = re.compile(
    r"\b([A-Z]\w*)\s+([a-z]\w*)\s*(?=[=;,)])",
    re.MULTILINE,
)
# Generic: List<T>/Set<T>/Map<K,V> varName [= ...] ; or , or )
_VAR_DECL_GENERIC_RE = re.compile(
    r"\b(?:List|Set|Map)\s*<([^>]+)>\s+([a-z]\w*)\s*(?=[=;,)])",
    re.IGNORECASE | re.MULTILINE,
)

# Apex keywords that look like calls but aren't class references
_APEX_KEYWORDS = frozenset(
    {
        "system",
        "string",
        "integer",
        "decimal",
        "double",
        "long",
        "boolean",
        "date",
        "datetime",
        "time",
        "blob",
        "id",
        "list",
        "set",
        "map",
        "object",
        "sobject",
        "database",
        "schema",
        "limits",
        "math",
        "json",
        "jsonparser",
        "trigger",
        "test",
        "apexpage",
        "pagereference",
        "httpresponse",
        "httprequest",
        "http",
        "restcontext",
        "restrequest",
        "restresponse",
        "userinfo",
        # Common test/assert helpers and standard Apex built-ins
        "assert",
        "system.assert",
        "type",
        "exception",
        "error",
        "results",
        "result",
        "response",
        "request",
        "event",
        "message",
        "record",
        "records",
        "field",
        "value",
        "values",
        "entry",
        "context",
        "iterator",
        "comparable",
        "runnable",
        "callable",
        "queueable",
        "batchable",
        "schedulable",
        "invocable",
        "label",
        # SOSL/SOQL built-ins
        "search",
        "query",
        "querylocator",
        # Messaging & email
        "messaging",
        "approval",
        "process",
        # Additional Apex system namespaces
        "dom",
        "crypto",
        "encodingutil",
        "url",
        "uri",
        "site",
        "network",
        "cookie",
        "standardcontroller",
        "standardsetcontroller",
        "componentcontroller",
    }
)


def _extract_var_types(text: str) -> dict[str, str]:
    """Return a varName → declared SObject type map from class source text.

    Handles simple declarations (TypeName var), generic collections
    (List<T>/Set<T>/Map<K,V> var), and method parameters.
    Variable names must start with a lowercase letter; types must be PascalCase
    and not be an Apex keyword/primitive.
    """
    result: dict[str, str] = {}
    # Generic declarations first (higher priority, e.g. List<Account> accs)
    for m in _VAR_DECL_GENERIC_RE.finditer(text):
        inner = m.group(1)
        var_name = m.group(2)
        parts = [p.strip() for p in inner.split(",")]
        # For Map<K, V> take the last type arg; strip any nested generics
        inner_type = re.sub(r"<[^>]*>", "", parts[-1]).strip()
        if inner_type and inner_type[0].isupper() and inner_type.lower() not in _APEX_KEYWORDS:
            result.setdefault(var_name, inner_type)
    # Simple declarations: TypeName varName
    for m in _VAR_DECL_SIMPLE_RE.finditer(text):
        type_name = m.group(1)
        var_name = m.group(2)
        if type_name.lower() not in _APEX_KEYWORDS:
            result.setdefault(var_name, type_name)
    return result


# Minimum length and shape heuristics for a plausible Apex class name in _raw_calls.
# Returns False for things like single-letter variables, all-caps constants,
# or names that look like local variables rather than class references.
_SINGLE_LETTER = re.compile(r"^[A-Za-z]$")
_ALL_CAPS = re.compile(r"^[A-Z][A-Z0-9_]+$")  # e.g. MAX_SIZE, TRUE


def _looks_like_apex_class(name: str) -> bool:
    """Heuristic: return True only if *name* plausibly refers to an Apex class.

    Rejects:
    - Single-character identifiers (loop vars, etc.)
    - All-uppercase identifiers (constants, enums accessed as Class.CONSTANT)
    - Names starting with a lowercase letter (local variables / primitive types)
    - Names shorter than 3 chars
    - Names in the extended keyword set
    """
    if not name or len(name) < 2:
        return False
    if name.lower() in _APEX_KEYWORDS:
        return False
    # Must start with uppercase (Apex class naming convention: PascalCase)
    if not name[0].isupper():
        return False
    # Single-letter check (already covered by len < 2, but explicit)
    if _SINGLE_LETTER.match(name):
        return False
    # All-caps constants (e.g. TRUE, FALSE, NULL, MAX_SIZE) are not class calls
    if _ALL_CAPS.match(name) and len(name) <= 10:
        return False
    return True


def _make_edge(
    src: str,
    tgt: str,
    relation: str,
    confidence: str,
    source_file: str,
    weight: float = 1.0,
    confidence_score: float | None = None,
) -> dict:
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

        nodes.append(
            {
                "id": class_nid,
                "label": class_name,
                "sf_type": sf_type,
                "file_type": "apex",
                "source_file": str_path,
                "source_location": None,
            }
        )

        # Superclass edge
        if superclass and superclass.lower() not in _APEX_KEYWORDS:
            edges.append(
                _make_edge(
                    class_nid,
                    apex_class_id(superclass),
                    "extends",
                    "INFERRED",
                    str_path,
                    confidence_score=0.9,
                )
            )

        # Interface edges
        if interfaces_raw:
            for iface in re.split(r",\s*", interfaces_raw):
                iface = iface.strip()
                if iface and iface.lower() not in _APEX_KEYWORDS:
                    edges.append(
                        _make_edge(
                            class_nid,
                            apex_class_id(iface),
                            "implements",
                            "INFERRED",
                            str_path,
                            confidence_score=0.9,
                        )
                    )

        # Method extraction
        raw_calls: list[dict] = []
        for mm in _METHOD_RE.finditer(text):
            method_name = mm.group(1)
            if method_name.lower() in _APEX_KEYWORDS:
                continue
            method_nid = apex_method_id(class_name, method_name)
            line_no = text[: mm.start()].count("\n") + 1
            nodes.append(
                {
                    "id": method_nid,
                    "label": f"{class_name}.{method_name}()",
                    "sf_type": "ApexMethod",
                    "file_type": "apex",
                    "source_file": str_path,
                    "source_location": f"L{line_no}",
                }
            )
            edges.append(
                _make_edge(
                    class_nid,
                    method_nid,
                    "contains",
                    "EXTRACTED",
                    str_path,
                )
            )

            # Collect method calls within this method for cross-file resolution
            # (Find the method body: from { to matching })
            start = mm.end() - 1  # position of {
            for cm in _CALL_RE.finditer(text, start):
                callee_class = cm.group(1)
                callee_method = cm.group(2)
                if _looks_like_apex_class(callee_class):
                    raw_calls.append(
                        {
                            "caller_id": method_nid,
                            "callee_class": callee_class,
                            "callee_method": callee_method,
                        }
                    )

        # SOQL → queries edges
        seen_soql_targets: set[str] = set()
        for sm in _SOQL_RE.finditer(text):
            obj_name = sm.group(1)
            if obj_name.lower() not in _APEX_KEYWORDS and obj_name not in seen_soql_targets:
                seen_soql_targets.add(obj_name)
                edges.append(
                    _make_edge(
                        class_nid,
                        object_id(obj_name),
                        "queries",
                        "EXTRACTED",
                        str_path,
                    )
                )

        # DML → dml edges. Each edge carries an "operation" field (insert→create, etc.).
        # Resolution order for the DML operand:
        #   (a) look up the varName→Type map built by _extract_var_types;
        #   (b) if the operand is already PascalCase and not a keyword, use it directly
        #       (backward-compat: handles `insert Account;` style);
        #   (c) otherwise skip — no edge for unresolvable variables (honesty).
        # Dedup by (resolved_type, operation) so insert+update on the same object → two edges.
        _DML_VERB_TO_OP = {
            "insert": "create",
            "update": "update",
            "delete": "delete",
            "upsert": "upsert",
            "merge": "merge",
            "undelete": "undelete",
        }
        var_types = _extract_var_types(text)
        seen_dml_ops: set[tuple[str, str]] = set()
        for dm in _DML_RE.finditer(text):
            operation = _DML_VERB_TO_OP[dm.group(1).lower()]
            obj_var = dm.group(2)
            if obj_var.lower() in _APEX_KEYWORDS:
                continue
            resolved_type = var_types.get(obj_var)
            if resolved_type is None:
                # Fallback: operand is itself PascalCase — treat as the type name
                if obj_var[0].isupper():
                    resolved_type = obj_var
                else:
                    continue  # lowercase variable with no declaration — skip
            if resolved_type.lower() in _APEX_KEYWORDS:
                continue  # primitive or system type — not a DML-able SObject
            key = (resolved_type, operation)
            if key not in seen_dml_ops:
                seen_dml_ops.add(key)
                edge = _make_edge(
                    class_nid,
                    object_id(resolved_type),
                    "dml",
                    "INFERRED",
                    str_path,
                    confidence_score=0.7,
                )
                edge["operation"] = operation
                edges.append(edge)

        # Apex → Flow invocations via Flow.Interview.FlowName
        seen_flow_invokes: set[str] = set()
        for fm in _FLOW_INVOKE_RE.finditer(text):
            flow_name = fm.group(1)
            if flow_name not in seen_flow_invokes:
                seen_flow_invokes.add(flow_name)
                edges.append(
                    _make_edge(
                        class_nid,
                        flow_id(flow_name),
                        "invokes",
                        "EXTRACTED",
                        str_path,
                    )
                )

        # A1: HTTP callout detection via .setEndpoint('...')
        seen_callout_targets: set[str] = set()
        for em in _ENDPOINT_RE.finditer(text):
            endpoint = em.group(1).strip()
            nc_match = re.match(r"callout:([^/]+)", endpoint, re.IGNORECASE)
            if nc_match:
                nc_name = nc_match.group(1).strip()
                tgt_id = make_sf_id("namedcredential", nc_name)
                if tgt_id not in seen_callout_targets:
                    seen_callout_targets.add(tgt_id)
                    edges.append(_make_edge(class_nid, tgt_id, "makes_callout", "EXTRACTED", str_path))
            elif endpoint.startswith(("http://", "https://")):
                try:
                    host = urlparse(endpoint).hostname or endpoint
                except Exception:
                    host = endpoint
                tgt_id = make_sf_id("externalendpoint", host)
                if tgt_id not in seen_callout_targets:
                    seen_callout_targets.add(tgt_id)
                    # Create ExternalEndpoint node inline
                    nodes.append(
                        {
                            "id": tgt_id,
                            "label": host,
                            "sf_type": "ExternalEndpoint",
                            "file_type": "apex",
                            "source_file": str_path,
                            "source_location": None,
                            "confidence": "INFERRED",
                        }
                    )
                    edges.append(_make_edge(class_nid, tgt_id, "makes_callout", "INFERRED", str_path))

        # A5: EventBus.publish(new X__e(...)) → publishes edge
        seen_publishes: set[str] = set()
        for pm in _EVENT_BUS_PUBLISH_RE.finditer(text):
            event_name = pm.group(1)
            tgt_id = object_id(event_name)
            if tgt_id not in seen_publishes:
                seen_publishes.add(tgt_id)
                edges.append(_make_edge(class_nid, tgt_id, "publishes", "EXTRACTED", str_path))

        # A6: Custom Metadata / Custom Settings config reads (INFERRED — by-type fetch)
        seen_config_reads: set[str] = set()
        for cm in _CUSTOM_MDT_ACCESS_RE.finditer(text):
            mdt_type = cm.group(1)
            tgt_id = make_sf_id("custommetadata", mdt_type)
            if tgt_id not in seen_config_reads:
                seen_config_reads.add(tgt_id)
                edges.append(_make_edge(class_nid, tgt_id, "reads_config", "INFERRED", str_path))
        for cm in _CUSTOM_SETTING_ACCESS_RE.finditer(text):
            cs_type = cm.group(1)
            tgt_id = object_id(cs_type)
            if tgt_id not in seen_config_reads:
                seen_config_reads.add(tgt_id)
                edges.append(_make_edge(class_nid, tgt_id, "reads_config", "INFERRED", str_path))

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
        nodes.append(
            {
                "id": trigger_nid,
                "label": trigger_name,
                "sf_type": "ApexTrigger",
                "file_type": "apex",
                "source_file": str_path,
                "source_location": None,
            }
        )
        return {"nodes": nodes, "edges": edges}

    trigger_name = m.group(1)
    obj_name = m.group(2)
    events = m.group(3)

    trigger_nid = trigger_id(trigger_name)
    nodes.append(
        {
            "id": trigger_nid,
            "label": trigger_name,
            "sf_type": "ApexTrigger",
            "file_type": "apex",
            "source_file": str_path,
            "source_location": "L1",
            "trigger_events": events.strip(),
        }
    )

    # triggers edge to the object
    edges.append(
        _make_edge(
            trigger_nid,
            object_id(obj_name),
            "triggers",
            "EXTRACTED",
            str_path,
        )
    )

    # A5: trigger on a Platform Event (__e) → subscribes edge
    if obj_name.lower().endswith("__e"):
        edges.append(
            _make_edge(
                trigger_nid,
                object_id(obj_name),
                "subscribes",
                "EXTRACTED",
                str_path,
            )
        )

    # Collect raw calls for cross-file resolution
    raw_calls: list[dict] = []
    for cm in _CALL_RE.finditer(text, m.end()):
        callee_class = cm.group(1)
        callee_method = cm.group(2)
        if _looks_like_apex_class(callee_class):
            raw_calls.append(
                {
                    "caller_id": trigger_nid,
                    "callee_class": callee_class,
                    "callee_method": callee_method,
                }
            )

    if raw_calls:
        nodes[0]["_raw_calls"] = raw_calls

    return {"nodes": nodes, "edges": edges}
