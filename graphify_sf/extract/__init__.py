"""Main extraction coordinator for graphify-sf.

Two-pass pipeline:
  Pass 1: per-file structural extraction (optionally parallel)
  Pass 2: cross-file reference resolution (EXTRACTED → INFERRED if target unknown)
"""

from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .agentforce import (
    extract_ai_authoring_bundle,
    extract_bot,
    extract_bot_version,
    extract_gen_ai_function,
    extract_gen_ai_planner_bundle,
    extract_gen_ai_plugin,
    extract_prompt_template,
)
from .apex import extract_apex_class, extract_apex_trigger
from .aura import extract_aura_bundle
from .automation import extract_approval_process, extract_generic_automation, extract_workflow
from .config import (
    extract_custom_labels,
    extract_custom_metadata_record,
    extract_external_service,
    extract_flexipage,
    extract_generic_config,
    extract_named_credential,
)
from .doc import extract_doc_file
from .flow import extract_flow
from .layout import extract_layout
from .lwc import extract_lwc_bundle
from .object import extract_child_object, extract_custom_field, extract_custom_object
from .profile import extract_permset, extract_profile
from .visualforce import extract_vf_component, extract_vf_page

# ---------------------------------------------------------------------------
# Compound-suffix dispatch table — longest suffix wins
# ---------------------------------------------------------------------------
_DISPATCH: dict[str, object] = {
    # Automation
    ".flow-meta.xml": extract_flow,
    ".workflow-meta.xml": extract_workflow,
    ".approvalProcess-meta.xml": extract_approval_process,
    ".escalationRules-meta.xml": extract_generic_automation,
    ".assignmentRules-meta.xml": extract_generic_automation,
    ".autoResponseRules-meta.xml": extract_generic_automation,
    # Object model
    ".object-meta.xml": extract_custom_object,
    ".field-meta.xml": extract_custom_field,
    ".validationRule-meta.xml": extract_child_object,
    ".recordType-meta.xml": extract_child_object,
    ".listView-meta.xml": extract_child_object,
    ".compactLayout-meta.xml": extract_child_object,
    # UI
    ".layout-meta.xml": extract_layout,
    ".flexipage-meta.xml": extract_flexipage,
    # Security
    ".profile-meta.xml": extract_profile,
    ".permissionset-meta.xml": extract_permset,
    ".permissionsetgroup-meta.xml": extract_permset,
    # Config
    ".labels-meta.xml": extract_custom_labels,
    ".md-meta.xml": extract_custom_metadata_record,
    ".namedCredential-meta.xml": extract_named_credential,
    ".externalService-meta.xml": extract_external_service,
    ".settings-meta.xml": extract_generic_config,
    ".connectedApp-meta.xml": extract_generic_config,
    ".app-meta.xml": extract_generic_config,
    ".tab-meta.xml": extract_generic_config,
    ".testSuite-meta.xml": extract_generic_config,
    ".remoteSite-meta.xml": extract_generic_config,
    ".role-meta.xml": extract_generic_config,
    ".site-meta.xml": extract_generic_config,
    ".network-meta.xml": extract_generic_config,
    # Agentforce
    ".bot-meta.xml": extract_bot,
    ".botVersion-meta.xml": extract_bot_version,
    ".genAiPlugin-meta.xml": extract_gen_ai_plugin,
    ".genAiFunction-meta.xml": extract_gen_ai_function,
    ".genAiPlannerBundle-meta.xml": extract_gen_ai_planner_bundle,
    ".aiAuthoringBundle-meta.xml": extract_ai_authoring_bundle,
    ".promptTemplate-meta.xml": extract_prompt_template,
    # Simple extensions
    ".cls": extract_apex_class,
    ".trigger": extract_apex_trigger,
    ".page": extract_vf_page,
    ".component": extract_vf_component,
}


def _compound_suffix(path: Path) -> str:
    """Return the longest matching compound suffix for this path."""
    suffixes = path.suffixes
    for i in range(len(suffixes), 0, -1):
        key = "".join(suffixes[-i:])
        if key in _DISPATCH:
            return key
    # Try simple suffix
    key = path.suffix
    if key in _DISPATCH:
        return key
    return ""


def _extract_file(path: Path) -> dict:
    """Dispatch to the right extractor for a single file."""
    key = _compound_suffix(Path(path))
    if key and key in _DISPATCH:
        try:
            return _DISPATCH[key](Path(path))
        except Exception as exc:
            print(f"[graphify-sf] WARNING: extraction failed for {path}: {exc}", file=sys.stderr)
            return {"nodes": [], "edges": []}
    return {"nodes": [], "edges": []}


