"""LWC bundle extractor."""

from __future__ import annotations

import re
from pathlib import Path

from ._ids import apex_class_id, lwc_id, make_sf_id

_IMPORT_RE = re.compile(r"""import\s+(?:\{[^}]+\}|\w+)\s+from\s+['"]([^'"]+)['"]""")
_CLASS_RE = re.compile(r"export\s+default\s+class\s+(\w+)\s+extends\s+(\w+)", re.IGNORECASE)
_WIRE_RE = re.compile(r"@wire\(\s*(\w+)")
_APEX_IMPORT_RE = re.compile(r"@salesforce/apex/([\w.]+)")
_CHILD_TAG_RE = re.compile(r"<(c-[\w-]+|lightning-[\w-]+)")
_METHOD_RE = re.compile(r"^\s{4}(\w+)\s*\([^)]*\)\s*\{", re.MULTILINE)

_LWC_KEYWORDS = frozenset({"LightningElement", "NavigationMixin", "Wire", "api", "wire", "track"})


def _kebab_to_camel(name: str) -> str:
    """Convert kebab-case to camelCase."""
    parts = name.split("-")
    if not parts:
        return name
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


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


def extract_lwc_bundle(bundle_dir: Path) -> dict:
    """Extract nodes and edges from an LWC bundle directory."""
    bundle_dir = Path(bundle_dir)
    name = bundle_dir.name
    nid = lwc_id(name)
    str_dir = str(bundle_dir / f"{name}.js")

    nodes: list[dict] = [
        {
            "id": nid,
            "label": name,
            "sf_type": "LWCComponent",
            "file_type": "lwc",
            "source_file": str_dir,
            "source_location": None,
        }
    ]
    edges: list[dict] = []
    seen_targets: set[str] = set()

    def add_edge(tgt: str, relation: str, confidence: str, weight: float = 1.0) -> None:
        key = f"{relation}:{tgt}"
        if key not in seen_targets:
            seen_targets.add(key)
            edges.append(_make_edge(nid, tgt, relation, confidence, str_dir, weight))

    js_file = bundle_dir / f"{name}.js"
    if js_file.exists():
        try:
            text = js_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""

        # Process imports
        for m in _IMPORT_RE.finditer(text):
            module = m.group(1)

            # @salesforce/apex/ClassName.methodName
            apex_m = _APEX_IMPORT_RE.match(module)
            if apex_m:
                apex_qualified = apex_m.group(1)  # e.g. "AccountService.findByName"
                class_name = apex_qualified.split(".")[0]
                add_edge(apex_class_id(class_name), "calls", "EXTRACTED")
                continue

            # c/componentName (camelCase) → another LWC
            if module.startswith("c/"):
                child_name = module[2:]
                add_edge(lwc_id(child_name), "calls", "EXTRACTED")
                continue

        # @wire adapters
        for m in _WIRE_RE.finditer(text):
            adapter = m.group(1)
            if adapter not in _LWC_KEYWORDS:
                add_edge(make_sf_id("wireadapter", adapter), "uses", "INFERRED", 0.5)

        # Method nodes
        for m in _METHOD_RE.finditer(text):
            method_name = m.group(1)
            if method_name in ("constructor",) or method_name[0] in ("_",):
                continue
            method_nid = make_sf_id("lwcmethod", name, method_name)
            nodes.append(
                {
                    "id": method_nid,
                    "label": f"{name}.{method_name}()",
                    "sf_type": "LWCMethod",
                    "file_type": "lwc",
                    "source_file": str_dir,
                    "source_location": None,
                }
            )
            edges.append(_make_edge(nid, method_nid, "contains", "EXTRACTED", str_dir))

    html_file = bundle_dir / f"{name}.html"
    if html_file.exists():
        try:
            html_text = html_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            html_text = ""

        for m in _CHILD_TAG_RE.finditer(html_text):
            tag = m.group(1)
            if tag.startswith("c-"):
                # c-account-card → accountCard
                child_kebab = tag[2:]
                child_camel = _kebab_to_camel(child_kebab)
                add_edge(lwc_id(child_camel), "uses", "EXTRACTED")
            # lightning-* are platform components — create stub nodes if not seen
            # (keep weight low since these don't produce SF metadata nodes)

    return {"nodes": nodes, "edges": edges}
