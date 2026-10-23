"""0.4.7 fixes: `hook install` refreshes an installed hook, the hook log is rotated, stale temp
files are swept, and a bind-mounted graph.json fails with a hint unless an in-place write is allowed."""

from __future__ import annotations

import errno
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from graphify_sf import export
from graphify_sf.__main__ import (
    _CHECKOUT_HOOK_BLOCK,
    _CHECKOUT_MARKER_END,
    _CHECKOUT_MARKER_START,
    _HOOK_BLOCK,
    _HOOK_MARKER_END,
    _HOOK_MARKER_START,
    _LOG_ROTATE_SNIPPET,
    _cmd_hook,
    _install_single_hook,
)

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="needs sh and POSIX permissions")


def _old_block(block: str) -> str:
    """The hook text of a release before the rotation snippet existed."""
    assert _LOG_ROTATE_SNIPPET in block
    return block.replace(_LOG_ROTATE_SNIPPET, "")


# ── hook install refreshes an installed hook ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("block", "start", "end"),
    [
        (_HOOK_BLOCK, _HOOK_MARKER_START, _HOOK_MARKER_END),
        (_CHECKOUT_HOOK_BLOCK, _CHECKOUT_MARKER_START, _CHECKOUT_MARKER_END),
    ],
)
def test_install_refreshes_only_our_block(tmp_path, block, start, end):
    hook = tmp_path / "post-commit"
    hook.write_text("#!/bin/sh\necho before\n\n" + _old_block(block) + "\necho after\n", encoding="utf-8")

    message = _install_single_hook(tmp_path, "post-commit", block, start, end)

    text = hook.read_text(encoding="utf-8")
    assert message.startswith("updated at")
    assert "echo before" in text and "echo after" in text
    assert text.count(start) == 1 and text.count(end) == 1
    assert _LOG_ROTATE_SNIPPET in text
    assert text.index("echo before") < text.index(start) < text.index(end) < text.index("echo after")


def test_install_leaves_an_up_to_date_hook_untouched(tmp_path):
    _install_single_hook(tmp_path, "post-commit", _HOOK_BLOCK, _HOOK_MARKER_START, _HOOK_MARKER_END)
    hook = tmp_path / "post-commit"
    before, mtime = hook.read_bytes(), hook.stat().st_mtime_ns

    message = _install_single_hook(tmp_path, "post-commit", _HOOK_BLOCK, _HOOK_MARKER_START, _HOOK_MARKER_END)

    assert message.startswith("already up to date")
    assert hook.read_bytes() == before and hook.stat().st_mtime_ns == mtime


def test_install_does_not_touch_a_block_without_an_end_marker(tmp_path):
    hook = tmp_path / "post-commit"
    broken = f"#!/bin/sh\n{_HOOK_MARKER_START}\necho half a block\n"
    hook.write_text(broken, encoding="utf-8")

    message = _install_single_hook(tmp_path, "post-commit", _HOOK_BLOCK, _HOOK_MARKER_START, _HOOK_MARKER_END)

    assert "no end marker" in message
    assert hook.read_text(encoding="utf-8") == broken


@posix_only
def test_fresh_install_creates_an_executable_hook(tmp_path):
    message = _install_single_hook(tmp_path, "post-commit", _HOOK_BLOCK, _HOOK_MARKER_START, _HOOK_MARKER_END)

    assert message.startswith("installed at")
    assert (tmp_path / "post-commit").stat().st_mode & stat.S_IXUSR


@posix_only
def test_hook_install_command_refreshes_hooks_in_a_custom_hooks_path(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".husky"], check=True, env=env)
    hooks = repo / ".husky"
    hooks.mkdir()
    (hooks / "post-commit").write_text("#!/bin/sh\nset -e\necho husky\n\n" + _old_block(_HOOK_BLOCK), encoding="utf-8")
    monkeypatch.chdir(repo)

    _cmd_hook("install")
    first = capsys.readouterr().out
    _cmd_hook("install")
    second = capsys.readouterr().out

    assert "post-commit:   updated at" in first
    assert "post-commit:   already up to date" in second
    assert "post-checkout: installed at" in first and "post-checkout: already up to date" in second
    text = (hooks / "post-commit").read_text(encoding="utf-8")
    assert "set -e" in text and "echo husky" in text and _LOG_ROTATE_SNIPPET in text


# ── hook log rotation ───────────────────────────────────────────────────────────────────────


def _run_snippet(log: Path, *, path_prefix: Path | None = None) -> subprocess.CompletedProcess:
    script = f'set -e\n_GSF_LOG="{log}"\n{_LOG_ROTATE_SNIPPET}echo reached\n'
    env = dict(os.environ)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    return subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env, timeout=30)


