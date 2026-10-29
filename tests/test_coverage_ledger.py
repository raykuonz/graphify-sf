"""0.6.0 E2: the coverage ledger in graph.json (graphify_sf block): accounting, round trips, merges."""

from __future__ import annotations

import json
import shutil
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pytest

from graphify_sf import _ledger
from graphify_sf.detect import detect
from graphify_sf.extract import extract

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def enabled(monkeypatch):
    """Turn both callout analyzers on (a no-op while both ship enabled)."""
    for spec in _ledger.ANALYZERS.values():
        monkeypatch.setitem(spec, "enabled", True)


def _project(tmp_path: Path, *, extra_classes: int = 0) -> Path:
    project = tmp_path / "proj"
    shutil.copytree(FIXTURES / "epicA_callout", project)
    classes = project / "force-app" / "main" / "default" / "classes"
    for i in range(extra_classes):
        (classes / f"Extra{i}.cls").write_text(f"public class Extra{i} {{ }}\n", encoding="utf-8")
    return project


def _assert_invariant(analysis: dict) -> None:
    for name, entry in analysis.items():
        if "eligible" in entry:
            assert entry["analyzed"] + entry["failed"] == entry["eligible"], (name, entry)


def _count(project: Path, *patterns: str) -> int:
    """Eligible files counted straight from disk, independently of the coordinator."""
    return sum(1 for pattern in patterns for _ in project.rglob(pattern))


# ── pure functions ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("eligible", "failed", "status"),
    [(0, 0, "complete"), (5, 0, "complete"), (5, 2, "partial"), (5, 5, "failed"), (1, 1, "failed")],
)
def test_status_equations(eligible, failed, status):
    assert _ledger.status_for(eligible, failed) == status


def test_capabilities_are_derived_from_complete_statuses_only():
    analysis = {
        "a": {"status": "complete"},
        "b": {"status": "partial"},
        "c": {"status": "failed"},
        "d": {"status": "not_run"},
    }
    assert _ledger.derive_capabilities(analysis) == ["a"]
    assert _ledger.derive_capabilities({}) == []


def test_merged_ledger_is_a_status_only_meet():
    complete = {
        "version": "0.6.0",
        "analysis": {"x": {"status": "complete", "eligible": 9, "analyzed": 9, "failed": 0}},
    }
    partial = {"version": "0.6.0", "analysis": {"x": {"status": "partial", "eligible": 9, "analyzed": 5, "failed": 4}}}
    merged = _ledger.merged_ledger([complete, partial])
    assert merged == {
        "scope": "merged",
        "analysis": {"x": {"status": "partial"}},
        "capabilities": [],
        "versions": ["0.6.0"],
    }
    assert _ledger.merged_ledger([complete, complete])["capabilities"] == ["x"]
    # an input without a block (or without the analyzer) never contributes coverage
    assert _ledger.merged_ledger([complete, None])["analysis"]["x"]["status"] == "not_run"
    assert _ledger.merged_ledger([complete, {"analysis": {}}])["analysis"]["x"]["status"] == "not_run"
    assert _ledger.merged_ledger([None, None]) is None


def test_every_analyzer_suffix_is_dispatched_to_the_intended_extractor():
    """A typo'd suffix would give eligible 0, which is 'complete': guard the table against that."""
    import graphify_sf.extract as ex
    from graphify_sf.extract.apex import extract_apex_class, extract_apex_trigger
    from graphify_sf.extract.flow import extract_flow

    expected = {".cls": extract_apex_class, ".trigger": extract_apex_trigger, ".flow-meta.xml": extract_flow}
    for name, spec in _ledger.ANALYZERS.items():
        assert spec["suffixes"], name
        for suffix in spec["suffixes"]:
            assert ex._DISPATCH[suffix] is expected[suffix], (name, suffix)


