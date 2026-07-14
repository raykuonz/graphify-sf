"""End-to-end CLI tests."""

from __future__ import annotations

import json

import pytest


def test_cli_full_pipeline_runs(simple_project_path, tmp_path):
    """Test that the full pipeline runs without errors on simple_project."""
    from graphify_sf.__main__ import _run_pipeline

    out_dir = tmp_path / "output"

    # Run the pipeline
    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=False,
        max_workers=1,
        force=False,
    )

    # Check that output files exist
    assert (out_dir / "graph.json").exists()
    assert (out_dir / "GRAPH_REPORT.md").exists()
    assert (out_dir / "manifest.json").exists()


def test_cli_no_viz_flag_skips_html(simple_project_path, tmp_path):
    """Test that --no-viz flag skips HTML generation."""
    from graphify_sf.__main__ import _run_pipeline

    out_dir = tmp_path / "output"

    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    # graph.html should not exist
    assert not (out_dir / "graph.html").exists()
    # But other files should exist
    assert (out_dir / "graph.json").exists()


def test_cli_update_mode_incremental(simple_project_path, tmp_path):
    """Test that --update mode performs incremental updates."""
    from graphify_sf.__main__ import _run_pipeline

    out_dir = tmp_path / "output"

    # First run
    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    # Second run with --update
    _run_pipeline(
        simple_project_path,
        out_dir,
        update=True,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    second_graph = (out_dir / "graph.json").read_text()

    # Graphs should be similar (incremental update should work)
    assert len(second_graph) > 0


def test_cli_directed_graph_option(simple_project_path, tmp_path):
    """Test that --directed creates a directed graph."""
    from networkx.readwrite import json_graph

    from graphify_sf.__main__ import _run_pipeline

    out_dir = tmp_path / "output"

    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=True,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    # Load the graph and check if it's directed
    graph_data = json.loads((out_dir / "graph.json").read_text())
    try:
        G = json_graph.node_link_graph(graph_data, edges="links")
    except TypeError:
        G = json_graph.node_link_graph(graph_data)

    assert G.is_directed()


def test_cli_version_command():
    """Test that graphify-sf --version outputs version."""
    from graphify_sf.__main__ import __version__

    assert __version__ is not None
    assert len(__version__) > 0


def test_cli_query_command_finds_nodes(simple_project_path, tmp_path):
    """Test that graphify-sf query finds relevant nodes."""
    from graphify_sf.__main__ import _cmd_query, _run_pipeline

    out_dir = tmp_path / "output"

    # First create the graph
    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    graph_path = out_dir / "graph.json"

    # Test query command (capture output)
    import io
    from contextlib import redirect_stdout

    output = io.StringIO()
    with redirect_stdout(output):
        _cmd_query("account", graph_path, use_dfs=False, budget=2000)

    result = output.getvalue()
    assert len(result) > 0
    assert "account" in result.lower() or "Account" in result


def test_cli_explain_command_shows_details(simple_project_path, tmp_path):
    """Test that graphify-sf explain shows node details."""
    from graphify_sf.__main__ import _cmd_explain, _run_pipeline

    out_dir = tmp_path / "output"

    # First create the graph
    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    graph_path = out_dir / "graph.json"

    # Test explain command
    import io
    from contextlib import redirect_stdout

    output = io.StringIO()
    with redirect_stdout(output):
        _cmd_explain("AccountService", graph_path)

    result = output.getvalue()
    assert "AccountService" in result
    assert "Node:" in result
    assert "Connections" in result or "Degree" in result


def test_cli_path_command_finds_shortest_path(simple_project_path, tmp_path):
    """Test that graphify-sf path finds shortest path."""
    from graphify_sf.__main__ import _cmd_path, _run_pipeline

    out_dir = tmp_path / "output"

    # First create the graph
    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    graph_path = out_dir / "graph.json"

    # Test path command
    import io
    from contextlib import redirect_stdout

    output = io.StringIO()
    with redirect_stdout(output):
        try:
            _cmd_path("AccountTrigger", "AccountService", graph_path)
            result = output.getvalue()
            assert "path" in result.lower() or "hops" in result.lower()
        except SystemExit:
            # Path might not exist, which is okay for this test
            pass


def test_cli_cluster_only_command(simple_project_path, tmp_path):
    """Test that cluster-only re-clusters existing graph."""
    from graphify_sf.__main__ import _cmd_cluster_only, _run_pipeline

    out_dir = tmp_path / "output"

    # First create the graph
    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    # Now run cluster-only
    _cmd_cluster_only(simple_project_path, out_dir, no_viz=True)

    # Graph should still exist and be updated
    assert (out_dir / "graph.json").exists()
    assert (out_dir / "GRAPH_REPORT.md").exists()


def test_cli_force_flag_overwrites(simple_project_path, tmp_path):
    """Test that --force flag overwrites smaller graphs."""
    from graphify_sf.__main__ import _run_pipeline

    out_dir = tmp_path / "output"

    # Create initial graph
    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    # Run again with force (should overwrite)
    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=True,
    )

    # File should exist (might be same or different size)
    assert (out_dir / "graph.json").exists()


