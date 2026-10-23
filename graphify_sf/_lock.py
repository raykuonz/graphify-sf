"""Advisory lock that serialises runs writing to one output directory.

Git hooks, the CLI and ``watch`` can all rebuild the same ``graphify-sf-out/``. Without a
lock the last writer wins, and a slow run that started on an older tree can overwrite a
newer graph. ``flock`` is released by the kernel when the process dies, and forked workers
close their inherited copy, so a crashed run does not leave a stale lock.

Windows has no ``fcntl`` and some network filesystems don't support ``flock``; in both
cases the lock degrades to a no-op (best effort), exactly as before this module existed.
"""

from __future__ import annotations

import contextlib
import errno
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

DEFAULT_TIMEOUT = 900.0
_POLL_SECONDS = 0.2
_CONTENTION = (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK)

LOCK_NAME = ".graphify_sf_rebuild.lock"


def lock_timeout() -> float:
    """Seconds to wait for the lock, from ``GRAPHIFY_SF_LOCK_TIMEOUT`` (default 900)."""
    raw = os.environ.get("GRAPHIFY_SF_LOCK_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if value < 0 or value != value:  # negative or NaN
        print(
            f"[graphify-sf] WARNING: ignoring invalid GRAPHIFY_SF_LOCK_TIMEOUT={raw!r} (using {DEFAULT_TIMEOUT:.0f}s)",
            file=sys.stderr,
        )
        return DEFAULT_TIMEOUT
    return value


# Handles of locks held by this process. A forked child (the extraction process pool on
# Linux) inherits them, and a flock stays held until EVERY descriptor for it is closed, so a
# killed parent would leave orphaned workers holding the lock. Children close their copies;
# closing a copy never releases the parent's lock.
_HELD: list = []
_FORK_HOOK_REGISTERED = False


def _close_inherited_locks() -> None:
    for handle in _HELD:
        with contextlib.suppress(Exception):
            handle.close()
    _HELD.clear()


def _register_fork_hook() -> None:
    global _FORK_HOOK_REGISTERED
    if not _FORK_HOOK_REGISTERED and hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=_close_inherited_locks)
        _FORK_HOOK_REGISTERED = True


@contextlib.contextmanager
def file_lock(path: Path, *, wait: float | None = 0.0, label: str | None = None) -> Iterator[bool]:
    """Hold an exclusive lock on *path* while the ``with`` body runs.

    ``wait`` is how long to keep trying: ``0`` tries once, ``None`` waits forever.
    Yields ``True`` when the body may proceed under the lock *or* the platform cannot
    lock (best effort), and ``False`` when the lock stayed busy for the whole wait.
    On the first failed attempt a one-line message says what is being waited for.
    """
    try:
        import fcntl
    except ImportError:  # Windows
        yield True
        return

    _register_fork_hook()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as handle:
        deadline = None if wait is None else time.monotonic() + wait
        announced = False
        outcome = "locked"
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in _CONTENTION:
                    print(
                        f"[graphify-sf] WARNING: cannot lock {path} ({exc.strerror or exc}); continuing without a lock",
                        file=sys.stderr,
                    )
                    outcome = "unsupported"
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    outcome = "busy"
                    break
            if not announced:
                announced = True
                where = label or str(path.parent)
                limit = "" if wait is None else f" (up to {wait:.0f}s)"
                print(
                    f"[graphify-sf] another run is updating {where}; waiting{limit}...",
                    file=sys.stderr,
                    flush=True,
                )
            time.sleep(_POLL_SECONDS)
        if outcome != "locked":  # raised outside the except block, so errors don't chain to it
            yield outcome == "unsupported"
            return
        _HELD.append(handle)
        try:
            yield True
        finally:
            with contextlib.suppress(ValueError):
                _HELD.remove(handle)
            with contextlib.suppress(OSError):
                fcntl.flock(handle, fcntl.LOCK_UN)