def test_merged_ledger_tolerates_malformed_blocks_and_records_versions():
    good = {"version": "0.6.0", "analysis": {"x": {"status": "complete"}}}
    for bad in (
        {"analysis": None},
        {"analysis": {"x": None}},
        {"analysis": {"x": {"status": "weird"}}},
        {"analysis": ["x"]},
        "not a dict",
    ):
        merged = _ledger.merged_ledger([good, bad])
        assert merged["analysis"]["x"]["status"] == "not_run", bad
        assert merged["capabilities"] == []
    assert _ledger.merged_ledger([good, good])["versions"] == ["0.6.0"]
    assert "versions" not in _ledger.merged_ledger([{"analysis": {"x": {"status": "complete"}}}])


# ── coordinator accounting ───────────────────────────────────────────────────────────


def test_disabled_analyzers_report_not_run(tmp_path, monkeypatch):
    for spec in _ledger.ANALYZERS.values():
        monkeypatch.setitem(spec, "enabled", False)
    result = extract(detect(_project(tmp_path)), parallel=False)
    assert result["analysis"] == {name: {"status": "not_run"} for name in _ledger.ANALYZERS}


def test_enabled_analyzers_count_their_eligible_files(tmp_path, enabled):
    project = _project(tmp_path)
    analysis = extract(detect(project), parallel=False)["analysis"]
    apex, flow = analysis["callout-edges.apex"], analysis["callout-edges.flow-http"]
    assert apex["eligible"] == _count(project, "*.cls", "*.trigger") == 3 and apex["status"] == "complete"
    assert flow["eligible"] == _count(project, "*.flow-meta.xml") == 1
    assert apex["analyzed"] == apex["eligible"] and flow["analyzed"] == flow["eligible"]
    _assert_invariant(analysis)


def test_zero_eligible_files_is_complete(tmp_path, enabled):
    project = tmp_path / "proj"
    shutil.copytree(FIXTURES / "epicA_callout", project)
    shutil.rmtree(project / "force-app" / "main" / "default" / "flows")
    analysis = extract(detect(project), parallel=False)["analysis"]
    assert analysis["callout-edges.flow-http"] == {
        "status": "complete", "eligible": 0, "analyzed": 0, "failed": 0, "sites": 0, "unresolved": 0,
    }  # fmt: skip


def test_a_truncated_flow_withholds_the_flow_capability(tmp_path, enabled):
    project = _project(tmp_path)
    flows = project / "force-app" / "main" / "default" / "flows"
    (flows / "Broken.flow-meta.xml").write_text("<?xml version='1.0'?><Flow><unclosed>", encoding="utf-8")
    analysis = extract(detect(project), parallel=False)["analysis"]
    flow = analysis["callout-edges.flow-http"]
    assert (flow["status"], flow["eligible"], flow["analyzed"], flow["failed"]) == ("partial", 2, 1, 1)
    assert _ledger.derive_capabilities(analysis) == ["callout-edges.apex"]
    _assert_invariant(analysis)


def test_only_a_broken_flow_is_a_failed_analyzer(tmp_path, enabled):
    project = _project(tmp_path)
    flows = project / "force-app" / "main" / "default" / "flows"
    for f in flows.glob("*.flow-meta.xml"):
        f.write_text("<<<", encoding="utf-8")
    assert extract(detect(project), parallel=False)["analysis"]["callout-edges.flow-http"]["status"] == "failed"


def test_an_extractor_exception_counts_as_failed(tmp_path, enabled, monkeypatch):
    import graphify_sf.extract as ex

    def boom(path):
        raise RuntimeError("boom")

    monkeypatch.setitem(ex._DISPATCH, ".cls", boom)
    analysis = extract(detect(_project(tmp_path)), parallel=False)["analysis"]
    assert analysis["callout-edges.apex"]["status"] == "failed"
    assert analysis["callout-edges.apex"]["failed"] == 3
    _assert_invariant(analysis)


