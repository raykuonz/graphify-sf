"""0.4.6 fixes: output dir is never re-ingested, runs are serialised, graph.json is written
atomically and first, hook logs append, and npm error prefixes are not doubled (npm/test)."""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from graphify_sf import _lock
from graphify_sf.__main__ import _run_pipeline

FIXTURES = Path(__file__).parent / "fixtures"
needs_fcntl = pytest.mark.skipif(sys.platform == "win32", reason="flock is POSIX only")


def _build(project: Path, out: Path, *, update: bool = False, force: bool = False, no_viz: bool = True) -> dict:
    _run_pipeline(project, out, update=update, directed=False, no_viz=no_viz, max_workers=1, force=force)
    return json.loads((out / "graph.json").read_text(encoding="utf-8"))


def _two_class_project(root: Path) -> Path:
    base = root / "force-app" / "main" / "default" / "classes"
    base.mkdir(parents=True)
    (base / "First.cls").write_text("public class First { }", encoding="utf-8")
    (base / "Second.cls").write_text("public class Second { }", encoding="utf-8")
    return base


# ── custom --out inside the project ─────────────────────────────────────────────────────────


def test_custom_out_dir_inside_the_project_is_not_reingested(tmp_path):
    project = tmp_path / "proj"
    shutil.copytree(FIXTURES / "epicA_callout", project)
    out = project / "build-output"  # not the default name, so detect used to scan it

    first = _build(project, out)
    again = _build(project, out)
    updated = _build(project, out, update=True)

    assert len(first["links"]) > 0
    assert len(again["links"]) == len(first["links"])
    assert len(updated["links"]) == len(first["links"])
    assert not [n for n in updated["nodes"] if "build-output" in (n.get("source_file") or "")]


def test_detect_skips_out_dir_wherever_it_is(tmp_path):
    from graphify_sf.detect import detect

    project = tmp_path / "proj"
    _two_class_project(project)
    out = project / "reports"
    out.mkdir()
    (out / "GRAPH_REPORT.md").write_text("# report\n", encoding="utf-8")

    without = detect(project)
    with_out = detect(project, out_dir=out)

    assert any(f.endswith("GRAPH_REPORT.md") for fs in without["doc_files"].values() for f in fs)
    assert not any(f.endswith("GRAPH_REPORT.md") for fs in with_out["doc_files"].values() for f in fs)


def test_detect_out_dir_trailing_dot_and_case_alias(tmp_path):
    from graphify_sf.detect import detect

    project = tmp_path / "proj"
    _two_class_project(project)
    out = project / "out"
    out.mkdir()
    (out / "GRAPH_REPORT.md").write_text("# report\n", encoding="utf-8")

    def reported(d):
        return any(f.endswith("GRAPH_REPORT.md") for fs in d["doc_files"].values() for f in fs)

    assert not reported(detect(project, out_dir=Path(os.path.join(str(out), "."))))
    if (project / "OUT").exists():  # case-insensitive filesystem (macOS, Windows)
        assert not reported(detect(project, out_dir=project / "OUT"))


def test_detect_tolerates_a_missing_or_unreadable_out_dir(tmp_path, monkeypatch):
    from graphify_sf import detect as detect_mod

    project = tmp_path / "proj"
    _two_class_project(project)
    out = project / "reports"
    out.mkdir()

    assert detect_mod.detect(project, out_dir=project / "does-not-exist")["total_files"] == 2

    def boom(*a, **k):
        raise OSError("stat failed")

    monkeypatch.setattr(os.path, "samefile", boom)
    assert detect_mod.detect(project, out_dir=out)["total_files"] == 2


def test_out_dir_equal_to_the_root_warns_and_prunes_nothing(tmp_path, capsys):
    from graphify_sf.detect import contained_out_dir

    project = tmp_path / "proj"
    project.mkdir()

    assert contained_out_dir(project.resolve(), project) is None
    assert "--out is the project root" in capsys.readouterr().err
    assert contained_out_dir(project.resolve(), tmp_path) is None  # an ancestor
    assert contained_out_dir(project.resolve(), tmp_path / "elsewhere") is None  # outside / missing