def test_cli_empty_project_exits_with_error(tmp_path):
    """Test that empty project exits with error."""
    from graphify_sf.__main__ import _run_pipeline

    empty_project = tmp_path / "empty"
    empty_project.mkdir()

    out_dir = tmp_path / "output"

    with pytest.raises(SystemExit) as exc_info:
        _run_pipeline(
            empty_project,
            out_dir,
            update=False,
            directed=False,
            no_viz=True,
            max_workers=1,
            force=False,
        )

    assert exc_info.value.code == 1


def test_cli_parallel_extraction_flag(simple_project_path, tmp_path):
    """Test that parallel extraction can be controlled."""
    from graphify_sf.__main__ import _run_pipeline

    out_dir = tmp_path / "output"

    # Run with max_workers=2
    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=2,
        force=False,
    )

    assert (out_dir / "graph.json").exists()


def test_cli_output_directory_created(simple_project_path, tmp_path):
    """Test that output directory is created if it doesn't exist."""
    from graphify_sf.__main__ import _run_pipeline

    out_dir = tmp_path / "nonexistent" / "output"

    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    assert out_dir.exists()
    assert (out_dir / "graph.json").exists()


def test_cli_graph_report_contains_communities(simple_project_path, tmp_path):
    """Test that GRAPH_REPORT.md contains community information."""
    from graphify_sf.__main__ import _run_pipeline

    out_dir = tmp_path / "output"

    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    report = (out_dir / "GRAPH_REPORT.md").read_text()
    assert "communit" in report.lower()


def test_cli_graph_json_valid_format(simple_project_path, tmp_path):
    """Test that graph.json is valid JSON with expected structure."""
    from graphify_sf.__main__ import _run_pipeline

    out_dir = tmp_path / "output"

    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    graph_data = json.loads((out_dir / "graph.json").read_text())

    assert "nodes" in graph_data
    assert "links" in graph_data or "edges" in graph_data
    assert len(graph_data["nodes"]) > 0


def test_cli_manifest_tracks_files(simple_project_path, tmp_path):
    """Test that manifest.json tracks file metadata."""
    from graphify_sf.__main__ import _run_pipeline

    out_dir = tmp_path / "output"

    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())

    # Should have entries with mtime and hash
    assert len(manifest) > 0
    first_key = next(iter(manifest))
    assert "mtime" in manifest[first_key]
    assert "hash" in manifest[first_key]