def test_both_hook_blocks_rotate_their_log():
    assert _LOG_ROTATE_SNIPPET in _HOOK_BLOCK and _LOG_ROTATE_SNIPPET in _CHECKOUT_HOOK_BLOCK
    for block in (_HOOK_BLOCK, _CHECKOUT_HOOK_BLOCK):
        assert block.index(_LOG_ROTATE_SNIPPET) < block.index("nohup")


@posix_only
def test_rotation_never_fails_a_set_e_hook_and_only_moves_a_big_log(tmp_path):
    log = tmp_path / "rebuild.log"

    missing = _run_snippet(log)
    assert missing.returncode == 0 and "reached" in missing.stdout

    log.write_text("small\n", encoding="utf-8")
    small = _run_snippet(log)
    assert small.returncode == 0 and "reached" in small.stdout
    assert log.read_text(encoding="utf-8") == "small\n" and not (tmp_path / "rebuild.log.1").exists()

    with open(log, "wb") as f:  # sparse: 2 MiB of metadata, nothing the snippet should read
        f.truncate(2 * 1024 * 1024)
    big = _run_snippet(log)
    assert big.returncode == 0 and "reached" in big.stdout
    assert not log.exists()
    assert (tmp_path / "rebuild.log.1").stat().st_size == 2 * 1024 * 1024
    with open(log, "ab") as f:  # the next hook appends to a fresh file
        f.write(b"fresh\n")
    assert log.read_bytes() == b"fresh\n"


@posix_only
def test_rotation_survives_a_failing_mv(tmp_path):
    log = tmp_path / "rebuild.log"
    with open(log, "wb") as f:
        f.truncate(2 * 1024 * 1024)
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "mv").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (fake / "mv").chmod(0o755)

    result = _run_snippet(log, path_prefix=fake)

    assert result.returncode == 0 and "reached" in result.stdout
    assert log.exists()


# ── orphan temp sweep ───────────────────────────────────────────────────────────────────────


def _age(path: Path, seconds: float) -> None:
    past = time.time() - seconds
    os.utime(path, (past, past), follow_symlinks=False)


@posix_only
def test_stale_temp_files_are_swept_but_lookalikes_are_not(tmp_path):
    stale = tmp_path / ".graph.json.123.abcdef12.tmp"
    fresh = tmp_path / ".graph.json.124.abcdef13.tmp"
    backup = tmp_path / ".graph.json.backup.tmp"
    dotted = tmp_path / ".graph-json.123.abcdef12.tmp"  # `.` in the name must not be a wildcard
    other_name = tmp_path / ".other.json.123.abcdef12.tmp"
    for p in (stale, fresh, backup, dotted, other_name):
        p.write_text("x", encoding="utf-8")
    for p in (stale, backup, dotted, other_name):
        _age(p, 2 * 3600)
    precious = tmp_path / "precious.txt"
    precious.write_text("keep", encoding="utf-8")
    link = tmp_path / ".graph.json.125.abcdef14.tmp"
    link.symlink_to(precious)
    _age(link, 2 * 3600)
    directory = tmp_path / ".graph.json.126.abcdef15.tmp"
    directory.mkdir()
    _age(directory, 2 * 3600)

    export._write_json_atomic(str(tmp_path / "graph.json"), {"ok": True})

    assert not stale.exists()
    for survivor in (fresh, backup, dotted, other_name, directory):
        assert survivor.exists(), survivor.name
    assert link.is_symlink() and precious.read_text(encoding="utf-8") == "keep"
    assert json.loads((tmp_path / "graph.json").read_text(encoding="utf-8")) == {"ok": True}


# ── bind-mounted graph.json ─────────────────────────────────────────────────────────────────