def test_sidecars_follow_out_dir_but_not_when_out_is_the_root(tmp_path):
    docx = pytest.importorskip("docx")
    from graphify_sf.detect import detect

    def project_with_docx(name: str) -> Path:
        project = tmp_path / name
        _two_class_project(project)
        document = docx.Document()
        document.add_paragraph("hello")
        document.save(str(project / "spec.docx"))
        return project

    def sidecars(d):
        return [f for fs in d["doc_files"].values() for f in fs if f.endswith(".md")]

    inside_project = project_with_docx("inside")
    (inside_project / "reports").mkdir()
    inside = sidecars(detect(inside_project, out_dir=inside_project / "reports"))
    outside = sidecars(detect(project_with_docx("outside"), out_dir=tmp_path / "out_outside"))
    root_project = project_with_docx("root")
    at_root = sidecars(detect(root_project, out_dir=root_project))

    reports_converted = (inside_project / "reports" / "converted").resolve()
    assert inside and all(str(reports_converted) in f for f in inside)
    assert outside and all(f"out_outside{os.sep}converted" in f for f in outside)
    assert at_root and all(f"{os.sep}graphify-sf-out{os.sep}converted" in f for f in at_root)


def test_watcher_filters_out_dir_only_when_strictly_inside_the_root(tmp_path):
    from graphify_sf.detect import contained_out_dir
    from graphify_sf.watch import _event_triggers_rebuild

    root = (tmp_path / "proj").resolve()
    (root / "reports").mkdir(parents=True)
    cls = str(root / "force-app" / "main" / "default" / "classes" / "A.cls")
    in_out = str(root / "reports" / "Generated.cls")

    inside = contained_out_dir(root, root / "reports")
    assert _event_triggers_rebuild("modified", in_out, "", False, root, out_skip=inside) is False
    assert _event_triggers_rebuild("modified", cls, "", False, root, out_skip=inside) is True

    for out_dir in (root, tmp_path, tmp_path / "elsewhere"):  # equal, ancestor, outside
        skip = contained_out_dir(root, out_dir)
        assert skip is None
        assert _event_triggers_rebuild("modified", cls, "", False, root, out_skip=skip) is True


# ── lock ───────────────────────────────────────────────────────────────────────────────────

_HOLDER = """
import fcntl, sys
f = open(sys.argv[1], "a+b")
fcntl.flock(f, fcntl.LOCK_EX)
print("ready", flush=True)
sys.stdin.read()  # hold until the parent closes stdin
"""