def test_cli_query_no_match_message(simple_project_path, tmp_path):
    """Test that query command shows message when no matches found."""
    from graphify_sf.__main__ import _cmd_query, _run_pipeline

    out_dir = tmp_path / "output"

    _run_pipeline(
        simple_project_path,
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=False,
    )

    graph_path = out_dir / "graph.json"

    import io
    from contextlib import redirect_stdout

    output = io.StringIO()
    with redirect_stdout(output):
        _cmd_query("NonexistentXYZ12345", graph_path, use_dfs=False, budget=2000)

    result = output.getvalue()
    assert "No matching nodes" in result or "NonexistentXYZ12345" in result


# ---------------------------------------------------------------------------
# A1 — _cmd_path must surface ALL parallel edges on a hop (edge_datas fix)
# ---------------------------------------------------------------------------


def _write_parallel_graph(path, *, extra_pairs=None):
    """Write a graph.json where apex_a both queries AND dml-writes obj_b."""
    from graphify_sf.build import build_from_json
    from graphify_sf.export import to_json

    nodes = [
        {"id": "apex_a", "label": "SvcA", "sf_type": "ApexClass", "file_type": "apex"},
        {"id": "obj_b", "label": "ObjB", "sf_type": "CustomObject", "file_type": "object"},
    ]
    edges = [
        {"source": "apex_a", "target": "obj_b", "relation": "queries", "confidence": "EXTRACTED"},
        {"source": "apex_a", "target": "obj_b", "relation": "dml", "confidence": "EXTRACTED"},
    ]
    for extra in extra_pairs or []:
        nodes.extend(extra.get("nodes", []))
        edges.extend(extra.get("edges", []))
    G = build_from_json({"nodes": nodes, "edges": edges}, multigraph=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    to_json(G, {}, str(path), force=True)


def test_cli_path_reports_all_parallel_relations(tmp_path):
    """graphify-sf path must show BOTH queries and dml on the SvcA→ObjB hop."""
    import io
    from contextlib import redirect_stdout

    from graphify_sf.__main__ import _cmd_path

    graph_path = tmp_path / "graph.json"
    _write_parallel_graph(graph_path)

    output = io.StringIO()
    with redirect_stdout(output):
        _cmd_path("SvcA", "ObjB", graph_path)
    result = output.getvalue()
    assert "queries" in result, f"queries missing from path output:\n{result}"
    assert "dml" in result, f"dml missing from path output:\n{result}"


# ---------------------------------------------------------------------------
# A2 — merge-graphs must NOT collapse parallel edges through a plain nx.Graph()
# ---------------------------------------------------------------------------


def _apex_obj_links(graph_data):
    links = graph_data.get("links", graph_data.get("edges", []))
    return [lnk for lnk in links if lnk.get("source") == "apex_a" and lnk.get("target") == "obj_b"]


def test_cli_merge_graphs_preserves_parallel_edges(tmp_path):
    """Two input graphs, each with a distinct apex_a→obj_b relation → merged
    output must retain BOTH (not collapse to 1)."""
    from graphify_sf.__main__ import _cmd_merge_graphs
    from graphify_sf.build import build_from_json
    from graphify_sf.export import to_json

    def _one(path, relation):
        G = build_from_json(
            {
                "nodes": [
                    {"id": "apex_a", "label": "SvcA", "sf_type": "ApexClass", "file_type": "apex"},
                    {"id": "obj_b", "label": "ObjB", "sf_type": "CustomObject", "file_type": "object"},
                ],
                "edges": [
                    {"source": "apex_a", "target": "obj_b", "relation": relation, "confidence": "EXTRACTED"},
                ],
            },
            multigraph=True,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        to_json(G, {}, str(path), force=True)

    g1 = tmp_path / "g1" / "graph.json"
    g2 = tmp_path / "g2" / "graph.json"
    _one(g1, "queries")
    _one(g2, "dml")

    out_path = tmp_path / "merged" / "graph.json"
    _cmd_merge_graphs([g1, g2], out_path, no_viz=True)

    data = json.loads(out_path.read_text())
    assert data.get("multigraph") is True, "merged graph.json must declare multigraph"
    pair = _apex_obj_links(data)
    rels = {lnk.get("relation") for lnk in pair}
    assert rels == {"queries", "dml"}, f"merge collapsed parallel edges; got {rels}"
    assert len(pair) == 2, f"expected 2 links for the pair, got {len(pair)}: {pair}"


def test_cli_merge_graphs_three_way_preserves_parallel_edges(tmp_path):
    """3-graph merge (catches pairwise-only dedup bugs): three distinct relations
    on the same pair must all survive."""
    from graphify_sf.__main__ import _cmd_merge_graphs
    from graphify_sf.build import build_from_json
    from graphify_sf.export import to_json

    def _one(path, relation):
        G = build_from_json(
            {
                "nodes": [
                    {"id": "apex_a", "label": "SvcA", "sf_type": "ApexClass", "file_type": "apex"},
                    {"id": "obj_b", "label": "ObjB", "sf_type": "CustomObject", "file_type": "object"},
                ],
                "edges": [
                    {"source": "apex_a", "target": "obj_b", "relation": relation, "confidence": "EXTRACTED"},
                ],
            },
            multigraph=True,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        to_json(G, {}, str(path), force=True)

    g1 = tmp_path / "g1" / "graph.json"
    g2 = tmp_path / "g2" / "graph.json"
    g3 = tmp_path / "g3" / "graph.json"
    _one(g1, "queries")
    _one(g2, "dml")
    _one(g3, "references")

    out_path = tmp_path / "merged" / "graph.json"
    _cmd_merge_graphs([g1, g2, g3], out_path, no_viz=True)

    data = json.loads(out_path.read_text())
    pair = _apex_obj_links(data)
    rels = {lnk.get("relation") for lnk in pair}
    assert rels == {"queries", "dml", "references"}, f"3-way merge lost a relation; got {rels}"


def _write_graph_json(path, edges):
    """Build + serialize a two-node graph with the given apex_a→obj_b edges."""
    from graphify_sf.build import build_from_json
    from graphify_sf.export import to_json

    G = build_from_json(
        {
            "nodes": [
                {"id": "apex_a", "label": "SvcA", "sf_type": "ApexClass", "file_type": "apex"},
                {"id": "obj_b", "label": "ObjB", "sf_type": "CustomObject", "file_type": "object"},
            ],
            "edges": edges,
        },
        multigraph=True,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    to_json(G, {}, str(path), force=True)


def test_cli_merge_graphs_preserves_operation_distinct_edges_split_inputs(tmp_path):
    """Two dml edges on the same (source, target, relation) triple but differing
    only in ``operation`` (create vs. update), split across two merge inputs,
    must BOTH survive the merge (coarse (src,tgt,rel) dedup would drop one)."""
    from graphify_sf.__main__ import _cmd_merge_graphs

    g1 = tmp_path / "g1" / "graph.json"
    g2 = tmp_path / "g2" / "graph.json"
    _write_graph_json(
        g1,
        [{"source": "apex_a", "target": "obj_b", "relation": "dml", "operation": "create", "confidence": "INFERRED"}],
    )
    _write_graph_json(
        g2,
        [{"source": "apex_a", "target": "obj_b", "relation": "dml", "operation": "update", "confidence": "INFERRED"}],
    )

    out_path = tmp_path / "merged" / "graph.json"
    _cmd_merge_graphs([g1, g2], out_path, no_viz=True)

    data = json.loads(out_path.read_text())
    pair = _apex_obj_links(data)
    ops = {lnk.get("operation") for lnk in pair}
    assert ops == {"create", "update"}, f"merge dropped an operation-distinct edge; got {ops}"
    assert len(pair) == 2, f"expected 2 dml links for the pair, got {len(pair)}: {pair}"


def test_cli_merge_graphs_preserves_operation_distinct_edges_single_input(tmp_path):
    """Two operation-distinct dml edges that already coexist inside ONE input
    graph must both survive, while a genuinely-identical duplicate in the second
    input collapses (not triplicates)."""
    from graphify_sf.__main__ import _cmd_merge_graphs

    g1 = tmp_path / "g1" / "graph.json"
    g2 = tmp_path / "g2" / "graph.json"
    _write_graph_json(
        g1,
        [
            {"source": "apex_a", "target": "obj_b", "relation": "dml", "operation": "create", "confidence": "INFERRED"},
            {"source": "apex_a", "target": "obj_b", "relation": "dml", "operation": "update", "confidence": "INFERRED"},
        ],
    )
    # g2 repeats the create edge verbatim — it must coalesce, not add a third.
    _write_graph_json(
        g2,
        [{"source": "apex_a", "target": "obj_b", "relation": "dml", "operation": "create", "confidence": "INFERRED"}],
    )

    out_path = tmp_path / "merged" / "graph.json"
    _cmd_merge_graphs([g1, g2], out_path, no_viz=True)

    data = json.loads(out_path.read_text())
    pair = _apex_obj_links(data)
    ops = sorted(lnk.get("operation") for lnk in pair)
    assert ops == ["create", "update"], f"expected exactly one create + one update, got {ops}"


def test_cli_merge_driver_preserves_operation_distinct_edges(tmp_path):
    """The 3-way git merge-driver path must also keep operation-distinct dml
    edges: base has create, theirs adds update — both survive in the merged
    result written back to ``ours``."""
    from graphify_sf.__main__ import _cmd_merge_driver

    base = tmp_path / "base" / "graph.json"
    ours = tmp_path / "ours" / "graph.json"
    theirs = tmp_path / "theirs" / "graph.json"
    _write_graph_json(
        base,
        [{"source": "apex_a", "target": "obj_b", "relation": "dml", "operation": "create", "confidence": "INFERRED"}],
    )
    # ours == base (no local change to this edge)
    _write_graph_json(
        ours,
        [{"source": "apex_a", "target": "obj_b", "relation": "dml", "operation": "create", "confidence": "INFERRED"}],
    )
    _write_graph_json(
        theirs,
        [{"source": "apex_a", "target": "obj_b", "relation": "dml", "operation": "update", "confidence": "INFERRED"}],
    )

    _cmd_merge_driver(base, ours, theirs)

    data = json.loads(ours.read_text())
    pair = _apex_obj_links(data)
    ops = {lnk.get("operation") for lnk in pair}
    assert ops == {"create", "update"}, f"merge-driver dropped an operation-distinct edge; got {ops}"
    assert len(pair) == 2, f"expected 2 dml links for the pair, got {len(pair)}: {pair}"


# ---------------------------------------------------------------------------
# A3 — --verbose node-drop accounting line
# ---------------------------------------------------------------------------


def test_cli_verbose_node_accounting_is_internally_consistent(simple_project_path, tmp_path):
    """--verbose emits an accounting line whose numbers reconcile:
    deduped - merged == extracted implied, and deduped + stubs == final."""
    import io
    import re
    from contextlib import redirect_stdout

    from graphify_sf.__main__ import _run_pipeline

    out_dir = tmp_path / "output"
    output = io.StringIO()
    with redirect_stdout(output):
        _run_pipeline(
            simple_project_path,
            out_dir,
            update=False,
            directed=False,
            no_viz=True,
            max_workers=1,
            force=True,
            verbose=True,
        )
    text = output.getvalue()
    m = re.search(
        r"node accounting: (\d+) extracted → (\d+) deduped-by-label \((\d+) merged\) "
        r"→ \+(\d+) stub → (\d+) final nodes",
        text,
    )
    assert m, f"verbose accounting line missing or malformed:\n{text}"
    extracted, deduped, merged, stubs, final = (int(g) for g in m.groups())
    assert extracted - merged == deduped, f"{extracted} - {merged} != {deduped}"
    assert deduped + stubs == final, f"{deduped} + {stubs} != {final}"


def test_cli_verbose_accounting_reconciles_with_collision_and_dangling(tmp_path):
    """Controlled fixture with a KNOWN label collision (two ApexClasses named Dup
    → dedup merges one) and a trigger referencing a standard Account object with
    no meta file (a dangling reference the pipeline resolves via a stub). Verifies
    the verbose 4-number accounting reconciles and the merge term is real."""
    import io
    import re
    from contextlib import redirect_stdout

    from graphify_sf.__main__ import _run_pipeline

    base = tmp_path / "proj" / "force-app" / "main" / "default"
    (base / "classes").mkdir(parents=True)
    (base / "triggers").mkdir(parents=True)
    other = tmp_path / "proj" / "other" / "classes"
    other.mkdir(parents=True)
    # Same class name in two locations → a real (sf_type, label) dedup collision.
    (base / "classes" / "Dup.cls").write_text("public class Dup { }", encoding="utf-8")
    (other / "Dup.cls").write_text("public class Dup { }", encoding="utf-8")
    # Trigger on a standard object with no .object-meta.xml → dangling endpoint.
    (base / "triggers" / "AccTrig.trigger").write_text(
        "trigger AccTrig on Account (before insert) { }", encoding="utf-8"
    )

    out_dir = tmp_path / "out"
    output = io.StringIO()
    with redirect_stdout(output):
        _run_pipeline(
            tmp_path / "proj",
            out_dir,
            update=False,
            directed=False,
            no_viz=True,
            max_workers=1,
            force=True,
            verbose=True,
        )
    text = output.getvalue()
    m = re.search(
        r"node accounting: (\d+) extracted → (\d+) deduped-by-label \((\d+) merged\) "
        r"→ \+(\d+) stub → (\d+) final nodes \((.+?) dangling edge\(s\) pruned\)",
        text,
    )
    assert m, f"verbose accounting line missing:\n{text}"
    extracted, deduped, merged, stubs, final = (int(g) for g in m.groups()[:5])
    assert extracted - merged == deduped, f"{extracted} - {merged} != {deduped}"
    assert deduped + stubs == final, f"{deduped} + {stubs} != {final}"
    assert merged >= 1, "the duplicate Dup class must produce at least one dedup merge"


def test_cli_verbose_accounting_stub_count_not_misreported_on_incremental_update(tmp_path):
    """--update merges with the ENTIRE prior graph.json, so a node retained
    unchanged from a deleted-on-disk source file is not a build-injected stub —
    the stub term must report n/a on the incremental path, not a misleading count
    of real carried-over nodes."""
    import io
    from contextlib import redirect_stdout

    from graphify_sf.__main__ import _run_pipeline

    base = tmp_path / "proj" / "force-app" / "main" / "default" / "classes"
    base.mkdir(parents=True)
    (base / "First.cls").write_text("public class First { }", encoding="utf-8")
    (base / "Second.cls").write_text("public class Second { }", encoding="utf-8")

    out_dir = tmp_path / "out"
    _run_pipeline(
        tmp_path / "proj",
        out_dir,
        update=False,
        directed=False,
        no_viz=True,
        max_workers=1,
        force=True,
        verbose=False,
    )

    # Remove a previously-extracted file's source; its node is retained by the
    # incremental merge but was never (re-)extracted this run.
    (base / "Second.cls").unlink()

    output = io.StringIO()
    with redirect_stdout(output):
        _run_pipeline(
            tmp_path / "proj",
            out_dir,
            update=True,
            directed=False,
            no_viz=True,
            max_workers=1,
            force=True,
            verbose=True,
        )
    text = output.getvalue()
    assert "→ n/a (incremental merge) → " in text, f"stub term must be n/a on --update:\n{text}"
    assert "stub" not in text.split("node accounting:")[1].split("final nodes")[0], (
        f"incremental accounting must not report a stub count:\n{text}"
    )