def _tmp_files(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


def _fail_replace(monkeypatch, code: int) -> None:
    def refuse(src, dst):
        raise OSError(code, os.strerror(code))

    monkeypatch.setattr(os, "replace", refuse)


@pytest.mark.parametrize("code", [errno.EBUSY, errno.EXDEV])
def test_bind_mounted_graph_fails_with_a_hint_by_default(tmp_path, monkeypatch, code):
    target = tmp_path / "graph.json"
    target.write_text('{"previous": true}', encoding="utf-8")
    monkeypatch.delenv("GRAPHIFY_SF_NONATOMIC_WRITE", raising=False)
    _fail_replace(monkeypatch, code)

    with pytest.raises(OSError, match="GRAPHIFY_SF_NONATOMIC_WRITE=1"):
        export._write_json_atomic(str(target), {"new": True})

    assert target.read_text(encoding="utf-8") == '{"previous": true}'
    assert _tmp_files(tmp_path) == []


@pytest.mark.parametrize("code", [errno.EBUSY, errno.EXDEV])
def test_bind_mounted_graph_is_written_in_place_when_allowed(tmp_path, monkeypatch, capsys, code):
    target = tmp_path / "graph.json"
    target.write_text('{"previous": "a much longer previous value than the new one"}', encoding="utf-8")
    monkeypatch.setenv("GRAPHIFY_SF_NONATOMIC_WRITE", "1")
    _fail_replace(monkeypatch, code)

    export._write_json_atomic(str(target), {"new": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}  # truncated to the new length
    assert "writing it in place" in capsys.readouterr().err
    assert _tmp_files(tmp_path) == []


def test_a_failed_in_place_write_restores_the_old_bytes_and_keeps_the_temp(tmp_path, monkeypatch):
    target = tmp_path / "graph.json"
    target.write_text('{"previous": true}', encoding="utf-8")
    monkeypatch.setenv("GRAPHIFY_SF_NONATOMIC_WRITE", "1")
    _fail_replace(monkeypatch, errno.EBUSY)
    real_fsync = os.fsync
    target_inode = target.stat().st_ino
    calls = {"n": 0}

    def fsync_fails_once(fd):
        # fail only the first fsync of the TARGET, so an fsync added elsewhere can't change this test
        if os.fstat(fd).st_ino == target_inode:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError(errno.ENOSPC, "No space left on device")
        return real_fsync(fd)

    monkeypatch.setattr(export.os, "fsync", fsync_fails_once)

    with pytest.raises(OSError, match="previous content was restored") as exc:
        export._write_json_atomic(str(target), {"new": True})

    assert target.read_text(encoding="utf-8") == '{"previous": true}'
    kept = _tmp_files(tmp_path)
    assert len(kept) == 1 and kept[0] in str(exc.value)
    assert json.loads((tmp_path / kept[0]).read_text(encoding="utf-8")) == {"new": True}  # complete copy


def test_permission_errors_never_fall_back_to_an_in_place_write(tmp_path, monkeypatch):
    target = tmp_path / "graph.json"
    target.write_text('{"previous": true}', encoding="utf-8")
    monkeypatch.setenv("GRAPHIFY_SF_NONATOMIC_WRITE", "1")

    def denied(src, dst):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(os, "replace", denied)
    monkeypatch.setattr(export.time, "sleep", lambda s: None)

    with pytest.raises(OSError, match="previous file was left unchanged"):
        export._write_json_atomic(str(target), {"new": True})

    assert target.read_text(encoding="utf-8") == '{"previous": true}'
    assert _tmp_files(tmp_path) == []


def test_nonatomic_flag_is_only_for_the_documented_values(monkeypatch):
    for value, expected in (("1", True), ("true", True), ("YES", True), ("0", False), ("", False), ("no", False)):
        monkeypatch.setenv("GRAPHIFY_SF_NONATOMIC_WRITE", value)
        assert export._nonatomic_write_allowed() is expected


def test_in_place_write_that_cannot_even_open_the_target_says_it_is_unchanged(tmp_path, monkeypatch):
    target = tmp_path / "graph.json"
    target.write_text('{"previous": true}', encoding="utf-8")
    monkeypatch.setenv("GRAPHIFY_SF_NONATOMIC_WRITE", "1")
    _fail_replace(monkeypatch, errno.EBUSY)
    real_open = open

    def open_denied_for_target(file, mode="r", *a, **k):
        if str(file) == str(target.resolve()) and "+" in mode:
            raise PermissionError(errno.EROFS, "Read-only file system")
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(export, "open", open_denied_for_target, raising=False)

    with pytest.raises(OSError, match="left unchanged") as exc:
        export._write_json_atomic(str(target), {"new": True})

    assert "could NOT be restored" not in str(exc.value)
    assert target.read_text(encoding="utf-8") == '{"previous": true}'


def test_uninstall_does_not_claim_to_remove_a_block_without_an_end_marker(tmp_path):
    from graphify_sf.__main__ import _uninstall_single_hook

    hook = tmp_path / "post-commit"
    broken = f"#!/bin/sh\n{_HOOK_MARKER_START}\necho half a block\n"
    hook.write_text(broken, encoding="utf-8")

    message = _uninstall_single_hook(tmp_path, "post-commit", _HOOK_MARKER_START, _HOOK_MARKER_END)

    assert "no end marker" in message and "by hand" in message
    assert hook.read_text(encoding="utf-8") == broken


@posix_only
def test_refresh_writes_through_a_symlinked_hook_and_keeps_its_mode(tmp_path):
    tracked = tmp_path / "tools" / "post-commit"
    tracked.parent.mkdir()
    tracked.write_text("#!/bin/sh\n" + _old_block(_HOOK_BLOCK), encoding="utf-8")
    tracked.chmod(0o750)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "post-commit").symlink_to(tracked)

    message = _install_single_hook(hooks, "post-commit", _HOOK_BLOCK, _HOOK_MARKER_START, _HOOK_MARKER_END)

    assert message.startswith("updated at")
    assert (hooks / "post-commit").is_symlink()
    assert _LOG_ROTATE_SNIPPET in tracked.read_text(encoding="utf-8")
    assert stat.S_IMODE(tracked.stat().st_mode) == 0o750