class _Holder:
    """Another process holding the lock on ``path`` until released."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            [sys.executable, "-c", _HOLDER, str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        assert self.proc.stdout.readline().strip() == "ready"

    def release(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


@needs_fcntl
def test_file_lock_try_once_reports_busy(tmp_path):
    path = tmp_path / "out" / _lock.LOCK_NAME
    with _Holder(path), _lock.file_lock(path, wait=0) as acquired:
        assert acquired is False
    with _lock.file_lock(path, wait=0) as acquired:  # free again
        assert acquired is True


@needs_fcntl
def test_file_lock_waits_for_the_holder_and_announces_it_once(tmp_path, capsys):
    path = tmp_path / "out" / _lock.LOCK_NAME
    holder = _Holder(path)
    timer = threading.Timer(0.6, holder.release)
    timer.start()
    started = time.monotonic()
    try:
        with _lock.file_lock(path, wait=10) as acquired:
            assert acquired is True
            assert time.monotonic() - started >= 0.4
    finally:
        timer.join()
    err = capsys.readouterr().err
    assert err.count("another run is updating") == 1


@needs_fcntl
def test_file_lock_gives_up_after_the_wait(tmp_path):
    path = tmp_path / "out" / _lock.LOCK_NAME
    with _Holder(path):
        started = time.monotonic()
        with _lock.file_lock(path, wait=0.5) as acquired:
            assert acquired is False
        assert 0.4 <= time.monotonic() - started < 5


@needs_fcntl
def test_file_lock_proceeds_unlocked_when_the_filesystem_cannot_lock(tmp_path, monkeypatch, capsys):
    import fcntl

    def unsupported(*a, **k):
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(fcntl, "flock", unsupported)

    with _lock.file_lock(tmp_path / "out" / _lock.LOCK_NAME, wait=0) as acquired:
        assert acquired is True
    assert "continuing without a lock" in capsys.readouterr().err


def test_lock_timeout_is_validated(monkeypatch, capsys):
    monkeypatch.delenv("GRAPHIFY_SF_LOCK_TIMEOUT", raising=False)
    assert _lock.lock_timeout() == 900
    monkeypatch.setenv("GRAPHIFY_SF_LOCK_TIMEOUT", "2.5")
    assert _lock.lock_timeout() == 2.5
    for bad in ("soon", "-3", "nan"):
        monkeypatch.setenv("GRAPHIFY_SF_LOCK_TIMEOUT", bad)
        assert _lock.lock_timeout() == 900
    assert "invalid GRAPHIFY_SF_LOCK_TIMEOUT" in capsys.readouterr().err


@needs_fcntl
@pytest.mark.parametrize("command", ["build", "cluster-only", "export-json"])
def test_cli_commands_exit_1_when_the_output_lock_stays_busy(tmp_path, monkeypatch, capsys, command):
    from graphify_sf.__main__ import main

    project = tmp_path / "proj"
    _two_class_project(project)
    out = tmp_path / "out"
    _build(project, out)
    argv = {
        "build": ["graphify-sf", str(project), "--out", str(out), "--no-viz"],
        "cluster-only": ["graphify-sf", "cluster-only", str(project), "--out", str(out), "--no-viz"],
        "export-json": ["graphify-sf", "export", "json", "--graph", str(out / "graph.json"), "--out", str(out)],
    }[command]
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setenv("GRAPHIFY_SF_LOCK_TIMEOUT", "1")
    before = (out / "graph.json").read_bytes()

    with _Holder(out / _lock.LOCK_NAME), pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    assert "held the lock" in capsys.readouterr().err
    assert (out / "graph.json").read_bytes() == before


@needs_fcntl
def test_watch_initial_build_waits_for_the_lock_but_idle_watch_does_not(tmp_path, monkeypatch):
    import graphify_sf.__main__ as cli
    from graphify_sf import watch as watch_mod

    project = tmp_path / "proj"
    _two_class_project(project)
    out = tmp_path / "out"
    calls: list[float] = []

    class Stop(Exception):
        pass

    def fake_pipeline(*a, **k):
        calls.append(time.monotonic())

    def stop(*a, **k):
        raise Stop

    monkeypatch.setattr(cli, "_run_pipeline", fake_pipeline)
    monkeypatch.setattr(watch_mod, "_watch_watchdog", stop)
    monkeypatch.setattr(watch_mod, "_watch_polling", stop)
    monkeypatch.setitem(sys.modules, "watchdog", type(sys)("watchdog"))

    holder = _Holder(out / _lock.LOCK_NAME)
    timer = threading.Timer(0.6, holder.release)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(Stop):
            watch_mod.watch(project, out)  # no graph.json yet: initial build must wait for the holder
    finally:
        timer.join()
    assert len(calls) == 1 and calls[0] - started >= 0.4

    # Idle watcher (graph.json present): never takes the lock, so a busy lock doesn't delay it.
    (out / "graph.json").write_text("{}", encoding="utf-8")
    with _Holder(out / _lock.LOCK_NAME):
        started = time.monotonic()
        with pytest.raises(Stop):
            watch_mod.watch(project, out)
        assert time.monotonic() - started < 0.5
    assert len(calls) == 1


class _Calls(list):
    install = None  # set by the fixture


@pytest.fixture
def counted_pipeline(monkeypatch):
    """Replace the pipeline and side effects used by watch rebuilds; returns the call list."""
    import graphify_sf.__main__ as cli
    from graphify_sf import watch as watch_mod

    calls = _Calls()
    monkeypatch.setattr(watch_mod, "_apply_resource_limits", lambda: None)
    monkeypatch.setattr(watch_mod, "_regen_callflow_if_present", lambda out_dir: None)

    def install(behaviour=None):
        def fake(*a, **k):
            calls.append(1)
            if behaviour:
                behaviour(len(calls))

        monkeypatch.setattr(cli, "_run_pipeline", fake)

    install()
    calls.install = install
    return calls


@needs_fcntl
def test_watch_events_during_a_lock_wait_make_exactly_one_rebuild(tmp_path, counted_pipeline):
    from graphify_sf import watch as watch_mod

    target, out = tmp_path / "proj", tmp_path / "out"
    holder = _Holder(out / _lock.LOCK_NAME)
    threads = [threading.Thread(target=watch_mod._rebuild, args=(target, out, False, True)) for _ in range(5)]
    for t in threads:
        t.start()
    time.sleep(0.5)  # all five have requested; one worker waits on the lock
    holder.release()
    for t in threads:
        t.join(timeout=20)

    assert len(counted_pipeline) == 1


def test_watch_events_during_a_rebuild_make_exactly_one_follow_up(tmp_path, counted_pipeline):
    from graphify_sf import watch as watch_mod

    target, out = tmp_path / "proj", tmp_path / "out"

    def during_first_run(n):
        if n == 1:
            for _ in range(3):
                watch_mod._rebuild(target, out, False, True)  # arrive while running -> pending

    counted_pipeline.install(during_first_run)
    watch_mod._rebuild(target, out, False, True)

    assert len(counted_pipeline) == 2


def test_watch_rebuild_survives_a_pipeline_system_exit(tmp_path, counted_pipeline):
    from graphify_sf import watch as watch_mod

    target, out = tmp_path / "proj", tmp_path / "out"

    def exit_first(n):
        if n == 1:
            raise SystemExit(1)

    counted_pipeline.install(exit_first)
    watch_mod._rebuild(target, out, False, True)
    watch_mod._rebuild(target, out, False, True)  # must not be swallowed as "already running"

    assert len(counted_pipeline) == 2


def test_hook_scripts_append_to_the_shared_log():
    from graphify_sf.__main__ import _CHECKOUT_HOOK_BLOCK, _HOOK_BLOCK

    for block in (_HOOK_BLOCK, _CHECKOUT_HOOK_BLOCK):
        assert '>> "$_GSF_LOG"' in block
        assert '> "$_GSF_LOG"' not in block.replace('>> "$_GSF_LOG"', "")


# ── atomic graph.json ──────────────────────────────────────────────────────────────────────


def _tiny_graph():
    import networkx as nx

    G = nx.MultiDiGraph()
    G.add_node("a", label="A", sf_type="ApexClass")
    G.add_node("b", label="B", sf_type="ApexClass")
    G.add_edge("a", "b", relation="calls", confidence="EXTRACTED")
    return G


def _leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


def test_to_json_writes_atomically_and_leaves_no_temp_file(tmp_path):
    from graphify_sf.export import to_json

    path = tmp_path / "graph.json"
    assert to_json(_tiny_graph(), {0: ["a", "b"]}, str(path)) is True

    assert json.loads(path.read_text(encoding="utf-8"))["nodes"]
    assert _leftovers(tmp_path) == []


def test_to_json_failure_mid_write_keeps_the_previous_file(tmp_path, monkeypatch):
    from graphify_sf.export import to_json

    path = tmp_path / "graph.json"
    path.write_text('{"previous": true}', encoding="utf-8")

    def partial_then_boom(data, handle, **kwargs):
        handle.write('{"nodes": [')
        raise RuntimeError("disk full")

    monkeypatch.setattr(json, "dump", partial_then_boom)
    with pytest.raises(RuntimeError):
        to_json(_tiny_graph(), {}, str(path), force=True)

    assert path.read_text(encoding="utf-8") == '{"previous": true}'
    assert _leftovers(tmp_path) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions and symlinks")
def test_to_json_keeps_permissions_and_symlinks(tmp_path):
    from graphify_sf.export import to_json

    real = tmp_path / "real" / "graph.json"
    real.parent.mkdir()
    real.write_text("{}", encoding="utf-8")
    real.chmod(0o640)
    link = tmp_path / "graph.json"
    link.symlink_to(real)

    to_json(_tiny_graph(), {}, str(link), force=True)

    assert link.is_symlink()
    assert json.loads(real.read_text(encoding="utf-8"))["nodes"]
    assert (real.stat().st_mode & 0o777) == 0o640


def test_to_json_retries_a_transient_permission_error(tmp_path, monkeypatch):
    from graphify_sf import export

    path = tmp_path / "graph.json"
    real_replace = os.replace
    failures = {"left": 2}

    def flaky(src, dst):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError(13, "in use")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(export.time, "sleep", lambda s: None)

    assert export.to_json(_tiny_graph(), {}, str(path)) is True
    assert json.loads(path.read_text(encoding="utf-8"))["nodes"]
    assert _leftovers(tmp_path) == []


def test_to_json_permanent_permission_error_leaves_the_old_file_valid(tmp_path, monkeypatch):
    from graphify_sf import export

    path = tmp_path / "graph.json"
    path.write_text('{"previous": true}', encoding="utf-8")

    def denied(src, dst):
        raise PermissionError(13, "in use")

    monkeypatch.setattr(os, "replace", denied)
    monkeypatch.setattr(export.time, "sleep", lambda s: None)

    with pytest.raises(OSError, match="previous file was left unchanged"):
        export.to_json(_tiny_graph(), {}, str(path), force=True)

    assert path.read_text(encoding="utf-8") == '{"previous": true}'
    assert _leftovers(tmp_path) == []


# ── graph.json first; nothing is published around a refused or failed write ─────────────────


def _snapshot(out: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(out.iterdir()) if p.is_file() and p.suffix != ".lock"}


def test_refused_shrink_publishes_nothing_and_exits_1(tmp_path, capsys):
    base = _two_class_project(tmp_path / "proj")
    out = tmp_path / "out"
    _build(tmp_path / "proj", out, no_viz=False)
    before = _snapshot(out)
    (base / "Second.cls").unlink()

    with pytest.raises(SystemExit) as exc:
        _build(tmp_path / "proj", out, no_viz=False)  # plain run, no --force

    assert exc.value.code == 1
    assert "use --force" in capsys.readouterr().err
    assert _snapshot(out) == before  # graph, report, labels, manifest and html all untouched


def test_failed_graph_write_publishes_nothing_and_exits_1(tmp_path, monkeypatch, capsys):
    from graphify_sf import export

    _two_class_project(tmp_path / "proj")
    out = tmp_path / "out"
    _build(tmp_path / "proj", out, no_viz=False)
    before = _snapshot(out)

    def denied(src, dst):
        raise PermissionError(13, "in use")

    monkeypatch.setattr(os, "replace", denied)
    monkeypatch.setattr(export.time, "sleep", lambda s: None)

    with pytest.raises(SystemExit) as exc:
        _build(tmp_path / "proj", out, update=True, no_viz=False)

    assert exc.value.code == 1
    assert "could not write" in capsys.readouterr().err
    assert _snapshot(out) == before


def test_cluster_only_and_merge_graphs_write_the_graph_before_the_report(tmp_path, monkeypatch):
    from graphify_sf import export
    from graphify_sf.__main__ import _cmd_cluster_only, _cmd_merge_graphs

    _two_class_project(tmp_path / "proj")
    out = tmp_path / "out"
    _build(tmp_path / "proj", out)
    report = out / "GRAPH_REPORT.md"
    report.write_text("old report", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("graph.json is locked")

    monkeypatch.setattr(export, "to_json", boom)

    with pytest.raises(OSError):
        _cmd_cluster_only(tmp_path / "proj", out, no_viz=True)
    assert report.read_text(encoding="utf-8") == "old report"

    merged = tmp_path / "merged"
    with pytest.raises(OSError):
        _cmd_merge_graphs([out / "graph.json", out / "graph.json"], merged / "graph.json", no_viz=True)
    assert not (merged / "GRAPH_REPORT.md").exists()


# ── review follow-ups ──────────────────────────────────────────────────────────────────────


_FORKER = """
import os, sys, time
from pathlib import Path
from graphify_sf import _lock

