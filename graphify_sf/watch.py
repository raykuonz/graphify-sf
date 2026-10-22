# graphify_sf/watch.py
"""File-system watcher for graphify-sf: auto-rebuild on SFDX metadata changes.

Uses watchdog when available; falls back to polling every POLL_INTERVAL seconds.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from pathlib import Path

from graphify_sf.detect import _COMPOUND_EXT_MAP, _SIMPLE_EXT_MAP
from graphify_sf.detect import _SKIP_DIRS as _DETECT_SKIP_DIRS

# Metadata file patterns that should trigger a rebuild: every suffix detect.py classifies,
# so a file type the detector understands can never be silently ignored by the watcher.
# LWC and Aura bundles are classified by directory instead (any file inside one counts).
# Reference documents (.md, .pdf, ...) deliberately don't trigger rebuilds.
_SF_EXTENSIONS = tuple(_COMPOUND_EXT_MAP) + tuple(_SIMPLE_EXT_MAP)
_BUNDLE_PARENTS = frozenset({"lwc", "aura"})

# watchdog also reports opened/closed events on some platforms; a rebuild opens every
# watched file, so reacting to those would retrigger it forever.
_CHANGE_EVENTS = frozenset({"created", "modified", "deleted", "moved"})

# The detector's skip list, plus the sf CLI's state directory.
_SKIP_DIRS = frozenset(_DETECT_SKIP_DIRS) | {".sf"}


def _is_sf_file(path: str) -> bool:
    if not path:
        return False
    if path.endswith(_SF_EXTENSIONS):
        return True
    # <...>/lwc/<bundle>/<file> or <...>/aura/<bundle>/<file>
    parts = Path(path).parts
    return len(parts) >= 3 and parts[-3] in _BUNDLE_PARENTS


def _in_skipped_dir(path: str, root: Path, resolved_root: Path | None = None) -> bool:
    """Whether *path* lies in a skipped directory below the watched *root*.

    Only components below *root* count, like detect.py's pruning: a project that itself
    lives under ``build/`` or ``.claude/worktrees/`` must still be watched.
    """
    p = Path(path)
    for base in (root, resolved_root or root.resolve()):
        try:
            parts = p.relative_to(base).parts
            break
        except ValueError:
            continue
    else:
        return False  # not under the root after all: prefer a spare rebuild to a missed one
    return any(part in _SKIP_DIRS for part in parts[:-1])


def _event_triggers_rebuild(
    event_type: str,
    src: str,
    dest: str,
    is_directory: bool,
    root: Path,
    resolved_root: Path | None = None,
    *,
    windows: bool = os.name == "nt",
) -> bool:
    """Whether a file-system event below *root* can change the graph."""
    if event_type not in _CHANGE_EVENTS:
        return False
    resolved_root = resolved_root or root.resolve()
    # Judge each end of a move on its own: moving classes/A.cls into dist/ removes it.
    ends = [
        p for p in (src, dest) if p and not _in_skipped_dir(p, root, resolved_root) and Path(p).name not in _SKIP_DIRS
    ]
    if not ends:
        return False
    if event_type in ("deleted", "moved") and (is_directory or (windows and not Path(src).suffix)):
        # Removing or moving a folder (an object, an LWC bundle) removes the files in it, and
        # watchdog may report only that one event. On Windows it reports a deleted folder as a
        # file event, so treat a suffix-less path as a folder there. (Not elsewhere: editors
        # create and delete suffix-less probe files on every save.)
        return True
    if is_directory:
        return False
    # A rename away from a metadata suffix removes a file from the graph.
    return any(_is_sf_file(p) for p in ends)


# ── Resource management ────────────────────────────────────────────────────────


def _apply_resource_limits() -> None:
    """Lower process priority and optionally cap memory usage.

    Sets ``nice(10)`` so background rebuilds don't starve interactive work.
    Honour ``GRAPHIFY_SF_REBUILD_MEMORY_LIMIT_MB`` (default: unlimited).
    """
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass  # Windows / restricted environments

    mem_limit_mb_str = os.environ.get("GRAPHIFY_SF_REBUILD_MEMORY_LIMIT_MB", "")
    if mem_limit_mb_str:
        try:
            import resource as _resource

            limit_bytes = int(mem_limit_mb_str) * 1024 * 1024
            soft, hard = _resource.getrlimit(_resource.RLIMIT_AS)
            new_soft = min(limit_bytes, hard) if hard != _resource.RLIM_INFINITY else limit_bytes
            _resource.setrlimit(_resource.RLIMIT_AS, (new_soft, hard))
        except (ImportError, ValueError, OSError):
            pass  # not available on all platforms


# ── Rebuild lock ───────────────────────────────────────────────────────────────


@contextlib.contextmanager
def _rebuild_lock(lock_path: Path):
    """Exclusive file lock to prevent concurrent rebuilds.

    Uses ``fcntl.flock`` (Unix) with a non-blocking acquire that
    silently skips the rebuild if another process holds the lock.
    Falls back to a no-op context manager on Windows.

    Yields ``True`` when the lock was acquired, ``False`` when skipped.
    """
    try:
        import fcntl as _fcntl

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as lf:
            try:
                _fcntl.flock(lf, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                try:
                    yield True
                finally:
                    _fcntl.flock(lf, _fcntl.LOCK_UN)
            except OSError:
                # Another rebuild is already running
                yield False
    except ImportError:
        # fcntl not available (Windows) — no locking, always proceed
        yield True


# ── Callflow auto-regeneration ─────────────────────────────────────────────────


def _regen_callflow_if_present(out_dir: Path) -> None:
    """Re-generate callflow HTML if a previous build produced one."""
    existing = list(out_dir.glob("*callflow*.html"))
    if not existing:
        return
    graph_path = out_dir / "graph.json"
    if not graph_path.exists():
        return
    try:
        from graphify_sf.__main__ import _load_graph_from_json
        from graphify_sf.export import to_callflow_html

        G, _ = _load_graph_from_json(graph_path)
        # Re-write to the first existing callflow file
        out_path = existing[0]
        n = to_callflow_html(G, str(out_path))
        print(f"[graphify-sf watch] callflow regenerated → {out_path} ({n} nodes)", flush=True)
    except Exception as exc:
        print(f"[graphify-sf watch] callflow regen skipped: {exc}", file=sys.stderr)


# ── Core rebuild ──────────────────────────────────────────────────────────────


def _rebuild(target: Path, out_dir: Path, directed: bool, no_viz: bool) -> None:
    """Trigger a rebuild (with lock + resource limits)."""
    lock_path = out_dir / ".graphify_sf_rebuild.lock"
    with _rebuild_lock(lock_path) as acquired:
        if not acquired:
            print("[graphify-sf watch] rebuild already in progress — skipping", flush=True)
            return
        _apply_resource_limits()
        from graphify_sf.__main__ import _run_pipeline

        try:
            _run_pipeline(target, out_dir, update=True, directed=directed, no_viz=no_viz)
        except SystemExit:
            pass
        except Exception as exc:
            print(f"[graphify-sf watch] rebuild error: {exc}", file=sys.stderr)
        # Re-generate callflow if it was previously built
        _regen_callflow_if_present(out_dir)


# ── Debounce timer ────────────────────────────────────────────────────────────


class _DebounceTimer:
    """Debounce: only fire after N seconds of silence."""

    def __init__(self, delay: float, callback):
        self._delay = delay
        self._callback = callback
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def trigger(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self._callback)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


# ── Watchdog backend ──────────────────────────────────────────────────────────


def _watch_watchdog(
    target: Path,
    out_dir: Path,
    debounce: float,
    directed: bool,
    no_viz: bool,
) -> None:
    """Use watchdog for efficient FS events."""
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    def do_rebuild():
        print("\n[graphify-sf watch] change detected — rebuilding...", flush=True)
        _rebuild(target, out_dir, directed, no_viz)
        print("[graphify-sf watch] waiting for changes... (Ctrl+C to stop)", flush=True)

    debouncer = _DebounceTimer(debounce, do_rebuild)
    root = Path(target)
    resolved_root = root.resolve()

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            src = getattr(event, "src_path", "") or ""
            dest = getattr(event, "dest_path", "") or ""
            if _event_triggers_rebuild(event.event_type, src, dest, event.is_directory, root, resolved_root):
                debouncer.trigger()

    observer = Observer()
    observer.schedule(Handler(), str(target), recursive=True)
    observer.start()
    print(f"[graphify-sf watch] watching {target} (watchdog)", flush=True)
    print("[graphify-sf watch] waiting for changes... (Ctrl+C to stop)", flush=True)
    try:
        while observer.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        debouncer.cancel()
        observer.stop()
        observer.join()


# ── Polling backend ───────────────────────────────────────────────────────────


def _watch_polling(
    target: Path,
    out_dir: Path,
    debounce: float,
    directed: bool,
    no_viz: bool,
    poll_interval: float = 5.0,
) -> None:
    """Fallback: poll every poll_interval seconds."""

    def _snapshot() -> dict[str, float]:
        snap: dict[str, float] = {}
        for dirpath, dirnames, filenames in os.walk(str(target)):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                if _is_sf_file(fpath):
                    try:
                        snap[fpath] = os.path.getmtime(fpath)
                    except OSError:
                        pass
        return snap

    prev = _snapshot()
    print(f"[graphify-sf watch] watching {target} (polling every {poll_interval:.0f}s)", flush=True)
    print("[graphify-sf watch] waiting for changes... (Ctrl+C to stop)", flush=True)
    pending_rebuild = False
    last_change_time = 0.0
    try:
        while True:
            time.sleep(poll_interval)
            curr = _snapshot()
            changed = set(curr) - set(prev) | {k for k in curr if curr[k] != prev.get(k, 0)}
            deleted = set(prev) - set(curr)
            if changed or deleted:
                last_change_time = time.time()
                pending_rebuild = True
                prev = curr
            if pending_rebuild and time.time() - last_change_time >= debounce:
                pending_rebuild = False
                print("\n[graphify-sf watch] change detected — rebuilding...", flush=True)
                _rebuild(target, out_dir, directed, no_viz)
                print("[graphify-sf watch] waiting for changes... (Ctrl+C to stop)", flush=True)
    except KeyboardInterrupt:
        pass


# ── Public entry point ────────────────────────────────────────────────────────


def watch(
    target: Path,
    out_dir: Path,
    *,
    debounce: float = 3.0,
    directed: bool = False,
    no_viz: bool = True,
    poll_interval: float = 5.0,
) -> None:
    """Watch an SFDX project directory and auto-rebuild on metadata changes.

    Args:
        target: SFDX project root to watch.
        out_dir: Output directory for graph artifacts (default: graphify-sf-out).
        debounce: Seconds to wait after last change before rebuilding.
        directed: Pass --directed to the rebuild pipeline.
        no_viz: Skip graph.html on rebuild (recommended for watch mode).
        poll_interval: Polling interval (seconds) when watchdog is unavailable.
    """
    # Ensure initial graph exists
    graph_json_path = out_dir / "graph.json"
    if not graph_json_path.exists():
        print("[graphify-sf watch] no graph.json found — running initial build...", flush=True)
        from graphify_sf.__main__ import _run_pipeline

        try:
            _run_pipeline(target, out_dir, directed=directed, no_viz=no_viz)
        except SystemExit:
            pass

    try:
        import watchdog  # noqa: F401

        _watch_watchdog(target, out_dir, debounce=debounce, directed=directed, no_viz=no_viz)
    except ImportError:
        print(
            "[graphify-sf watch] watchdog not installed — falling back to polling. "
            "Install with: pip install graphify-sf[watch]",
            file=sys.stderr,
        )
        _watch_polling(
            target,
            out_dir,
            debounce=debounce,
            directed=directed,
            no_viz=no_viz,
            poll_interval=poll_interval,
        )