class _FakeExecutor:
    """Stands in for ProcessPoolExecutor: runs in-process, with scripted per-file failures."""

    raise_for: set[str] = set()
    broken_after: int | None = None

    def __init__(self, *args, **kwargs):
        self.submitted = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, path):
        self.submitted += 1
        fut: Future = Future()
        if self.broken_after is not None and self.submitted > self.broken_after:
            fut.set_exception(BrokenProcessPool("pool died"))
        elif path.name in self.raise_for:
            fut.set_exception(RuntimeError("worker blew up"))
        else:
            fut.set_result(fn(path))
        return fut


@pytest.fixture
def fake_pool(monkeypatch):
    import graphify_sf.extract as ex

    _FakeExecutor.raise_for = set()
    _FakeExecutor.broken_after = None
    monkeypatch.setattr(ex, "ProcessPoolExecutor", _FakeExecutor)
    return _FakeExecutor


def test_parallel_matches_sequential(tmp_path, enabled, fake_pool):
    detection = detect(_project(tmp_path, extra_classes=9))
    sequential = extract(detection, parallel=False)["analysis"]
    parallel = extract(detection, parallel=True)["analysis"]
    assert parallel == sequential
    assert sequential["callout-edges.apex"]["eligible"] == 12
    _assert_invariant(parallel)


def test_a_failed_worker_future_is_a_failed_file(tmp_path, enabled, fake_pool):
    fake_pool.raise_for = {"CalloutNamed.cls"}
    analysis = extract(detect(_project(tmp_path, extra_classes=9)), parallel=True)["analysis"]
    apex = analysis["callout-edges.apex"]
    assert (apex["status"], apex["eligible"], apex["failed"]) == ("partial", 12, 1)
    _assert_invariant(analysis)


def test_pool_break_falls_back_to_sequential_and_rebuilds_outcomes(tmp_path, enabled, fake_pool):
    fake_pool.broken_after = 5  # five results arrive, then the pool dies
    analysis = extract(detect(_project(tmp_path, extra_classes=9)), parallel=True)["analysis"]
    apex = analysis["callout-edges.apex"]
    assert (apex["status"], apex["eligible"], apex["analyzed"], apex["failed"]) == ("complete", 12, 12, 0)
    _assert_invariant(analysis)


# ── graph.json round trips ───────────────────────────────────────────────────────────


def _build(tmp_path: Path, name: str = "out") -> tuple[Path, Path]:
    from graphify_sf.__main__ import _run_pipeline

    project = _project(tmp_path) if not (tmp_path / "proj").exists() else tmp_path / "proj"
    out = tmp_path / name
    _run_pipeline(project, out, update=False, directed=False, no_viz=True, max_workers=1, force=True)
    return project, out


def _graph_json(out: Path) -> dict:
    return json.loads((out / "graph.json").read_text())


def test_pipeline_writes_the_block_once_at_the_top_level(tmp_path, enabled):
    from graphify_sf.__main__ import __version__

    _, out = _build(tmp_path)
    data = _graph_json(out)
    block = data["graphify_sf"]
    assert block["version"] == __version__
    assert block["capabilities"] == ["callout-edges.apex", "callout-edges.flow-http"]
    assert "graphify_sf" not in data["graph"], "the ledger must not be duplicated under 'graph'"
    _assert_invariant(block["analysis"])


def test_default_build_advertises_both_shipped_analyzers(tmp_path):
    """Both callout analyzers ship in 0.6.0; a clean build advertises both."""
    _, out = _build(tmp_path)
    block = _graph_json(out)["graphify_sf"]
    assert block["capabilities"] == ["callout-edges.apex", "callout-edges.flow-http"]
    assert {v["status"] for v in block["analysis"].values()} == {"complete"}


def test_cluster_only_and_export_json_pass_the_block_through(tmp_path, enabled):
    from graphify_sf.__main__ import _cmd_cluster_only, _cmd_export_json

    project, out = _build(tmp_path)
    before = _graph_json(out)["graphify_sf"]
    _cmd_cluster_only(project, out, no_viz=True)
    assert _graph_json(out)["graphify_sf"] == before
    other = tmp_path / "exported"
    _cmd_export_json(out / "graph.json", other)
    assert _graph_json(other)["graphify_sf"] == before


