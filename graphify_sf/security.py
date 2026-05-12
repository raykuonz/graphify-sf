from __future__ import annotations

import re
from pathlib import Path

# Compiled control-character pattern (matches \x00-\x1f and DEL \x7f)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_label(label: str) -> str:
    """Strip control characters and cap length to 256 chars."""
    if not label:
        return ""
    label = _CONTROL_CHAR_RE.sub("", str(label))
    return label[:256]


def validate_graph_path(
    path: str | Path,
    out_dir: str | Path | None = None,
) -> Path:
    """Resolve and validate a graph.json path.

    If *out_dir* is given, the resolved path must stay within it —
    this prevents path-traversal attacks via ``--graph`` arguments.

    Returns the resolved :class:`~pathlib.Path` on success.
    Raises :class:`ValueError` for invalid or unsafe paths.
    """
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise ValueError(f"Graph file not found: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"Not a file: {resolved}")
    if out_dir is not None:
        out_resolved = Path(out_dir).resolve()
        try:
            resolved.relative_to(out_resolved)
        except ValueError:
            raise ValueError(
                f"Graph path {resolved} is outside the expected output directory "
                f"{out_resolved}. Use --out to specify the correct directory."
            )
    return resolved
