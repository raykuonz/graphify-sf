"""Per-file extraction cache for graphify-sf.

Caches extraction results by file hash so unchanged files are not
re-parsed on incremental runs.

Cache layout::

    {out_dir}/cache/{file_type}/{hash[:2]}/{hash}.json

The two-character prefix shards the cache to avoid oversized directories
on filesystems with slow per-directory listing (e.g. FAT32, some NFS mounts).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# Increment when the cached JSON schema changes in a backwards-incompatible way.
# All entries with a different version are treated as stale and re-extracted.
_CACHE_VERSION = 1


def file_hash(path: str | Path, relative_to: str | Path | None = None) -> str:
    """Return the SHA-256 hex digest of *path*'s contents.

    When *relative_to* is provided the relative path string is mixed into the
    hash so that identical files placed under different project roots produce
    different cache keys (prevents cross-project cache collisions).
    """
    p = Path(path)
    data = p.read_bytes()
    if relative_to is not None:
        try:
            rel = str(p.relative_to(relative_to))
        except ValueError:
            rel = str(p)
        data = data + b"\x00" + rel.encode()
    return hashlib.sha256(data).hexdigest()


def _cache_path(out_dir: Path, file_type: str, hash_str: str) -> Path:
    """Return the cache file path for a given file_type + hash."""
    return out_dir / "cache" / file_type / hash_str[:2] / f"{hash_str}.json"


def load_cached(out_dir: Path, file_type: str, hash_str: str) -> dict | None:
    """Load a cached extraction result.

    Returns the deserialized dict on a cache hit, or ``None`` if the entry
    is missing, unreadable, or from an older cache version.
    """
    p = _cache_path(out_dir, file_type, hash_str)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("_cache_version") != _CACHE_VERSION:
            return None
        return data
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def save_cached(out_dir: Path, file_type: str, hash_str: str, result: dict) -> None:
    """Write an extraction result to the cache atomically.

    Uses a temp-file + :func:`os.replace` to avoid partial writes visible to
    concurrent readers.
    """
    p = _cache_path(out_dir, file_type, hash_str)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(result)
    payload["_cache_version"] = _CACHE_VERSION
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def clear_cache(out_dir: Path) -> int:
    """Delete all cache entries under *out_dir*/cache/.

    Returns the number of files deleted.
    """
    cache_dir = out_dir / "cache"
    if not cache_dir.exists():
        return 0
    count = 0
    for f in cache_dir.rglob("*.json"):
        try:
            f.unlink()
            count += 1
        except OSError:
            pass
    # Clean up empty shard directories
    for d in sorted(cache_dir.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()  # only removes if empty
            except OSError:
                pass
    return count


def cached_files(out_dir: Path) -> list[Path]:
    """Return a list of all cache entry paths under *out_dir*/cache/."""
    cache_dir = out_dir / "cache"
    if not cache_dir.exists():
        return []
    return sorted(cache_dir.rglob("*.json"))
