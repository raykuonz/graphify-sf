import fnmatch
import hashlib
import json
import os
from enum import Enum
from pathlib import Path


class SFFileType(str, Enum):
    APEX = "apex"
    TRIGGER = "trigger"
    FLOW = "flow"
    OBJECT = "object"
    FIELD = "field"
    CHILD_OBJECT = "child_object"
    LAYOUT = "layout"
    VISUALFORCE = "visualforce"
    LWC_BUNDLE = "lwc_bundle"
    AURA_BUNDLE = "aura_bundle"
    PROFILE = "profile"
    PERMISSIONSET = "permissionset"
    CONFIG = "config"
    AUTOMATION = "automation"
    EXPERIENCE = "experience"
    AGENTFORCE = "agentforce"


# Compound extensions MUST be checked first
_COMPOUND_EXT_MAP = {
    ".flow-meta.xml": SFFileType.FLOW,
    ".object-meta.xml": SFFileType.OBJECT,
    ".field-meta.xml": SFFileType.FIELD,
    ".validationRule-meta.xml": SFFileType.CHILD_OBJECT,
    ".recordType-meta.xml": SFFileType.CHILD_OBJECT,
    ".listView-meta.xml": SFFileType.CHILD_OBJECT,
    ".compactLayout-meta.xml": SFFileType.CHILD_OBJECT,
    ".layout-meta.xml": SFFileType.LAYOUT,
    ".profile-meta.xml": SFFileType.PROFILE,
    ".permissionset-meta.xml": SFFileType.PERMISSIONSET,
    ".permissionsetgroup-meta.xml": SFFileType.PERMISSIONSET,
    ".labels-meta.xml": SFFileType.CONFIG,
    ".md-meta.xml": SFFileType.CONFIG,
    ".settings-meta.xml": SFFileType.CONFIG,
    ".namedCredential-meta.xml": SFFileType.CONFIG,
    ".externalService-meta.xml": SFFileType.CONFIG,
    ".connectedApp-meta.xml": SFFileType.CONFIG,
    ".app-meta.xml": SFFileType.CONFIG,
    ".tab-meta.xml": SFFileType.CONFIG,
    ".flexipage-meta.xml": SFFileType.CONFIG,
    ".testSuite-meta.xml": SFFileType.CONFIG,
    ".remoteSite-meta.xml": SFFileType.CONFIG,
    ".role-meta.xml": SFFileType.CONFIG,
    ".site-meta.xml": SFFileType.EXPERIENCE,
    ".network-meta.xml": SFFileType.EXPERIENCE,
    ".workflow-meta.xml": SFFileType.AUTOMATION,
    ".approvalProcess-meta.xml": SFFileType.AUTOMATION,
    ".escalationRules-meta.xml": SFFileType.AUTOMATION,
    ".assignmentRules-meta.xml": SFFileType.AUTOMATION,
    ".autoResponseRules-meta.xml": SFFileType.AUTOMATION,
    # Agentforce
    ".bot-meta.xml": SFFileType.AGENTFORCE,
    ".botVersion-meta.xml": SFFileType.AGENTFORCE,
    ".genAiPlugin-meta.xml": SFFileType.AGENTFORCE,
    ".genAiFunction-meta.xml": SFFileType.AGENTFORCE,
    ".genAiPlannerBundle-meta.xml": SFFileType.AGENTFORCE,
    ".aiAuthoringBundle-meta.xml": SFFileType.AGENTFORCE,
    ".promptTemplate-meta.xml": SFFileType.AGENTFORCE,
}

_SIMPLE_EXT_MAP = {
    ".cls": SFFileType.APEX,
    ".trigger": SFFileType.TRIGGER,
    ".page": SFFileType.VISUALFORCE,
    ".component": SFFileType.VISUALFORCE,
}

_SKIP_DIRS = {".sfdx", "node_modules", "__pycache__", ".git", "graphify-sf-out"}


def _compound_suffix(path: Path) -> str:
    """Return the longest matching compound suffix, or the simple suffix if none match."""
    suffixes = path.suffixes
    for i in range(len(suffixes), 0, -1):
        compound = "".join(suffixes[-i:])
        if compound in _COMPOUND_EXT_MAP:
            return compound
    return path.suffix if path.suffix else ""


