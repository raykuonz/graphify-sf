"""Shared test fixtures for graphify-sf."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SIMPLE_PROJECT = FIXTURES_DIR / "simple_project"


@pytest.fixture
def simple_project_path():
    return SIMPLE_PROJECT


@pytest.fixture
def simple_detect_result(simple_project_path):
    from graphify_sf.detect import detect

    return detect(simple_project_path)


@pytest.fixture
def simple_extraction(simple_detect_result):
    from graphify_sf.extract import extract

    return extract(simple_detect_result, parallel=False)


@pytest.fixture
def simple_graph(simple_extraction):
    from graphify_sf.build import build_from_json, deduplicate_by_label

    nodes, edges = deduplicate_by_label(simple_extraction["nodes"], simple_extraction["edges"])
    return build_from_json({"nodes": nodes, "edges": edges})


@pytest.fixture
def simple_communities(simple_graph):
    from graphify_sf.cluster import cluster

    return cluster(simple_graph)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """With GRAPHIFY_SF_FAIL_ON_SKIP=1 (CI's all-extras job), a skip is a failure.

    Optional-dependency tests use pytest.importorskip. In an environment that
    installs every extra, a skip means an extra silently failed to install or
    import, which would otherwise leave CI green with the real-SDK/Leiden tests unrun.
    """
    outcome = yield
    report = outcome.get_result()
    if os.environ.get("GRAPHIFY_SF_FAIL_ON_SKIP") == "1" and report.skipped and not hasattr(report, "wasxfail"):
        reason = report.longrepr[-1] if isinstance(report.longrepr, tuple) else report.longrepr
        report.outcome = "failed"
        report.longrepr = f"skipped while GRAPHIFY_SF_FAIL_ON_SKIP=1: {reason}"


def pytest_sessionfinish(session, exitstatus):
    """Also fail on skips the hook above never sees (module-level importorskip at collection)."""
    if os.environ.get("GRAPHIFY_SF_FAIL_ON_SKIP") != "1":
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None and reporter.stats.get("skipped") and session.exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