if len(sys.argv) > 2:  # mutation check: behave as if the fork hook did not exist
    _lock._register_fork_hook = lambda: None
cm = _lock.file_lock(Path(sys.argv[1]), wait=0)
cm.__enter__()
pid = os.fork()
if pid == 0:  # a worker of the extraction pool: outlives the parent
    null = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):  # let the caller's pipes close
        os.dup2(null, fd)
    time.sleep(8)
    os._exit(0)
print(pid, flush=True)
os._exit(0)  # the parent dies without unlocking (OOM kill, SIGKILL)
"""


@needs_fcntl
def test_orphaned_forked_workers_do_not_keep_a_dead_runs_lock(tmp_path):
    # The extraction pool forks on Linux. A flock lives until every descriptor for it is closed,
    # so without the fork hook an orphaned worker would hold a killed run's lock for good.
    path = tmp_path / "out" / _lock.LOCK_NAME
    proc = subprocess.run([sys.executable, "-c", _FORKER, str(path)], capture_output=True, text=True, timeout=30)
    child = int(proc.stdout.split()[0])
    try:
        with _lock.file_lock(path, wait=0) as acquired:
            assert acquired is True  # False if the orphaned worker still held its inherited copy
    finally:
        os.kill(child, 9)


@needs_fcntl
def test_errors_in_an_unlocked_run_are_not_chained_to_the_lock_error(tmp_path, monkeypatch):
    import fcntl

    def unsupported(*a, **k):
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(fcntl, "flock", unsupported)

    with pytest.raises(ValueError) as exc:
        with _lock.file_lock(tmp_path / _lock.LOCK_NAME, wait=0):
            raise ValueError("real problem")

    assert exc.value.__context__ is None


def test_out_dir_is_found_by_identity_not_spelling(tmp_path):
    from graphify_sf.detect import contained_out_dir

    (tmp_path / "Proj" / "reports").mkdir(parents=True)

    found = contained_out_dir(tmp_path / "proj", tmp_path / "Proj" / "reports")

    if (tmp_path / "proj").exists():  # case-insensitive filesystem (macOS, Windows): same directory
        assert found is not None
    else:  # case-sensitive (Linux CI): "proj" is a different, missing directory
        assert found is None


def test_detect_says_which_output_directory_it_is_not_scanning(tmp_path, capsys):
    from graphify_sf.detect import detect

    project = tmp_path / "proj"
    _two_class_project(project)
    (project / "reports").mkdir()
    (project / "graphify-sf-out").mkdir()

    detect(project, out_dir=project / "reports")
    assert "not scanning the output directory" in capsys.readouterr().err

    detect(project, out_dir=project / "graphify-sf-out")  # the default name is pruned as before
    assert "not scanning" not in capsys.readouterr().err


@pytest.mark.parametrize("command", ["cluster-only", "export-json"])
def test_commands_turn_a_graph_write_error_into_exit_1(tmp_path, monkeypatch, capsys, command):
    from graphify_sf import export
    from graphify_sf.__main__ import main

    _two_class_project(tmp_path / "proj")
    out = tmp_path / "out"
    _build(tmp_path / "proj", out)
    argv = {
        "cluster-only": ["graphify-sf", "cluster-only", str(tmp_path / "proj"), "--out", str(out), "--no-viz"],
        "export-json": ["graphify-sf", "export", "json", "--graph", str(out / "graph.json"), "--out", str(out)],
    }[command]
    monkeypatch.setattr("sys.argv", argv)

    def denied(*a, **k):
        raise OSError("could not replace graph.json")

    monkeypatch.setattr(export, "to_json", denied)

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    assert "error: could not replace graph.json" in capsys.readouterr().err


def test_cluster_only_refuses_to_publish_when_the_graph_was_not_written(tmp_path, monkeypatch, capsys):
    from graphify_sf import export
    from graphify_sf.__main__ import _cmd_cluster_only

    _two_class_project(tmp_path / "proj")
    out = tmp_path / "out"
    _build(tmp_path / "proj", out)
    report = out / "GRAPH_REPORT.md"
    report.write_text("old report", encoding="utf-8")
    monkeypatch.setattr(export, "to_json", lambda *a, **k: False)

    with pytest.raises(SystemExit) as exc:
        _cmd_cluster_only(tmp_path / "proj", out, no_viz=True)

    assert exc.value.code == 1
    assert report.read_text(encoding="utf-8") == "old report"


def test_the_watch_first_build_is_skipped_when_a_run_holding_the_lock_just_built_it(tmp_path, monkeypatch):
    import graphify_sf.__main__ as cli
    from graphify_sf import watch as watch_mod

    project, out = tmp_path / "proj", tmp_path / "out"
    _two_class_project(project)
    built: list[int] = []

    class Stop(Exception):
        pass

    def pipeline_that_built_it_elsewhere(*a, **k):
        built.append(1)

    real_lock = watch_mod.file_lock

    from contextlib import contextmanager

    @contextmanager
    def lock_then_graph_appears(path, **kw):
        with real_lock(path, **kw) as acquired:
            (out / "graph.json").write_text("{}", encoding="utf-8")  # the other run finished meanwhile
            yield acquired

    monkeypatch.setattr(watch_mod, "file_lock", lock_then_graph_appears)
    monkeypatch.setattr(cli, "_run_pipeline", pipeline_that_built_it_elsewhere)
    monkeypatch.setattr(watch_mod, "_watch_watchdog", lambda *a, **k: (_ for _ in ()).throw(Stop()))
    monkeypatch.setattr(watch_mod, "_watch_polling", lambda *a, **k: (_ for _ in ()).throw(Stop()))
    monkeypatch.setitem(sys.modules, "watchdog", type(sys)("watchdog"))

    with pytest.raises(Stop):
        watch_mod.watch(project, out)

    assert built == []