def test_graphs_without_a_block_never_gain_one(tmp_path):
    from graphify_sf.__main__ import _cmd_cluster_only, _cmd_export_json

    project, out = _build(tmp_path)
    data = _graph_json(out)
    data.pop("graphify_sf")  # a graph built before 0.6.0
    (out / "graph.json").write_text(json.dumps(data), encoding="utf-8")
    _cmd_cluster_only(project, out, no_viz=True)
    assert "graphify_sf" not in _graph_json(out)
    other = tmp_path / "exported"
    _cmd_export_json(out / "graph.json", other)
    assert "graphify_sf" not in _graph_json(other)


def _graph_with(path: Path, block: dict | None) -> Path:
    data = {
        "nodes": [{"id": "apex_a", "label": "A", "sf_type": "ApexClass", "file_type": "apex"}],
        "links": [],
    }
    if block is not None:
        data["graphify_sf"] = block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _block(status: str) -> dict:
    return {
        "version": "0.6.0",
        "analysis": {"callout-edges.apex": {"status": status, "eligible": 4, "analyzed": 4, "failed": 0}},
        "capabilities": ["callout-edges.apex"] if status == "complete" else [],
    }


def test_merge_graphs_writes_a_status_only_meet(tmp_path):
    from graphify_sf.__main__ import _cmd_merge_graphs

    a = _graph_with(tmp_path / "a" / "graph.json", _block("complete"))
    b = _graph_with(tmp_path / "b" / "graph.json", _block("partial"))
    out = tmp_path / "merged" / "graph.json"
    _cmd_merge_graphs([a, b], out, no_viz=True)
    merged = json.loads(out.read_text())["graphify_sf"]
    assert merged == {
        "scope": "merged",
        "analysis": {"callout-edges.apex": {"status": "partial"}},
        "capabilities": [],
        "versions": ["0.6.0"],
    }


def test_merge_graphs_without_any_block_writes_none(tmp_path):
    from graphify_sf.__main__ import _cmd_merge_graphs

    a = _graph_with(tmp_path / "a" / "graph.json", None)
    b = _graph_with(tmp_path / "b" / "graph.json", None)
    out = tmp_path / "merged" / "graph.json"
    _cmd_merge_graphs([a, b], out, no_viz=True)
    assert "graphify_sf" not in json.loads(out.read_text())


def test_merge_graphs_with_one_block_does_not_claim_coverage(tmp_path):
    from graphify_sf.__main__ import _cmd_merge_graphs

    a = _graph_with(tmp_path / "a" / "graph.json", _block("complete"))
    b = _graph_with(tmp_path / "b" / "graph.json", None)
    out = tmp_path / "merged" / "graph.json"
    _cmd_merge_graphs([a, b], out, no_viz=True)
    assert json.loads(out.read_text())["graphify_sf"]["capabilities"] == []


def test_merge_driver_ignores_the_bases_ledger(tmp_path):
    from graphify_sf.__main__ import _cmd_merge_driver

    base = _graph_with(tmp_path / "base.json", _block("partial"))  # would drag the meet down if it counted
    ours = _graph_with(tmp_path / "ours.json", _block("complete"))
    theirs = _graph_with(tmp_path / "theirs.json", _block("complete"))
    _cmd_merge_driver(base, ours, theirs)
    assert json.loads(ours.read_text())["graphify_sf"]["capabilities"] == ["callout-edges.apex"]


def test_merge_driver_writes_the_meet_of_ours_and_theirs(tmp_path):
    from graphify_sf.__main__ import _cmd_merge_driver

    base = _graph_with(tmp_path / "base.json", _block("complete"))
    ours = _graph_with(tmp_path / "ours.json", _block("complete"))
    theirs = _graph_with(tmp_path / "theirs.json", _block("partial"))
    _cmd_merge_driver(base, ours, theirs)
    merged = json.loads(ours.read_text())["graphify_sf"]
    assert merged["scope"] == "merged" and merged["capabilities"] == []
    assert merged["analysis"]["callout-edges.apex"] == {"status": "partial"}


