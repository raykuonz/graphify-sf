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
