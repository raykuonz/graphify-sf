"""Extraction output schema validation for graphify-sf.

Call ``validate_extraction(data)`` after each extractor run to catch
structural problems (missing required fields, invalid enum values, dangling
edge references) before they propagate into graph assembly.
"""

from __future__ import annotations

_VALID_FILE_TYPES = frozenset(
    {
        "apex",
        "trigger",
        "flow",
        "object",
        "field",
        "validation_rule",
        "record_type",
        "layout",
        "lwc",
        "aura",
        "profile",
        "permission_set",
        "custom_label",
        "named_credential",
        "external_service",
        "unknown",
    }
)

_VALID_CONFIDENCES = frozenset({"EXTRACTED", "INFERRED", "AMBIGUOUS"})


def validate_extraction(data: dict) -> list[str]:
    """Validate extraction JSON structure.

    Args:
        data: Dict with ``"nodes"`` and ``"edges"`` lists as returned by
              :mod:`graphify_sf.extract`.

    Returns:
        A list of human-readable error strings.  An empty list means the
        data is structurally valid.
    """
    errors: list[str] = []
    nodes: list[dict] = data.get("nodes", [])
    edges: list[dict] = data.get("edges", [])

    node_ids: set[str] = set()

    for i, node in enumerate(nodes):
        nid = node.get("id")
        if not nid:
            errors.append(f"node[{i}] missing required field 'id'")
        else:
            node_ids.add(str(nid))

        if not node.get("label"):
            errors.append(f"node[{i}] (id={nid!r}) missing required field 'label'")

        file_type = node.get("file_type", "")
        if file_type and file_type not in _VALID_FILE_TYPES:
            errors.append(
                f"node[{i}] (id={nid!r}) invalid file_type: {file_type!r}. Valid types: {sorted(_VALID_FILE_TYPES)}"
            )

        confidence = node.get("confidence")
        if confidence and confidence not in _VALID_CONFIDENCES:
            errors.append(
                f"node[{i}] (id={nid!r}) invalid confidence: {confidence!r}. Valid values: {sorted(_VALID_CONFIDENCES)}"
            )

    for i, edge in enumerate(edges):
        src = str(edge.get("source", "") or "")
        tgt = str(edge.get("target", "") or "")

        if not src:
            errors.append(f"edge[{i}] missing 'source'")
        elif src not in node_ids:
            errors.append(f"edge[{i}] dangling source reference: {src!r} (no matching node id)")

        if not tgt:
            errors.append(f"edge[{i}] missing 'target'")
        elif tgt not in node_ids:
            errors.append(f"edge[{i}] dangling target reference: {tgt!r} (no matching node id)")

        confidence = edge.get("confidence")
        if confidence and confidence not in _VALID_CONFIDENCES:
            errors.append(f"edge[{i}] invalid confidence: {confidence!r}. Valid values: {sorted(_VALID_CONFIDENCES)}")

    return errors