def test_only_the_top_level_block_counts(tmp_path):
    """A nested graph.graphify_sf (hand-built or from an odd tool) is never promoted to a ledger."""
    from graphify_sf.__main__ import _cmd_export_json, _load_graph_from_json

    nested = tmp_path / "nested" / "graph.json"
    nested.parent.mkdir()
    nested.write_text(
        json.dumps(
            {
                "nodes": [{"id": "a", "label": "A", "sf_type": "ApexClass", "file_type": "apex"}],
                "links": [],
                "graph": {"graphify_sf": _block("complete")},
            }
        ),
        encoding="utf-8",
    )
    G, raw = _load_graph_from_json(nested)
    assert "graphify_sf" not in G.graph
    assert "graphify_sf" in raw["graph"], "loading must not mutate the caller's raw dict"
    _cmd_export_json(nested, tmp_path / "exported")
    exported = json.loads((tmp_path / "exported" / "graph.json").read_text())
    assert "graphify_sf" not in exported and "graphify_sf" not in exported["graph"]


def test_an_empty_top_level_block_is_not_written_anywhere(tmp_path):
    from graphify_sf.__main__ import _cmd_export_json

    empty = _graph_with(tmp_path / "e" / "graph.json", {})
    _cmd_export_json(empty, tmp_path / "exported")
    exported = json.loads((tmp_path / "exported" / "graph.json").read_text())
    assert "graphify_sf" not in exported and "graphify_sf" not in exported["graph"]


def test_the_block_is_written_once_even_when_the_graph_dict_also_holds_one(tmp_path):
    import networkx as nx

    from graphify_sf.export import to_json

    G = nx.MultiDiGraph()
    G.add_node("a", label="A", sf_type="ApexClass", file_type="apex")
    G.graph["graphify_sf"] = _block("complete")
    to_json(G, {}, str(tmp_path / "graph.json"), force=True)
    data = json.loads((tmp_path / "graph.json").read_text())
    assert data["graphify_sf"] == _block("complete") and "graphify_sf" not in data["graph"]


# ── surfaces ─────────────────────────────────────────────────────────────────────────


def test_stats_command_prints_the_coverage_section(tmp_path, enabled, capsys):
    from graphify_sf.__main__ import _cmd_stats

    _, out = _build(tmp_path)
    _cmd_stats(out / "graph.json")
    text = capsys.readouterr().out
    assert "Analysis coverage:" in text and "callout-edges.apex" in text and "Capabilities:" in text


def test_stats_command_says_so_when_there_is_no_block(tmp_path, capsys):
    from graphify_sf.__main__ import _cmd_stats

    _cmd_stats(_graph_with(tmp_path / "graph.json", None))
    assert "coverage ledger" in capsys.readouterr().out


def test_stats_command_survives_a_hand_edited_ledger(tmp_path, capsys):
    from graphify_sf.__main__ import _cmd_stats

    block = {
        "version": "x",
        "analysis": {"callout-edges.apex": {"status": "complete", "eligible": 3}},
        "capabilities": [],
    }
    _cmd_stats(_graph_with(tmp_path / "graph.json", block))
    assert "eligible 3" in capsys.readouterr().out


def test_mcp_graph_stats_says_null_when_the_graph_has_no_block(tmp_path):
    from graphify_sf import serve

    serve._G = None
    serve._ensure_graph(str(_graph_with(tmp_path / "graph.json", None)))
    stats = serve._tool_graph_stats({})
    assert stats["analysis"] is None and stats["capabilities"] is None


def test_mcp_graph_stats_exposes_analysis_and_capabilities(tmp_path, enabled):
    from graphify_sf import serve

    _, out = _build(tmp_path)
    serve._ensure_graph(str(out / "graph.json"))
    stats = serve._tool_graph_stats({})
    assert stats["capabilities"] == ["callout-edges.apex", "callout-edges.flow-http"]
    assert stats["analysis"]["callout-edges.apex"]["status"] == "complete"