def _resolve_cross_references(nodes: list, edges: list) -> tuple[list, list]:
    """Mark edges to unknown targets as INFERRED instead of EXTRACTED.

    Also resolves raw_calls: callee_class.method references stored in node
    metadata during Apex extraction are turned into proper edges.
    """
    known_ids: set[str] = {n["id"] for n in nodes}

    # Process raw_calls from Apex nodes
    additional_edges: list[dict] = []
    for node in nodes:
        raw_calls = node.pop("_raw_calls", None)
        if not raw_calls:
            continue
        for call in raw_calls:
            caller_id = call["caller_id"]
            callee_class = call["callee_class"]
            callee_method = call["callee_method"]
            from ._ids import apex_class_id, apex_method_id

            method_nid = apex_method_id(callee_class, callee_method)
            class_nid = apex_class_id(callee_class)
            source_file = node.get("source_file", "")
            if method_nid in known_ids:
                confidence, score = "EXTRACTED", 1.0
                target = method_nid
            elif class_nid in known_ids:
                confidence, score = "INFERRED", 0.75
                target = class_nid
            else:
                confidence, score = "INFERRED", 0.5
                target = class_nid
            additional_edges.append(
                {
                    "source": caller_id,
                    "target": target,
                    "relation": "calls",
                    "confidence": confidence,
                    "confidence_score": score,
                    "source_file": source_file,
                    "source_location": None,
                    "weight": 1.0,
                    "_src": caller_id,
                    "_tgt": target,
                }
            )

    # Build a label→id lookup for SF mention resolution from doc nodes
    label_to_ids: dict[str, list[str]] = {}
    for n in nodes:
        lbl = n.get("label", "")
        if lbl:
            label_to_ids.setdefault(lbl, []).append(n["id"])
        # Also index by stem without extension
        stem = lbl.rsplit(".", 1)[0] if "." in lbl else lbl
        if stem and stem != lbl:
            label_to_ids.setdefault(stem, []).append(n["id"])

    # Resolve __mention__ placeholder targets
    resolved_mention_edges: list[dict] = []
    for edge in edges:
        tgt = edge.get("target", "")
        if tgt.startswith("__mention__"):
            mention_label = edge.get("_mention_label", tgt[len("__mention__") :])
            real_targets = label_to_ids.get(mention_label, [])
            if real_targets:
                for real_id in real_targets[:1]:  # take first match
                    new_edge = {k: v for k, v in edge.items() if k != "_mention_label"}
                    new_edge["target"] = real_id
                    new_edge["_tgt"] = real_id
                    resolved_mention_edges.append(new_edge)
            # If no match found, drop the placeholder edge (unknown SF component)
        else:
            resolved_mention_edges.append(edge)
    edges = resolved_mention_edges

    # Downgrade EXTRACTED edges pointing to unknown nodes → INFERRED
    resolved_edges: list[dict] = []
    for edge in edges + additional_edges:
        tgt = edge.get("target", "")
        if tgt not in known_ids and edge.get("confidence") == "EXTRACTED":
            new_edge = dict(edge)
            new_edge["confidence"] = "INFERRED"
            if not new_edge.get("confidence_score"):
                new_edge["confidence_score"] = 0.7
            resolved_edges.append(new_edge)
        else:
            resolved_edges.append(edge)

    return nodes, resolved_edges


def extract(
    detect_result: dict,
    *,
    parallel: bool = True,
    max_workers: int | None = None,
) -> dict:
    """Two-pass extraction from a detect() result dict.

    Pass 1: Per-file extraction (parallel if enough files).
    Pass 1b: Bundle (LWC/Aura) extraction.
    Pass 2: Cross-file reference resolution.

    Returns:
        {nodes: list, edges: list, input_tokens: int, output_tokens: int}
    """
    all_nodes: list[dict] = []
    all_edges: list[dict] = []

    # Collect all single-file paths (SF metadata)
    single_files: list[Path] = []
    for file_list in detect_result.get("files", {}).values():
        single_files.extend(Path(f) for f in file_list)

    # Collect doc files (markdown, PDF, images, xlsx sidecars)
    doc_file_paths: list[Path] = []
    for file_list in detect_result.get("doc_files", {}).values():
        doc_file_paths.extend(Path(f) for f in file_list)

    lwc_dirs = [Path(d) for d in detect_result.get("bundle_dirs", {}).get("lwc", [])]
    aura_dirs = [Path(d) for d in detect_result.get("bundle_dirs", {}).get("aura", [])]

    # Phase 1: Extract single files
    use_parallel = parallel and len(single_files) > 8
    if use_parallel:
        try:
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_extract_file, p): p for p in single_files}
                for fut in as_completed(futures):
                    try:
                        result = fut.result()
                        all_nodes.extend(result.get("nodes", []))
                        all_edges.extend(result.get("edges", []))
                    except Exception as exc:
                        p = futures[fut]
                        print(f"[graphify-sf] WARNING: {p}: {exc}", file=sys.stderr)
        except Exception:
            # Fall back to sequential if parallel fails (e.g. on Windows)
            # Clear any partial results from completed futures to prevent duplicates
            all_nodes.clear()
            all_edges.clear()
            use_parallel = False

    if not use_parallel:
        for p in single_files:
            result = _extract_file(p)
            all_nodes.extend(result.get("nodes", []))
            all_edges.extend(result.get("edges", []))

    # Phase 1b: Bundle extraction (always sequential — they're directory-level)
    for bundle_dir in lwc_dirs:
        try:
            result = extract_lwc_bundle(bundle_dir)
            all_nodes.extend(result.get("nodes", []))
            all_edges.extend(result.get("edges", []))
        except Exception as exc:
            print(f"[graphify-sf] WARNING: LWC bundle {bundle_dir}: {exc}", file=sys.stderr)

    for bundle_dir in aura_dirs:
        try:
            result = extract_aura_bundle(bundle_dir)
            all_nodes.extend(result.get("nodes", []))
            all_edges.extend(result.get("edges", []))
        except Exception as exc:
            print(f"[graphify-sf] WARNING: Aura bundle {bundle_dir}: {exc}", file=sys.stderr)

    # Phase 1c: Extract doc files (sequential — usually few and lightweight)
    for p in doc_file_paths:
        try:
            result = extract_doc_file(p)
            all_nodes.extend(result.get("nodes", []))
            all_edges.extend(result.get("edges", []))
        except Exception as exc:
            print(f"[graphify-sf] WARNING: doc extraction failed for {p}: {exc}", file=sys.stderr)

    # Phase 2: Cross-file resolution
    all_nodes, all_edges = _resolve_cross_references(all_nodes, all_edges)

    return {
        "nodes": all_nodes,
        "edges": all_edges,
        "input_tokens": 0,
        "output_tokens": 0,
    }