def _classify_file(path: Path) -> SFFileType | None:
    """Classify a single file by compound extension."""
    suffix = _compound_suffix(path)
    if suffix in _COMPOUND_EXT_MAP:
        return _COMPOUND_EXT_MAP[suffix]
    if suffix in _SIMPLE_EXT_MAP:
        return _SIMPLE_EXT_MAP[suffix]
    return None


def _is_lwc_bundle(bundle_dir: Path) -> bool:
    """Return True if this directory is an LWC bundle."""
    if not bundle_dir.is_dir():
        return False
    name = bundle_dir.name
    js_file = bundle_dir / f"{name}.js"
    return js_file.exists()


def _is_aura_bundle(bundle_dir: Path) -> bool:
    """Return True if this directory is an Aura bundle."""
    if not bundle_dir.is_dir():
        return False
    name = bundle_dir.name
    cmp_file = bundle_dir / f"{name}.cmp"
    return cmp_file.exists()


def _load_sfgraphignore(root: Path) -> list[str]:
    """Load .graphifysfignore patterns from the project root."""
    ignore_file = root / ".graphifysfignore"
    if not ignore_file.exists():
        return []
    patterns = []
    for line in ignore_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _is_ignored(path: Path, root: Path, patterns: list[str]) -> bool:
    """Return True if the path matches any ignore pattern."""
    if not patterns:
        return False
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        return False
    for pattern in patterns:
        if fnmatch.fnmatch(rel, pattern):
            return True
        if fnmatch.fnmatch(path.name, pattern):
            return True
    return False


def detect(root: Path) -> dict:
    """Scan the SFDX project and return detected files grouped by type."""
    root = root.resolve()
    files = {ft.value: [] for ft in SFFileType}
    bundle_dirs = {"lwc": [], "aura": []}
    skipped = []
    ignore_patterns = _load_sfgraphignore(root)

    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)

        # Prune skip dirs
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        # Check for LWC/Aura bundles
        if dp.parent.name == "lwc" and _is_lwc_bundle(dp):
            if not _is_ignored(dp, root, ignore_patterns):
                bundle_dirs["lwc"].append(str(dp))
            continue

        if dp.parent.name == "aura" and _is_aura_bundle(dp):
            if not _is_ignored(dp, root, ignore_patterns):
                bundle_dirs["aura"].append(str(dp))
            continue

        # Classify individual files
        for fname in filenames:
            path = dp / fname
            if _is_ignored(path, root, ignore_patterns):
                skipped.append(str(path))
                continue
            ftype = _classify_file(path)
            if ftype:
                files[ftype.value].append(str(path))

    total_files = sum(len(v) for v in files.values()) + len(bundle_dirs["lwc"]) + len(bundle_dirs["aura"])

    return {
        "files": files,
        "total_files": total_files,
        "bundle_dirs": bundle_dirs,
        "warning": None,
        "skipped": skipped,
    }


def _md5_file(path: Path) -> str:
    """MD5 hash of file content for change detection."""
    h = hashlib.md5(usedforsecurity=False)
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def load_manifest(manifest_path: str) -> dict:
    """Load the manifest from a previous run."""
    try:
        return json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_manifest(files: dict[str, list[str]], manifest_path: str) -> None:
    """Save current file mtimes + content hashes for incremental updates."""
    manifest = {}
    for file_list in files.values():
        for f in file_list:
            try:
                p = Path(f)
                manifest[f] = {"mtime": p.stat().st_mtime, "hash": _md5_file(p)}
            except OSError:
                pass
    Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
    Path(manifest_path).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def detect_incremental(root: Path, manifest_path: str) -> dict:
    """Like detect(), but returns only new or modified files since the last run."""
    full = detect(root)
    manifest = load_manifest(manifest_path)

    if not manifest:
        full["new_files"] = full["files"]
        full["unchanged_files"] = {k: [] for k in full["files"]}
        return full

    new_files = {k: [] for k in full["files"]}
    unchanged_files = {k: [] for k in full["files"]}

    for ftype, file_list in full["files"].items():
        for f in file_list:
            stored = manifest.get(f, {})
            try:
                current_mtime = Path(f).stat().st_mtime
                stored_mtime = stored.get("mtime")
                if stored_mtime is None or current_mtime != stored_mtime:
                    changed = _md5_file(Path(f)) != stored.get("hash", "")
                else:
                    changed = False
            except Exception:
                changed = True

            if changed:
                new_files[ftype].append(f)
            else:
                unchanged_files[ftype].append(f)

    full["new_files"] = new_files
    full["unchanged_files"] = unchanged_files
    return full
